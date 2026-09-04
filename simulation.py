"""Deterministic synthetic worlds sampled on a fixed monotonic-time grid."""
from __future__ import annotations

import math
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict

if __package__:
    from .airspace import AirspaceConfig, AirspaceTrack, Position, Velocity, iso_time, primary_track, zone_state
else:
    from airspace import AirspaceConfig, AirspaceTrack, Position, Velocity, iso_time, primary_track, zone_state


def hermite(start, end, initial_velocity, final_velocity, duration, elapsed):
    """Cubic path with its analytic derivative, not an independently assigned heading."""
    u = min(1.0, max(0.0, elapsed / duration))
    h = (2*u**3-3*u*u+1, u**3-2*u*u+u, -2*u**3+3*u*u, u**3-u*u)
    dh = ((6*u*u-6*u)/duration, 3*u*u-4*u+1, (-6*u*u+6*u)/duration, 3*u*u-2*u)
    position = tuple(h[0]*a+h[1]*duration*va+h[2]*b+h[3]*duration*vb
                     for a,b,va,vb in zip(start,end,initial_velocity,final_velocity))
    velocity = tuple(dh[0]*a+dh[1]*va+dh[2]*b+dh[3]*vb
                     for a,b,va,vb in zip(start,end,initial_velocity,final_velocity))
    return Position(*position), Velocity(*velocity)


def sample_path(path, elapsed):
    if path == "north_east_approach":
        return Position(1600-(160/3)*elapsed, 1800-60*elapsed, 150+0.25*elapsed), Velocity(-160/3, -60, 0.25), "TRANSIT"
    if path == "west_fast_mover":
        return Position(-2350+150*elapsed, 350, 210-0.4*elapsed), Velocity(150, 0, -0.4), "TRANSIT"
    if path != "south_loiter":
        raise ValueError("unknown path")
    angular_speed = 2*math.pi/20
    tangent_speed = 100*angular_speed
    if elapsed < 16:
        position, velocity = hermite((0,-2350,150), (0,-900,150), (0,90,0),
                                     (tangent_speed,0,0), 16, elapsed)
        return position, velocity, "TRANSIT"
    if elapsed < 36:
        angle = -math.pi/2 + angular_speed*(elapsed-16)
        return (Position(100*math.cos(angle), -800+100*math.sin(angle), 150),
                Velocity(-tangent_speed*math.sin(angle), tangent_speed*math.cos(angle), 0), "LOITERING")
    position, velocity = hermite((0,-900,150), (0,2700,150), (tangent_speed,0,0),
                                 (0,115,0), 38, elapsed-36)
    return position, velocity, "TRANSIT"


SCENARIOS = {
    "north_east_approach": {"label": "NE APPROACH", "duration_s": 65,
        "description": "One north-east contact crosses both zones and exits south-west.",
        "contacts": [("DW-001", "north_east_approach", 0)]},
    "west_fast_mover": {"label": "WEST FAST MOVER", "duration_s": 35,
        "description": "A faster west-to-east crossing, offset 350 m north of the origin.",
        "contacts": [("DW-001", "west_fast_mover", 0)]},
    "south_loiter": {"label": "SOUTH LOITER", "duration_s": 75,
        "description": "A southern approach, 20-second curved loiter at 700-900 m, then renewed approach.",
        "contacts": [("DW-001", "south_loiter", 0)]},
    "multi_vector": {"label": "MULTI-VECTOR", "duration_s": 81,
        "description": "NE, west and south contacts acquired at 0, 3 and 6 seconds; priority follows severity then range.",
        "contacts": [("DW-001", "north_east_approach", 0), ("DW-002", "west_fast_mover", 3),
                     ("DW-003", "south_loiter", 6)]},
}


class SyntheticAirspace:
    def __init__(self, config=None, clock=time.monotonic, wall_clock=time.time):
        self.config = config or AirspaceConfig.from_env()
        self.clock, self.wall_clock = clock, wall_clock
        self.lock = threading.RLock()
        self.pending = deque()
        self.revision = 0
        self.run_id = "idle"
        self.scenario = None
        self.active = False
        self.status = "READY"
        self.elapsed = 0.0
        self.started = 0.0
        self.epoch = 0.0
        self.step_index = -1
        self.tracks = {}
        self.completed = set()
        self.sequence = 0
        self.acquired_count = 0

    def catalog(self):
        return [{"id": key, "label": value["label"], "duration_s": value["duration_s"],
                 "description": value["description"], "contact_count": len(value["contacts"])}
                for key, value in SCENARIOS.items()]

    def _emit(self, kind, explanation, track=None):
        self.sequence += 1
        self.pending.append({"event_id": "SYN-%s-%04d" % (self.run_id, self.sequence),
            "event_type": kind, "track_id": track.track_id if track else None,
            "run_id": self.run_id, "scenario": self.scenario, "elapsed_s": self.elapsed,
            "occurred_at": iso_time(self.epoch+self.elapsed), "source": "SYNTHETIC",
            "synthetic": True, "is_simulated": True, "position_source": "SYNTHETIC GROUND TRUTH",
            "state": track.state if track else "UNKNOWN", "severity": track.severity if track else "INFO",
            "explanation": explanation, "track": track.snapshot() if track else None})

    def start(self, scenario):
        if scenario not in SCENARIOS:
            raise ValueError("unknown scenario; choose a listed scenario ID")
        with self.lock:
            self.run_id = uuid.uuid4().hex[:12]
            self.scenario, self.active, self.status = scenario, True, "RUNNING"
            self.started, self.epoch = self.clock(), self.wall_clock()
            self.elapsed, self.step_index, self.sequence, self.acquired_count = 0.0, -1, 0, 0
            self.tracks.clear()
            self.completed.clear()
            self.revision += 1
            self._emit("SCENARIO_STARTED", SCENARIOS[scenario]["label"] + " / synthetic airspace started.")
            self.advance()

    def stop(self):
        with self.lock:
            if self.active:
                self.advance()
                self.active, self.status = False, "STOPPED"
                self.revision += 1
                self._emit("SCENARIO_STOPPED", "Simulation stopped; displayed positions are frozen synthetic state.")

    def reset(self):
        with self.lock:
            if self.scenario is not None:
                self._emit("SCENARIO_RESET", "Synthetic tracks cleared; permanent source events retained.")
            self.run_id = uuid.uuid4().hex[:12]
            self.scenario, self.active, self.status = None, False, "READY"
            self.elapsed, self.step_index, self.acquired_count = 0.0, -1, 0
            self.tracks.clear()
            self.completed.clear()
            self.revision += 1

    def _step(self, elapsed):
        self.elapsed = elapsed
        for identity, path, delay in SCENARIOS[self.scenario]["contacts"]:
            if elapsed < delay or identity in self.completed:
                continue
            position, velocity, phase = sample_path(path, elapsed-delay)
            distance = math.hypot(position.x_m, position.y_m)
            track = self.tracks.get(identity)
            if distance > self.config.max_range_m:
                if track:
                    track.position, track.velocity = position, velocity
                    track.state, track.severity = "EXITED", "INFO"
                    track.last_seen = iso_time(self.epoch+elapsed)
                    self._emit("EXITED", "Exited the configured synthetic monitored range.", track)
                    del self.tracks[identity]
                    self.completed.add(identity)
                continue
            new = track is None
            if new:
                track = AirspaceTrack(identity, "SYNTHETIC", True, "SYNTHETIC GROUND TRUTH",
                    iso_time(self.epoch+elapsed), iso_time(self.epoch+elapsed), confidence=0.94)
                self.tracks[identity] = track
                self.acquired_count += 1
            old_zone, old_phase = track.zone, track.phase
            track.position, track.velocity, track.phase = position, velocity, phase
            track.zone, track.state, track.severity = zone_state(position, velocity, self.config, phase)
            track.last_seen = iso_time(self.epoch+elapsed)
            track.observation_count += 1
            # History at 5 Hz, telemetry at 10 Hz. Always actual synthetic samples.
            if new or self.step_index % 2 == 0:
                track.history.append({**asdict(position), "elapsed_s": elapsed})
                track.history = track.history[-self.config.history_length:]
            if new:
                self._emit("TRACK_ACQUIRED", "Synthetic contact acquired with a stable track identity.", track)
            if track.zone != old_zone:
                if track.zone == "RESTRICTED":
                    self._emit("RESTRICTED_ZONE_ENTERED", "Entered the configured restricted area.", track)
                elif old_zone == "RESTRICTED":
                    self._emit("RESTRICTED_ZONE_EXITED", "Left the restricted area; remains under observation.", track)
                elif track.zone == "WARNING":
                    self._emit("WARNING_ZONE_ENTERED", "Approaching the protected area; warning threshold crossed.", track)
                elif old_zone == "WARNING":
                    self._emit("WARNING_ZONE_EXITED", "Left the warning area; moving through outer monitored airspace.", track)
            if phase == "LOITERING" and old_phase != phase:
                self._emit("LOITERING", "Entered the scenario's 20-second loiter segment; not an inferred real-world intent.", track)
        self.revision += 1

    def advance(self):
        with self.lock:
            if not self.active:
                return
            duration = SCENARIOS[self.scenario]["duration_s"]
            target = min(duration, max(0.0, self.clock()-self.started))
            final_index = int(math.floor(target*self.config.update_hz+1e-8))
            while self.step_index < final_index:
                self.step_index += 1
                self._step(self.step_index/self.config.update_hz)
            if target >= duration:
                self.active, self.status = False, "COMPLETE"
                self._emit("SCENARIO_COMPLETED", "Deterministic synthetic scenario completed.")

    def snapshot(self):
        with self.lock:
            tracks = sorted(self.tracks.values(), key=lambda track: track.track_id)
            selected = primary_track(tracks)
            primary = self.tracks.get(selected)
            return {"tracks": [track.snapshot() for track in tracks], "primary_track_id": selected,
                "revision": self.revision, "run_id": self.run_id, "generated_at": time.time(),
                "config": asdict(self.config), "provenance": "SYNTHETIC GROUND TRUTH", "source": "SYNTHETIC",
                "simulation": {"active": self.active, "scenario": self.scenario, "status": self.status,
                    "label": SCENARIOS[self.scenario]["label"] if self.scenario else "NO SCENARIO",
                    "elapsed_s": self.elapsed, "duration_s": SCENARIOS[self.scenario]["duration_s"] if self.scenario else 0},
                "metrics": {"active_tracks": len(tracks), "acquired_tracks": self.acquired_count,
                    "nearest_range_m": min((math.hypot(t.position.x_m,t.position.y_m) for t in tracks), default=None),
                    "max_severity": primary.severity if primary else "NORMAL"}}

    def drain_events(self):
        with self.lock:
            events = list(self.pending)
            self.pending.clear()
            return events
