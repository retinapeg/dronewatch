"""Public-airspace cache and isolated, explicitly simulated observation integrity demo.

Provider observations are authoritative only within this demonstration, not verified
ground truth. A future estimator can consume observations without changing this store.
"""
import copy
import math
import threading
import time
import uuid
from collections import deque

if __package__:
    from .adsb_provider import iso_time
    from .geometry import Origin, enu_geometry
    from .capture_replay import ReplaySession, synthetic_frames
else:
    from adsb_provider import iso_time
    from geometry import Origin, enu_geometry
    from capture_replay import ReplaySession, synthetic_frames


class IntegrityRuntime:
    def __init__(self, origin=None, clock=time.monotonic, wall=time.time):
        self.origin, self.clock, self.wall = origin or Origin(), clock, wall
        self.lock = threading.RLock()
        self.live = {}
        self.playback = {}
        self.replay = None
        self.last_replay_key = None
        self.mode = "LIVE"
        self.last_success = None
        self.provider_time = None
        self.feed_error = None
        self.connected = False
        self.selected = None
        self.attack = None
        self.pending = deque()
        self.sequence = 0
        self.capture = {"frames": 0, "name": None, "error": None}

    def _event(self, kind, message, severity="INFO", simulated=False, **extra):
        stamp = iso_time(self.wall())
        self.pending.append({"event_id": "integrity-" + uuid.uuid4().hex, "received_at": stamp,
                             "detection_type": kind, "drone_detected": False, "confidence": None,
                             "state": "UNKNOWN", "severity": severity,
                             "source": "SIMULATED_INTEGRITY" if simulated else "ADSB.LOL",
                             "media_url": None, "is_simulated": simulated,
                             "raw_payload": {"producer": "DRONEWATCH_INTEGRITY", "event_type": kind,
                                             "message": message, "mode": self.mode,
                                             "simulation": "SIMULATED" if simulated else None, **extra}})

    def _merge(self, destination, incoming, now):
        for item in incoming[:60]:
            track = copy.deepcopy(item)
            old = destination.get(track["track_id"])
            history = copy.deepcopy(old.get("history", [])) if old else []
            point = {key: track.get(key) for key in ("east_m", "north_m", "up_m", "observed_at", "received_at")}
            if not history or any(point.get(k) != history[-1].get(k) for k in ("east_m", "north_m", "up_m", "observed_at")):
                history.append(point)
            track["history"] = history[-30:]
            destination[track["track_id"]] = track
        for key, track in list(destination.items()):
            if now - track.get("received_epoch", now) > 180:
                del destination[key]
        nearest = sorted(destination.values(), key=lambda t: t["horizontal_range_m"])[:60]
        destination.clear()
        destination.update((t["track_id"], t) for t in nearest)

    def ingest(self, snapshot):
        with self.lock:
            self._merge(self.live, snapshot["tracks"], snapshot["received_epoch"])
            self.last_success = snapshot["received_epoch"]
            self.provider_time = snapshot.get("provider_time")
            self.feed_error = None
            self.sequence += 1
            if not self.connected:
                self._event("LIVE_FEED_CONNECTED", "Public ADSB.lol feed connected; cooperative aircraft telemetry.")
            self.connected = True

    def failed(self, error):
        with self.lock:
            if self.connected or self.feed_error is None:
                self._event("LIVE_FEED_LOST", "Provider unavailable; retaining the last valid observations.", "WARNING", error=str(error)[:200])
            self.feed_error = str(error)[:200]
            self.connected = False

    def _active(self):
        if self.replay:
            snap, now, details = self.replay.current()
            key = (details["loop"], details["frame"])
            if key != self.last_replay_key:
                if self.last_replay_key is None or key[0] != self.last_replay_key[0]:
                    self.playback = {}
                self._merge(self.playback, snap["tracks"], now)
                self.last_replay_key = key
                self.sequence += 1
            return self.playback, now, details
        return self.live, self.wall(), None

    def select(self, track_id):
        with self.lock:
            tracks, _, _ = self._active()
            if track_id not in tracks:
                raise ValueError("Select an available aircraft")
            if self.selected != track_id:
                if self.attack:
                    self.restore()
                self.selected = track_id
                self._event("TRACK_SELECTED", "Operator selected an aircraft observation.", simulated=self.mode == "SYNTHETIC_FALLBACK", track_id=track_id)

    def start(self, track_id=None):
        with self.lock:
            tracks, _, _ = self._active()
            chosen = track_id or self.selected or next(iter(tracks), None)
            if not chosen or chosen not in tracks:
                raise ValueError("No aircraft available; choose a capture or synthetic fallback")
            self.select(chosen)
            if self.attack:
                return
            self.attack = {"track_id": chosen, "started": self.clock(), "emitted": set()}
            self._event("TELEMETRY_MANIPULATION_STARTED", "SIMULATED: offset applied to a local copy only. Provider track is unchanged.", "WARNING", True, track_id=chosen)

    def restore(self):
        with self.lock:
            if self.attack:
                self._event("SOURCE_RESTORED", "Simulated input removed; source observations were never modified.", simulated=True, track_id=self.attack["track_id"])
            self.attack = None

    def start_replay(self, name, frames, synthetic=False):
        with self.lock:
            self.restore()
            self.mode = "SYNTHETIC_FALLBACK" if synthetic else "REPLAY"
            self.replay = ReplaySession(name, frames, self.clock, synthetic)
            self.playback, self.last_replay_key, self.selected = {}, None, None
            self._event("REPLAY_STARTED", "SYNTHETIC FALLBACK DATA" if synthetic else "RECORDED LIVE DATA / REPLAY; original relative timing.", simulated=synthetic, capture=name)

    def fallback(self):
        self.start_replay("Bundled synthetic fallback", synthetic_frames(self.origin), True)

    def reset(self):
        with self.lock:
            self.restore()
            self.replay, self.last_replay_key, self.selected = None, None, None
            self.playback = {}
            self.mode = "LIVE"

    def _integrity(self, tracks):
        result = {"active": False, "label": "SIMULATED TELEMETRY MANIPULATION", "trust": 100,
                  "trust_basis": "Demonstration heuristic, not a calibrated probability or authentication verdict",
                  "residual_m": 0, "decision": "NOMINAL", "ghost": None,
                  "authoritative_track_unchanged": True, "warning_threshold_m": 1500, "reject_threshold_m": 4000}
        if not self.attack:
            return result
        track = tracks.get(self.attack["track_id"])
        if not track:
            result.update(active=True, decision="REFERENCE UNAVAILABLE", trust=0)
            return result
        elapsed = min(30, max(0, self.clock() - self.attack["started"]))
        east, north, up = elapsed * 450, elapsed * 300, elapsed * 30 if track.get("up_m") is not None else 0
        residual = math.sqrt(east ** 2 + north ** 2 + up ** 2)
        ghost = {"track_id": track["track_id"], "label": "UNTRUSTED OBSERVATION", "simulated": True,
                 "east_m": track["east_m"] + east, "north_m": track["north_m"] + north,
                 "up_m": track["up_m"] + up if track.get("up_m") is not None else None,
                 "offset": {"east_m": east, "north_m": north, "up_m": up}}
        ghost.update(enu_geometry(ghost["east_m"], ghost["north_m"], ghost["up_m"]))
        for threshold, kind, message in [
            (1500, "POSITION_RESIDUAL_EXCEEDED", "Copied observation exceeds the 1.5 km demonstration residual threshold."),
            (2500, "SENSOR_TRUST_DEGRADED", "Simulated input trust degraded by the residual-based heuristic."),
            (4000, "OBSERVATION_REJECTED", "Simulated observation rejected at 4 km residual. Authoritative track unchanged.")]:
            if residual >= threshold and kind not in self.attack["emitted"]:
                self.attack["emitted"].add(kind)
                self._event(kind, message, "HIGH" if threshold == 4000 else "WARNING", True,
                            track_id=track["track_id"], residual_m=round(residual, 1))
        result.update(active=True, track_id=track["track_id"], trust=max(0, round(100 * (1 - residual / 8000))),
                      residual_m=round(residual, 1), decision="REJECTED" if residual >= 4000 else "ISOLATED TEST INPUT",
                      ghost=ghost, elapsed_s=round(elapsed, 1))
        return result

    def snapshot(self):
        with self.lock:
            tracks, virtual_now, replay = self._active()
            if self.selected not in tracks:
                self.selected = next(iter(tracks), None)
            age = max(0, self.wall() - self.last_success) if self.last_success is not None else None
            status = self.mode if self.replay else ("LIVE" if self.connected and age is not None and age < 30 else "STALE")
            output = []
            for track in tracks.values():
                item = copy.deepcopy(track)
                # Provider age is preserved under the replay clock. Never re-date recordings as live.
                from datetime import datetime
                observed = item.get("observed_at")
                observed_epoch = datetime.fromisoformat(observed.replace("Z", "+00:00")).timestamp() if observed else item.get("received_epoch", virtual_now)
                item["source_age_s"] = round(max(0, virtual_now - observed_epoch), 1)
                item["stale"] = item["source_age_s"] > 30 or (not self.replay and status != "LIVE")
                item["display_provenance"] = "SYNTHETIC FALLBACK DATA" if self.mode == "SYNTHETIC_FALLBACK" else "RECORDED LIVE DATA" if self.replay else "LIVE PUBLIC ADS-B"
                if item["source_age_s"] <= 180:
                    output.append(item)
            return {"schema": "dronewatch.airspace.v1", "mode": self.mode, "status": status,
                    "provider": "ADSB.LOL", "generated_at": iso_time(self.wall()), "sequence": self.sequence,
                    "origin": self.origin.snapshot(), "max_range_m": 50000,
                    "last_success_at": iso_time(self.last_success) if self.last_success is not None else None,
                    "feed_age_s": round(age, 1) if age is not None else None, "error": self.feed_error,
                    "tracks": output, "track_count": len(output), "selected_track_id": self.selected,
                    "integrity": self._integrity(tracks), "replay": replay, "capture": copy.deepcopy(self.capture),
                    "poll_interval_s": 10, "source_description": "Public cooperative aircraft telemetry, not physical radar"}
