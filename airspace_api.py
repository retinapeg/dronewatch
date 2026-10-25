"""Additive airspace routes using the existing SQLite incident writer for milestones."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

if __package__:
    from .airspace import visual_sighting
    from .domain import provenance
    from .simulation import SyntheticAirspace
else:
    from airspace import visual_sighting
    from domain import provenance
    from simulation import SyntheticAirspace


class ScenarioStart(BaseModel):
    scenario: Literal["north_east_approach", "west_fast_mover", "south_loiter", "multi_vector"]


def milestone_incident(event):
    track = event.get("track") or {}
    return {"event_id": event["event_id"], "received_at": datetime.now(timezone.utc).isoformat(),
        "detection_type": track.get("object_class"), "drone_detected": bool(track),
        "confidence": track.get("confidence"), "state": event["state"], "severity": event["severity"],
        "source": "SYNTHETIC", "media_url": None, "raw_payload": event, "is_simulated": True}


def install_airspace(app, write_incident, snapshot_events, root, engine=None):
    engine = engine or SyntheticAirspace()
    enabled = os.environ.get("DRONEWATCH_ENABLE_SCENARIOS", "1").lower() in {"1", "true", "yes"}
    app.state.airspace = engine
    pending = deque()
    persist_lock = None
    state = {"event_log_error": None, "next_retry": 0.0}

    async def flush():
        async with persist_lock:
            pending.extend(engine.drain_events())
            if time.monotonic() < state["next_retry"]:
                return
            while pending:
                try:
                    await asyncio.to_thread(write_incident, milestone_incident(pending[0]))
                except Exception:
                    if state["event_log_error"] is None:
                        logging.exception("Synthetic milestone persistence failed; retaining pending events")
                    state["event_log_error"] = "Milestone log temporarily unavailable; retrying."
                    state["next_retry"] = time.monotonic()+2
                    return
                pending.popleft()
            state["event_log_error"] = None

    def snapshot(source="SYNTHETIC"):
        result = engine.snapshot()
        if source == "VISO":
            observations = [event for event in snapshot_events()["events"] if provenance(event) == "VISO"]
            latest = observations[0] if observations else None
            age = None
            if latest:
                try:
                    age = time.time()-datetime.fromisoformat(latest["received_at"].replace("Z", "+00:00")).timestamp()
                except (TypeError, ValueError):
                    pass
            result.update({"tracks": [visual_sighting(event) for event in observations[:20]],
                "primary_track_id": None, "source": "VISO", "provenance": "SENSOR REPORTED / NO WORLD POSITION",
                "source_online": age is not None and 0 <= age < 120,
                "last_sensor_update": latest["received_at"] if latest else None,
                "metrics": {"active_tracks": 0, "sighting_observations": len(observations),
                            "nearest_range_m": None, "max_severity": "UNKNOWN"}})
        result.update({"controls_enabled": enabled, "event_log_error": state["event_log_error"],
                       "pending_milestones": len(pending)})
        return result

    @app.on_event("startup")
    async def start_airspace():
        nonlocal persist_lock
        persist_lock = asyncio.Lock()
        async def tick():
            while True:
                engine.advance()
                await flush()
                await asyncio.sleep(1/engine.config.update_hz)
        app.state.airspace_task = asyncio.create_task(tick())

    @app.on_event("shutdown")
    async def stop_airspace():
        app.state.airspace_task.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.airspace_task
        await flush()

    @app.get("/vision")
    def vision():
        return FileResponse(root / "vision.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/tracks")
    def tracks(response: Response, source: Literal["SYNTHETIC", "VISO"] = "SYNTHETIC"):
        response.headers["Cache-Control"] = "no-store"
        return snapshot(source)

    @app.get("/dev/scenarios")
    def scenarios():
        return {"enabled": enabled, "scenarios": engine.catalog(), "config": engine.snapshot()["config"]}

    def require_enabled():
        if not enabled:
            raise HTTPException(403, "Synthetic scenario controls are disabled by configuration.")

    @app.post("/dev/scenario/start")
    async def scenario_start(payload: ScenarioStart):
        require_enabled()
        engine.start(payload.scenario)
        await flush()
        return snapshot()

    @app.post("/dev/scenario/stop")
    async def scenario_stop():
        require_enabled()
        engine.stop()
        await flush()
        return snapshot()

    @app.post("/dev/scenario/reset")
    async def scenario_reset():
        require_enabled()
        engine.reset()
        await flush()
        return {**snapshot(), "permanent_events_deleted": 0}
