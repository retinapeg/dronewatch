"""Transient presentation/tracking state; SQLite remains the source event history."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

if __package__:
    from .domain import detections_from_event, epoch, find, provenance
    from .inference import LocalRunner, availability
    from .replay import ReplayEngine
    from .tracking import TrackManager, TrackerConfig
else:
    from domain import detections_from_event, epoch, find, provenance
    from inference import LocalRunner, availability
    from replay import ReplayEngine
    from tracking import TrackManager, TrackerConfig


MODES = {"VISO_LIVE", "BENCHMARK_REPLAY", "LOCAL_INFERENCE"}


class ConsoleRuntime:
    def __init__(self, root):
        self.lock = threading.RLock()
        self.config = TrackerConfig.from_env()
        self.zones = json.loads(os.getenv("DRONEWATCH_ZONES", "{}"))
        if not isinstance(self.zones, dict):
            raise ValueError("DRONEWATCH_ZONES must be a camera-to-polygon JSON object")
        self.live = TrackManager(self.config, self.zones)
        self.local = TrackManager(self.config, self.zones)
        self.events = {}
        self.sightings = []
        self.processed_ids = set()
        self.reset_after_id = 0
        self.publish = lambda *args: None
        self.replay_error = None
        try:
            self.replay = ReplayEngine(os.getenv("DRONEWATCH_REPLAY_PATH", str(root / "samples/synthetic_replay.json")), self.config)
        except (ValueError, OSError) as error:
            self.replay = None
            self.replay_error = "Replay manifest unavailable or invalid. Check DRONEWATCH_REPLAY_PATH and its documented schema."
        self.local_runner = LocalRunner(self.local_frame, lambda: self.local.snapshot()["tracks"], self.reset_local)

    def observe(self, event, emit=True):
        with self.lock:
            identity = event["id"]
            self.events[identity] = event
            if identity not in self.processed_ids and identity > self.reset_after_id:
                self.processed_ids.add(identity)
                detections = detections_from_event(event)
                self.sightings.extend(d.to_dict() for d in detections)
                self.sightings = self.sightings[-200:]
                # Simulations never contribute to genuine live tracks or counters.
                if provenance(event) == "VISO":
                    stamp = epoch(event.get("received_at"))
                    camera = detections[0].camera_id if detections else find(event.get("raw_payload"), ["camera_id", "connectionId"])
                    if stamp is not None:
                        supplied_frame = find(event.get("raw_payload"), ["frame_id", "frame_index"])
                        frame_id = str(supplied_frame) if isinstance(supplied_frame, (str, int)) else str(identity)
                        self.live.update("VISO", camera, frame_id, stamp, detections)
            if len(self.events) > 200:
                for old in sorted(self.events)[:-200]:
                    self.events.pop(old)
            if emit:
                self.publish("observation", event)

    def local_frame(self, frame_id, timestamp, detections):
        with self.lock:
            self.local.update("LOCAL_INFERENCE", "local-01", frame_id, timestamp, detections)
            self.publish("console", self.snapshot("LOCAL_INFERENCE"))

    def reset_local(self):
        with self.lock:
            self.local.reset()

    def reset(self, mode):
        with self.lock:
            self.live.reset()
            self.local.reset()
            self.sightings = []
            self.reset_after_id = max(self.events, default=0)
            if self.replay:
                self.replay.restart(mode == "BENCHMARK_REPLAY")
            self.publish("reset", {"mode": mode})

    def tick(self):
        with self.lock:
            before = [(t.track_id, t.state) for t in self.live.tracks.values()]
            self.live.tick(time.time())
            after = [(t.track_id, t.state) for t in self.live.tracks.values()]
            if before != after:
                self.publish("console", self.snapshot("VISO_LIVE"))
            if self.replay and self.replay.playing:
                self.replay.update()
                self.publish("console", self.snapshot("BENCHMARK_REPLAY"))
            self.local.tick(time.time())

    def snapshot(self, mode):
        with self.lock:
            if mode == "BENCHMARK_REPLAY":
                if self.replay:
                    return {**self.replay.snapshot(), "generated_at": time.time()}
                return {"mode": mode, "tracks": [], "alerts": [], "lifecycle": [], "sightings": [],
                        "metrics": {}, "generated_at": time.time(), "source": {"online": False, "status": "UNAVAILABLE", "error": self.replay_error}}
            if mode == "LOCAL_INFERENCE":
                result = self.local.snapshot()
                result.update({"mode": mode, "spatial_available": True, "sightings": [],
                    "source": {"online": self.local_runner.status == "ONLINE", "status": self.local_runner.status,
                        "last_event": self.local_runner.last_event, "error": self.local_runner.error},
                    "availability": availability(), "processing_fps": self.local_runner.fps,
                    "zone": self.zones.get("local-01")})
                result["generated_at"] = time.time()
                return result
            result = self.live.snapshot()
            genuine = [e for e in self.events.values() if provenance(e) == "VISO"]
            latest = max(genuine, key=lambda e: e["id"]) if genuine else None
            timestamp = epoch(latest.get("received_at")) if latest else None
            latest_detections = detections_from_event(latest) if latest else []
            result.update({"mode": "VISO_LIVE", "spatial_available": any(d.bbox is not None for d in latest_detections),
                "sightings": list(reversed(self.sightings)), "source": {"online": timestamp is not None and -5 <= time.time() - timestamp <= 120,
                    "status": "ONLINE" if timestamp is not None and -5 <= time.time() - timestamp <= 120 else "STALE" if latest else "WAITING",
                    "last_event": timestamp}, "latest_viso_id": latest["id"] if latest else None,
                "zone": self.zones.get(str(latest_detections[0].camera_id)) if latest_detections else None})
            result["generated_at"] = time.time()
            return result
