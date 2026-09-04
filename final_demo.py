"""Offline presentation scenarios. Synthetic observations, never live measurements.

The monotonic clock is the only driver. Polling does not advance the simulation,
and a skipped poll cannot lose or duplicate an event. All coordinates are metres
in local ENU: +X east, +Y north, +Z up. One process / one shared presentation.
"""
from __future__ import annotations

import math
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi.responses import JSONResponse
from pydantic import BaseModel

MAXIMUM = 2500.0
WARNING = 1000.0
RESTRICTED = 500.0
DRONE_RANGE = math.hypot(1600, 1800)
DRONE_SPEED = (DRONE_RANGE - RESTRICTED) / 26.0
WARNING_AT = 6.0 + (DRONE_RANGE - WARNING) / DRONE_SPEED
RESTRICTED_AT = 32.0
SCENARIOS = {
    "drone": {"class": "UAS", "label": "UAS", "confidence": .96, "id": "DW-001", "duration": 35.0},
    "aircraft": {"class": "AIRCRAFT", "label": "AIRCRAFT", "confidence": .94, "id": "AC-001", "duration": 24.0},
    "bird": {"class": "BIRD", "label": "BIRD", "confidence": .88, "id": "BD-001", "duration": 18.0},
}


def bearing(x, y):
    return math.degrees(math.atan2(x, y)) % 360 if x or y else None


def trajectory(scenario, elapsed):
    """Position and its derivative share the same seconds and coordinate system."""
    duration = SCENARIOS[scenario]["duration"]
    moving = max(0.0, min(duration, elapsed) - 6.0)
    if scenario == "drone":
        vx, vy, vz = -1600 / DRONE_RANGE * DRONE_SPEED, -1800 / DRONE_RANGE * DRONE_SPEED, -.5
        position = (1600 + vx * moving, 1800 + vy * moving, 130 + vz * moving)
    elif scenario == "aircraft":
        vx, vy, vz = 160.0, 0.0, 0.0
        position = (-1700 + vx * moving, 1400.0, 650.0)
    else:
        vx, vy, vz = 20.0, -8.0, 0.0
        position = (-650 + vx * moving, 1650 + vy * moving, 65.0)
    velocity = (vx, vy, vz) if 6 <= elapsed < duration else (0.0, 0.0, 0.0)
    return position, velocity


def snapshot(scenario, elapsed):
    spec = SCENARIOS[scenario]
    elapsed = max(0.0, min(spec["duration"], elapsed))
    position, velocity = trajectory(scenario, elapsed)
    x, y, z = position
    distance = math.hypot(x, y)
    system_state, severity, banner = "CLEAR", "NORMAL", "AIRSPACE CLEAR"
    detection, track = None, None
    milestones = [(0, "SYSTEM", "AIRSPACE MONITORING")]
    if elapsed >= 3:
        detection = {"class": spec["class"], "label": spec["label"], "confidence": spec["confidence"],
                     "sensor": "EO-01", "source": "SIMULATED EO SENSOR",
                     "sensor_x": .5 + x / MAXIMUM * .25,
                     "sensor_y": .48 - y / MAXIMUM * .12,
                     "sensor_scale": 1.0 + (1.0 - distance / MAXIMUM) * .65}
        system_state = "NON_UAS" if scenario == "bird" else "DETECTED"
        banner = {"drone": "VISUAL CONTACT DETECTED",
                  "aircraft": "AIRCRAFT DETECTED",
                  "bird": "BIRD DETECTED — NON-UAS CONTACT"}[scenario]
    milestones.append((3, "SENSOR", spec["class"] + " DETECTED"))
    if elapsed >= 6:
        system_state = "ACQUIRED" if elapsed < 8 else "APPROACHING" if scenario == "drone" else "NORMAL" if scenario == "aircraft" else "NON_UAS"
        banner = "TRACK ACQUIRED — " + spec["id"]
        if elapsed >= 8:
            banner = {"drone": "DRONE APPROACHING PROTECTED AIRSPACE",
                      "aircraft": "AIRCRAFT TRACKED — NORMAL",
                      "bird": "BIRD IDENTIFIED — NON-UAS CONTACT"}[scenario]
        if scenario == "drone" and distance <= WARNING + 1e-8:
            system_state, severity, banner = "WARNING", "WARNING", "WARNING — PROTECTED ZONE APPROACH"
        if scenario == "drone" and distance <= RESTRICTED + 1e-8:
            system_state, severity, banner = "RESTRICTED", "HIGH", "RESTRICTED AIRSPACE PENETRATION"
        # Non-UAS is explicit throughout the bird contact, including acquisition.
        if scenario == "bird":
            system_state, banner = "NON_UAS", "BIRD IDENTIFIED — NON-UAS CONTACT"
        history = []
        for tick in range(max(12, int(elapsed * 2) - 20), int(elapsed * 2) + 1):
            point, _ = trajectory(scenario, tick / 2)
            history.append({"x": point[0], "y": point[1]})
        history.append({"x": x, "y": y})
        track = {"id": spec["id"], "track_id": spec["id"], "class": spec["class"],
                 "state": system_state, "x": x, "y": y, "z": z,
                 "vx": velocity[0], "vy": velocity[1], "vz": velocity[2],
                 "range_m": distance, "bearing_deg": bearing(x, y), "altitude_m": z,
                 "speed_mps": math.sqrt(sum(v * v for v in velocity)),
                 "heading_deg": bearing(velocity[0], velocity[1]),
                 "confidence": spec["confidence"], "source": "EO-01", "history": history}
    milestones.append((6, "TRACK", spec["id"] + " ACQUIRED"))
    if scenario == "drone":
        milestones.extend([(WARNING_AT, "WARNING", "DW-001 APPROACHING — WARNING ZONE ENTRY"),
                           (RESTRICTED_AT, "HIGH", "RESTRICTED ZONE ENTRY — DW-001")])
    elif scenario == "aircraft":
        milestones.append((8, "SYSTEM", "AC-001 NORMAL TRANSIT — OUTSIDE PROTECTED ZONES"))
    else:
        milestones.append((6, "CLASS", "BIRD IDENTIFIED — NON-UAS CONTACT"))
    return {"scenario": scenario, "elapsed_s": round(elapsed, 3), "duration_s": spec["duration"],
            "system_state": system_state, "severity": severity, "banner": banner,
            "sensor_state": "MONITORING" if detection is None else "DETECTED" if track is None else "TRACKING",
            "detection": detection, "track": track, "complete": elapsed >= spec["duration"],
            "is_simulated": True, "mode": "SYNTHETIC DEMO",
            "zones": {"warning_m": WARNING, "restricted_m": RESTRICTED, "maximum_m": MAXIMUM},
            "events": [{"time_s": at, "category": category, "message": message}
                       for at, category, message in milestones if elapsed >= at]}


class FinalDemo:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.scenario, self.base_elapsed = "drone", 0.0
            self.started, self.wall_started = self.clock(), datetime.now(timezone.utc)
            self.running, self.has_started = False, False
            self.run_id = uuid.uuid4().hex[:12]
            return self.state()

    def elapsed(self):
        delta = max(0.0, self.clock() - self.started) if self.running else 0.0
        return min(SCENARIOS[self.scenario]["duration"], self.base_elapsed + delta)

    def start(self, scenario="drone"):
        if scenario not in SCENARIOS:
            raise ValueError("Unknown scenario")
        with self.lock:
            self.reset()
            self.scenario, self.running, self.has_started = scenario, True, True
            return self.state()

    def pause(self):
        with self.lock:
            if not self.has_started or self.elapsed() >= SCENARIOS[self.scenario]["duration"]:
                return self.state()
            self.base_elapsed = self.elapsed()
            self.started = self.clock()
            self.running = not self.running
            return self.state()

    def state(self):
        with self.lock:
            elapsed = self.elapsed()
            result = snapshot(self.scenario, elapsed)
            if result["complete"]:
                self.base_elapsed, self.running = elapsed, False
            result.update(run_id=self.run_id, running=self.running, has_started=self.has_started)
            for index, event in enumerate(result["events"]):
                event["id"] = self.run_id + "-" + str(index)
                event["timestamp"] = (self.wall_started + timedelta(seconds=event["time_s"])).isoformat()
            result["sensor_timestamp"] = (self.wall_started + timedelta(seconds=elapsed)).isoformat()
            return result


class StartRequest(BaseModel):
    scenario: Literal["drone", "aircraft", "bird"] = "drone"


def response(state):
    return JSONResponse(state, headers={"Cache-Control": "no-store"})


def install_final_demo(app, demo=None):
    demo = demo or FinalDemo()
    app.state.demo = demo

    @app.get("/api/demo/state")
    def state():
        return response(demo.state())

    @app.post("/api/demo/start")
    def start(payload: StartRequest):
        return response(demo.start(payload.scenario))

    @app.post("/api/demo/pause")
    def pause():
        return response(demo.pause())

    # /api/demo/reset is shared with the preserved console API in realtime.py.
