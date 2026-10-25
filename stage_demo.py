"""Offline deterministic stage demonstration. No media, network or database writes.

The observation interface carries positions, timestamps and confidence, not truth
identity. Association uses a spatial gate against constant-velocity prediction.
During dropout, neither current truth nor a fabricated measurement is returned.
"""
import math
import threading
import time
import uuid

from fastapi import HTTPException
from fastapi.responses import JSONResponse

START = (1600.0, 1800.0, 140.0)
VELOCITY = (-31.4, -37.9, 0.4)
WARNING_RADIUS = math.hypot(START[0] + VELOCITY[0] * 17, START[1] + VELOCITY[1] * 17)
RESTRICTED_RADIUS = 500.0
LAST_MEASUREMENT = 28.9


def bearing(x, y):
    return math.degrees(math.atan2(x, y)) % 360 if x or y else None


def telemetry(position, velocity):
    x, y, z = position
    vx, vy, vz = velocity
    return {"x": x, "y": y, "z": z, "range_m": math.hypot(x, y),
            "bearing_deg": bearing(x, y), "altitude_m": z,
            "speed_mps": math.sqrt(vx * vx + vy * vy + vz * vz),
            "heading_deg": bearing(vx, vy), "vx": vx, "vy": vy, "vz": vz}


def ground_truth(elapsed):
    moving_time = max(0.0, min(52.0, elapsed) - 3.0)
    return tuple(p + v * moving_time for p, v in zip(START, VELOCITY))


def observation(elapsed):
    if elapsed < 3 or 29 <= elapsed < 37:
        return None
    return {"position": ground_truth(elapsed), "timestamp_s": elapsed,
            "confidence": min(0.97, 0.92 + (elapsed - 3) * 0.006),
            "class": "UAS", "source": "SIMULATED EO SENSOR"}


def predict(position, velocity, elapsed):
    return tuple(p + v * elapsed for p, v in zip(position, velocity))


def gate_observation(measured_position, predicted_position, threshold_m=150.0):
    residual = math.sqrt(sum((a - b) ** 2 for a, b in zip(measured_position, predicted_position)))
    return {"accepted": residual <= threshold_m, "residual_m": residual, "threshold_m": threshold_m}


def crossing_time(radius):
    x, y, _ = START
    vx, vy, _ = VELOCITY
    a, b, c = vx * vx + vy * vy, 2 * (x * vx + y * vy), x * x + y * y - radius * radius
    return 3 + (-b - math.sqrt(b * b - 4 * a * c)) / (2 * a)


WARNING_AT = 20.0
RESTRICTED_AT = crossing_time(RESTRICTED_RADIUS)
TRANSITIONS = [
    (3.0, "SENSOR", "SIMULATED EO CONTACT DETECTED"),
    (4.0, "TRACK", "DW-001 ACQUIRED"),
    (WARNING_AT, "WARNING", "DW-001 APPROACHING PROTECTED SITE"),
    (29.0, "SENSOR", "EO SENSOR FEED INTERRUPTED"),
    (29.1, "TRACK", "DW-001 COASTING"),
    (37.0, "SENSOR", "EO CONTACT RESTORED"),
    (37.1, "TRACK", "DW-001 REACQUIRED; POSITION GATE PASSED"),
    (RESTRICTED_AT, "HIGH", "DW-001 ENTERED RESTRICTED AIRSPACE"),
    (52.0, "SYSTEM", "SCENARIO COMPLETE; FINAL STATE HELD"),
]


class StageDemo:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.run_id = uuid.uuid4().hex[:12]
            self.base_elapsed = 0.0
            self.started = self.clock()
            self.running = False
            self.has_started = False
            self.emitted = set()
            self.events = [{"id": self.run_id + "-0", "time_s": 0, "category": "SYSTEM",
                            "message": "DEMO RESET; AIRSPACE CLEAR", "is_simulated": True}]
            return self.state()

    def elapsed(self):
        return min(60.0, self.base_elapsed + (max(0.0, self.clock() - self.started) if self.running else 0.0))

    def start(self):
        with self.lock:
            self.reset()
            self.running = self.has_started = True
            return self.state()

    def pause(self):
        with self.lock:
            if not self.has_started:
                return self.start()
            if self.elapsed() >= 60:
                return self.state()
            self.base_elapsed = self.elapsed()
            self.started = self.clock()
            self.running = not self.running
            return self.state()

    def manual(self, action):
        targets = {"acquire": 5.0, "dropout": 29.2, "reacquire": 37.2, "restricted": 44.0}
        if action not in targets:
            raise ValueError("Unknown manual stage control")
        with self.lock:
            # Manual recovery is an explicit timeline jump, not an injected measurement.
            # Rewind creates a fresh run so transitions remain exactly once per run.
            if targets[action] < self.elapsed():
                self.reset()
            self.base_elapsed = targets[action]
            self.started = self.clock()
            self.running = self.has_started = True
            return self.state()

    def state(self):
        with self.lock:
            elapsed = self.elapsed()
            if elapsed >= 60:
                self.base_elapsed, self.running = 60.0, False
            for index, (at, category, message) in enumerate(TRANSITIONS):
                if elapsed >= at and index not in self.emitted:
                    self.emitted.add(index)
                    self.events.append({"id": self.run_id + "-" + str(index + 1), "time_s": round(at, 1),
                                        "category": category, "message": message, "is_simulated": True})
            current = observation(elapsed)
            track, association = None, None
            sensor_state, banner, threat = "CLEAR", "AIRSPACE CLEAR", "CLEAR"
            if elapsed >= 3:
                coasting = 29 <= elapsed < 37
                last_time = LAST_MEASUREMENT if coasting else elapsed
                last = observation(last_time)
                # Velocity is estimated only from two real (simulated) observations before loss.
                before = observation(LAST_MEASUREMENT - 0.1)
                last_before_loss = observation(LAST_MEASUREMENT)
                estimated_velocity = tuple((a - b) / 0.1 for a, b in zip(last_before_loss["position"], before["position"]))
                position = predict(last["position"], estimated_velocity, elapsed - last_time) if coasting else current["position"]
                velocity = estimated_velocity if elapsed < 52 else (0.0, 0.0, 0.0)
                if elapsed >= 37:
                    returning = observation(37.0)
                    predicted_return = predict(last_before_loss["position"], estimated_velocity, 37.0 - LAST_MEASUREMENT)
                    association = gate_observation(returning["position"], predicted_return)
                track_state = "COASTING" if coasting else "REACQUIRED" if 37 <= elapsed < 42 else "TRACKED" if elapsed >= 4 else "DETECTED"
                track_id = "DW-001" if association is None or association["accepted"] else "DW-002"
                track = {"track_id": track_id, "class": "UAS", "state": track_state,
                         **telemetry(position, velocity), "confidence": current["confidence"] if current else None,
                         "last_observation_age_s": round(elapsed - last_time, 2),
                         "position_source": "TRACK PREDICTION" if coasting else "SYNTHETIC GROUND TRUTH",
                         "uncertainty_m": 20 + 22 * (elapsed - LAST_MEASUREMENT) if coasting else 20.0,
                         "uncertainty_basis": "Illustrative radius: 20 m baseline + 22 m/s during loss; not a confidence interval"}
                trail = []
                for tick in range(max(30, int(elapsed * 10) - 180), int(elapsed * 10) + 1, 5):
                    when = tick / 10
                    is_prediction = 29 <= when < 37
                    point = predict(last_before_loss["position"], estimated_velocity, when - LAST_MEASUREMENT) if is_prediction else ground_truth(when)
                    trail.append({"x": point[0], "y": point[1], "predicted": is_prediction})
                track["history"] = trail
                threat = "HIGH" if track["range_m"] <= RESTRICTED_RADIUS else "WARNING" if track["range_m"] <= WARNING_RADIUS else "CONTACT"
                sensor_state = "SIGNAL LOST" if coasting else "REACQUIRED" if track_state == "REACQUIRED" else "TRACKED"
                if threat == "HIGH":
                    banner = "RESTRICTED AIRSPACE PENETRATION"
                elif coasting:
                    banner = "SENSOR FEED INTERRUPTED / TRACK COASTING"
                elif track_state == "REACQUIRED":
                    banner = "TRACK REACQUIRED / DW-001"
                elif threat == "WARNING":
                    banner = "DRONE APPROACHING PROTECTED SITE"
                elif elapsed < 7:
                    banner = "VISUAL CONTACT DETECTED"
                else:
                    banner = "TRACK ACQUIRED / DW-001"
            return {"scenario": "PROTECTED SITE APPROACH", "run_id": self.run_id,
                    "elapsed_s": round(elapsed, 3), "duration_s": 60, "running": self.running,
                    "has_started": self.has_started, "complete": elapsed >= 52,
                    "mode": "SYNTHETIC AIRSPACE", "is_simulated": True,
                    "detection_source": "SIMULATED EO SENSOR", "banner": banner,
                    "threat": threat, "sensor_state": sensor_state, "track": track,
                    "measurement": current, "association": association, "events": list(self.events),
                    "zones": {"warning_m": WARNING_RADIUS, "restricted_m": RESTRICTED_RADIUS, "maximum_m": 2500}}


def install_stage(app, demo=None):
    demo = demo or StageDemo()
    app.state.stage = demo

    @app.get("/api/stage/state")
    async def state():
        return JSONResponse(demo.state(), headers={"Cache-Control": "no-store"})

    @app.post("/api/stage/start")
    async def start():
        return demo.start()

    @app.post("/api/stage/reset")
    async def reset():
        return demo.reset()

    @app.post("/api/stage/pause")
    async def pause():
        return demo.pause()

    @app.post("/api/stage/manual/{action}")
    async def manual(action: str):
        try:
            return demo.manual(action)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
