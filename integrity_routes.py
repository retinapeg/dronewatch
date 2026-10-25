"""Additive routes. Existing Viso ingestion, schema and event APIs remain unchanged."""
import asyncio
import contextlib
import logging
import os

import httpx
from fastapi import Body, HTTPException
from fastapi.responses import FileResponse, JSONResponse

if __package__:
    from .adsb_provider import ADSBLolProvider
    from .capture_replay import CaptureStore
    from .integrity_runtime import IntegrityRuntime
else:
    from adsb_provider import ADSBLolProvider
    from capture_replay import CaptureStore
    from integrity_runtime import IntegrityRuntime

LOG = logging.getLogger("dronewatch.integrity")


def install_integrity(app, write_incident, root, runtime=None):
    runtime = runtime or IntegrityRuntime()
    captures = CaptureStore(root / "captures")
    tasks = []
    persist_lock = None
    app.state.integrity = runtime

    async def flush():
        if persist_lock is None:
            return
        async with persist_lock:
            while runtime.pending:
                item = runtime.pending[0]
                try:
                    await asyncio.to_thread(write_incident, item)
                except Exception:
                    LOG.exception("Integrity milestone persistence failed; will retry")
                    break
                runtime.pending.popleft()

    async def provider_loop():
        async with httpx.AsyncClient(timeout=7.0, follow_redirects=False) as client:
            provider = ADSBLolProvider()
            while True:
                if runtime.mode == "LIVE":
                    try:
                        snapshot = await provider.fetch(client)
                        runtime.ingest(snapshot)
                        try:
                            await asyncio.to_thread(captures.append, snapshot)
                        except Exception as exc:
                            captures.error = str(exc)[:160]
                            LOG.warning("Capture unavailable: %s", exc)
                        runtime.capture = {"frames": captures.frames_written, "name": captures.active.name if captures.active else None, "error": captures.error}
                    except Exception as exc:
                        runtime.failed(str(exc) or type(exc).__name__)
                    await flush()
                await asyncio.sleep(10)

    async def tick():
        while True:
            runtime.snapshot()
            await flush()
            await asyncio.sleep(0.1)

    @app.on_event("startup")
    async def start():
        nonlocal persist_lock
        persist_lock = asyncio.Lock()
        if os.environ.get("DRONEWATCH_LIVE_ENABLED", "1") != "0":
            tasks.append(asyncio.create_task(provider_loop()))
        tasks.append(asyncio.create_task(tick()))
        print("DRONEWATCH INTEGRITY READY | /ops | provider ADSB.LOL | local capture/replay enabled", flush=True)

    @app.on_event("shutdown")
    async def stop():
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        tasks.clear()
        await flush()

    @app.get("/ops", include_in_schema=False)
    async def ops():
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/synthetic", include_in_schema=False)
    async def synthetic():
        return FileResponse(root / "synthetic.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/airspace")
    @app.get("/api/airspace/status")
    async def airspace():
        return JSONResponse(runtime.snapshot(), headers={"Cache-Control": "no-store"})

    @app.get("/api/airspace/captures")
    async def recordings():
        return {"captures": await asyncio.to_thread(captures.listing)}

    @app.post("/api/airspace/select")
    async def select(payload: dict = Body(...)):
        try:
            runtime.select(payload.get("track_id"))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        await flush()
        return runtime.snapshot()

    @app.post("/api/integrity/start")
    async def manipulate(payload: dict = Body(default={})):
        try:
            runtime.start(payload.get("track_id"))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        await flush()
        return runtime.snapshot()

    @app.post("/api/integrity/stop")
    async def restore():
        runtime.restore()
        await flush()
        return runtime.snapshot()

    @app.post("/api/airspace/replay/start")
    async def replay(payload: dict = Body(default={})):
        try:
            if payload.get("synthetic") is True:
                runtime.fallback()
            else:
                name, frames = await asyncio.to_thread(captures.load, payload.get("name"))
                runtime.start_replay(name, frames)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))
        await flush()
        return runtime.snapshot()

    @app.post("/api/airspace/replay/stop")
    @app.post("/api/airspace/reset")
    async def reset():
        runtime.reset()
        await flush()
        return runtime.snapshot()
