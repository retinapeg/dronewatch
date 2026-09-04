"""SSE transport and additive operator APIs; no changes to legacy route contracts."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if __package__:
    from .inference import ModelUnavailable, availability
else:
    from inference import ModelUnavailable, availability


class EventHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.listeners = {}

    def subscribe(self):
        queue = asyncio.Queue(maxsize=256)
        with self.lock:
            self.listeners[queue] = asyncio.get_running_loop()
        return queue

    def unsubscribe(self, queue):
        with self.lock:
            self.listeners.pop(queue, None)

    def publish(self, kind, payload):
        def deliver(queue):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait((kind, payload))
        with self.lock:
            listeners = list(self.listeners.items())
        for queue, loop in listeners:
            if not loop.is_closed():
                loop.call_soon_threadsafe(deliver, queue)


def sse(kind, payload, event_id=None):
    identity = f"id: {event_id}\n" if event_id is not None else ""
    return f"{identity}event: {kind}\ndata: {json.dumps(payload, separators=(',', ':'), allow_nan=False)}\n\n"


async def stream_events(request, hub, snapshot, query_since, runtime, mode, after_id=0, heartbeat=10):
    queue = hub.subscribe()
    try:
        initial = snapshot()
        cursor = initial["latest"]["id"] if initial["latest"] else 0
        if after_id:
            for event in query_since(after_id, cursor):
                yield sse("observation", event, event["id"])
        yield sse("snapshot", {**initial, "console": runtime.snapshot(mode)}, cursor)
        heartbeat_deadline = time.monotonic() + heartbeat
        while not await request.is_disconnected():
            # Unrelated source traffic must not restart this deadline. A busy
            # replay previously starved heartbeats for quiet Viso subscribers.
            remaining = heartbeat_deadline - time.monotonic()
            if remaining <= 0:
                yield sse("heartbeat", {"timestamp": time.time(), "console": runtime.snapshot(mode)})
                heartbeat_deadline = time.monotonic() + heartbeat
                continue
            try:
                kind, value = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                yield sse("heartbeat", {"timestamp": time.time(), "console": runtime.snapshot(mode)})
                heartbeat_deadline = time.monotonic() + heartbeat
                continue
            if kind == "observation":
                if value["id"] <= cursor:
                    continue
                # Catch up through SQLite if a slow client's notification queue overflowed.
                for event in query_since(cursor, value["id"]):
                    cursor = event["id"]
                    yield sse("observation", event, cursor)
                yield sse("snapshot", {**snapshot(), "console": runtime.snapshot(mode)}, cursor)
            elif kind == "reset":
                yield sse("console", runtime.snapshot(mode))
            elif kind == "console" and value.get("mode") == mode:
                yield sse("console", value)
    finally:
        hub.unsubscribe(queue)


class ReplayControl(BaseModel):
    action: Literal["play", "pause", "restart"]
    loop: Optional[bool] = None


class ModeRequest(BaseModel):
    mode: Literal["VISO_LIVE", "BENCHMARK_REPLAY", "LOCAL_INFERENCE"] = "VISO_LIVE"


def install_console(app, runtime, snapshot, query_since, root):
    hub = EventHub()
    runtime.publish = hub.publish
    app.state.console = runtime
    app.state.event_hub = hub
    app.mount("/static", StaticFiles(directory=root / "static"), name="static")

    @app.on_event("startup")
    async def start_console():
        async def tick():
            while True:
                runtime.tick()
                await asyncio.sleep(0.1)
        app.state.console_task = asyncio.create_task(tick())

    @app.on_event("shutdown")
    async def stop_console():
        app.state.console_task.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.console_task
        runtime.local_runner.stop()

    @app.get("/api/stream")
    async def stream(request: Request, mode: str = "VISO_LIVE", after_id: int = 0):
        if mode not in {"VISO_LIVE", "BENCHMARK_REPLAY", "LOCAL_INFERENCE"}:
            raise HTTPException(400, "Unknown source mode")
        try:
            cursor = max(0, int(request.headers.get("last-event-id", after_id)))
        except ValueError:
            cursor = 0
        return StreamingResponse(stream_events(request, hub, snapshot, query_since, runtime, mode, cursor),
            media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/console")
    def console(mode: str = "VISO_LIVE"):
        if mode not in {"VISO_LIVE", "BENCHMARK_REPLAY", "LOCAL_INFERENCE"}:
            raise HTTPException(400, "Unknown source mode")
        return runtime.snapshot(mode)

    @app.get("/api/sources")
    def sources():
        return {"modes": ["VISO_LIVE", "LOCAL_INFERENCE", "BENCHMARK_REPLAY"],
                "local_inference": availability(), "replay_available": runtime.replay is not None,
                "replay_error": runtime.replay_error}

    @app.post("/api/demo/reset")
    def reset(payload: Optional[ModeRequest] = None):
        # No mode means the presentation. Explicit legacy modes retain their API.
        if (payload is None or "mode" not in payload.model_fields_set) and hasattr(app.state, "demo"):
            from fastapi.responses import JSONResponse
            return JSONResponse(app.state.demo.reset(), headers={"Cache-Control": "no-store"})
        payload = payload or ModeRequest()
        runtime.reset(payload.mode)
        return {"status": "reset", "permanent_events_deleted": 0, "console": runtime.snapshot(payload.mode)}

    @app.post("/api/replay/control")
    def replay_control(payload: ReplayControl):
        if runtime.replay is None:
            raise HTTPException(503, runtime.replay_error)
        with runtime.lock:
            runtime.replay.control(payload.action, payload.loop)
            result = runtime.snapshot("BENCHMARK_REPLAY")
            hub.publish("console", result)
            return result

    @app.post("/api/local/start")
    def local_start():
        try:
            runtime.local_runner.start()
        except ModelUnavailable as error:
            raise HTTPException(503, str(error))
        return runtime.snapshot("LOCAL_INFERENCE")

    @app.post("/api/local/stop")
    def local_stop():
        runtime.local_runner.stop()
        return runtime.snapshot("LOCAL_INFERENCE")

    @app.get("/api/local/frame")
    async def local_frame(request: Request):
        if not runtime.local_runner.jpeg:
            raise HTTPException(503, "No inference frame available")
        async def frames():
            while not await request.is_disconnected() and runtime.local_runner.status == "ONLINE":
                data = runtime.local_runner.jpeg
                if data:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
                await asyncio.sleep(0.1)
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/replay/video")
    def replay_video(request: Request):
        path = runtime.replay.data["video_path"] if runtime.replay else None
        if path is None:
            raise HTTPException(404, "No video is associated with this annotation sequence")
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        requested = request.headers.get("range")
        if requested:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
            if not match:
                raise HTTPException(416, "Unsupported range", headers={"Content-Range": f"bytes */{size}"})
            start = int(match[1])
            end = min(int(match[2]), size - 1) if match[2] else size - 1
            if not 0 <= start <= end < size:
                raise HTTPException(416, "Invalid range", headers={"Content-Range": f"bytes */{size}"})
            code = 206
        def chunks():
            with path.open("rb") as video:
                video.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = video.read(min(left, 128 * 1024))
                    if not chunk:
                        break
                    left -= len(chunk)
                    yield chunk
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Cache-Control": "no-store"}
        if code == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(chunks(), status_code=code, media_type="video/mp4", headers=headers)
