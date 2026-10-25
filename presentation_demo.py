"""Three offline, backend-driven visual detection-to-track demonstrations."""
import math
import time

from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse

if __package__:
    from .stage_demo import StageDemo, telemetry
else:
    from stage_demo import StageDemo, telemetry

SCENARIOS = {
    "drone": {"class": "DRONE", "confidence": 0.96, "track_id": "DW-001", "start": (1600., 1800., 140.), "velocity": (-50., (math.sqrt(500**2-250**2)-1800)/27, .2)},
    "aircraft": {"class": "AIRCRAFT", "confidence": 0.94, "track_id": "AC-001", "start": (-1800., 1100., 900.), "velocity": (90., -5., .5)},
    "bird": {"class": "BIRD", "confidence": 0.88, "track_id": "VC-001", "start": (-700., 950., 80.), "velocity": (25., -8., .1)},
}
DRONE_WARNING = math.hypot(500, 1800 + SCENARIOS["drone"]["velocity"][1] * 22)


class PresentationDemo(StageDemo):
    def __init__(self, clock=time.monotonic):
        self.scenario = "drone"
        super().__init__(clock)

    def elapsed(self):
        return min(35.0, super().elapsed())

    def start(self, scenario="drone"):
        if scenario not in SCENARIOS:
            raise ValueError("Choose drone, aircraft or bird")
        with self.lock:
            self.scenario = scenario
            return super().start()

    def manual(self, action):
        targets = {"acquire": 6.2, "warning": 25.1, "restricted": 30.1}
        if action not in targets:
            raise ValueError("Unknown stage control")
        with self.lock:
            if targets[action] < self.elapsed():
                self.reset()
            self.base_elapsed, self.started = targets[action], self.clock()
            self.running = self.has_started = True
            return self.state()

    def state(self):
        with self.lock:
            elapsed, config = self.elapsed(), SCENARIOS[self.scenario]
            if elapsed >= 35:
                self.base_elapsed, self.running = 35.0, False
            category, identity = config["class"], config["track_id"]
            transitions = [(3., "SENSOR", category + " DETECTED / SIMULATED EO-01"),
                           (6., "TRACK", identity + " ACQUIRED"),
                           (8., "TRACK", identity + (" APPROACHING PROTECTED SITE" if self.scenario == "drone" else " / NON-UAS INFORMATIONAL CONTACT"))]
            if self.scenario == "drone":
                transitions += [(25., "WARNING", "DRONE ENTERED WARNING BOUNDARY"),
                                (30., "HIGH", "DRONE ENTERED RESTRICTED AIRSPACE")]
            transitions += [(35., "SYSTEM", "DEMONSTRATION COMPLETE / FINAL STATE HELD")]
            for index, (at, level, message) in enumerate(transitions):
                if elapsed >= at and index not in self.emitted:
                    self.emitted.add(index)
                    self.events.append({"id": self.run_id + "-" + str(index + 1), "time_s": at,
                                        "category": level, "message": message, "is_simulated": True})
            measurement, detection, track = None, None, None
            banner, threat, system_state = "AIRSPACE CLEAR", "CLEAR", "CLEAR"
            if elapsed >= 3:
                position = tuple(p + v * (elapsed - 3) for p, v in zip(config["start"], config["velocity"]))
                measurement = {"position": position, "timestamp_s": elapsed, "confidence": config["confidence"],
                               "class": category, "source": "SIMULATED EO SENSOR"}
                detection = {"class": category, "confidence": config["confidence"], "sensor": "EO-01", "is_simulated": True}
                banner, threat, system_state = "VISUAL CONTACT DETECTED", "CONTACT", "DETECTED"
                if elapsed >= 6:
                    values = telemetry(position, config["velocity"])
                    is_drone = self.scenario == "drone"
                    # Classification gates alerts; non-UAS contacts never inherit drone severity.
                    high = is_drone and values["range_m"] <= 500.000001
                    warning = is_drone and values["range_m"] <= DRONE_WARNING + .000001
                    threat = "HIGH" if high else "WARNING" if warning else "CONTACT" if is_drone else "INFO"
                    track_state = "RESTRICTED_ZONE" if high else "APPROACHING" if is_drone and elapsed >= 8 else "TRACKED"
                    system_state = track_state
                    track = {"track_id": identity, "class": category, "state": track_state, **values,
                             "confidence": config["confidence"], "last_observation_age_s": 0.,
                             "position_source": "SYNTHETIC GROUND TRUTH", "uncertainty_m": 0.,
                             "history": []}
                    for tick in range(max(60, int(elapsed * 10) - 160), int(elapsed * 10) + 1, 4):
                        dt = tick / 10 - 3
                        track["history"].append({"x": config["start"][0] + config["velocity"][0] * dt,
                                                 "y": config["start"][1] + config["velocity"][1] * dt, "predicted": False})
                    if high:
                        banner = "RESTRICTED AIRSPACE PENETRATION"
                    elif warning:
                        banner = "DRONE APPROACHING PROTECTED AIRSPACE"
                    elif is_drone:
                        banner = "TRACK ACQUIRED / DW-001" if elapsed < 8 else "TRACK DW-001 / APPROACHING"
                    else:
                        banner = category + " IDENTIFIED / NON-UAS CONTACT"
            return {"scenario": self.scenario, "system_state": system_state, "run_id": self.run_id,
                    "elapsed_s": round(elapsed, 3), "duration_s": 35, "running": self.running,
                    "has_started": self.has_started, "complete": elapsed >= 35,
                    "mode": "SYNTHETIC AIRSPACE", "is_simulated": True, "detection_source": "SIMULATED EO SENSOR",
                    "detection": detection, "measurement": measurement, "track": track, "association": None,
                    "banner": banner, "threat": threat, "sensor_state": "TRACKED" if measurement else "CLEAR",
                    "events": list(self.events),
                    "zones": {"warning_m": DRONE_WARNING, "restricted_m": 500., "maximum_m": 2500.}}


def install_presentation(app, demo=None):
    demo = demo or PresentationDemo()
    app.state.stage = demo

    @app.get("/api/stage/state")
    async def state():
        return JSONResponse(demo.state(), headers={"Cache-Control": "no-store"})

    @app.post("/api/stage/start")
    async def start(payload: dict = Body(default={})):
        try:
            scenario = payload.get("scenario", "drone")
            if not isinstance(scenario, str):
                raise ValueError("Choose drone, aircraft or bird")
            return demo.start(scenario)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

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
