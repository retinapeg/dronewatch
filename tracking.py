"""Small replaceable IoU/constant-velocity tracker, isolated by source and camera."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Protocol

if __package__:
    from .domain import Alert, Detection, Track
else:
    from domain import Alert, Detection, Track


@dataclass
class TrackerConfig:
    confirmation_count: int = 3
    confirmation_window: int = 5
    loss_timeout: float = 1.0
    end_timeout: float = 4.0
    association_threshold: float = 0.1
    centroid_threshold: float = 0.12
    history_length: int = 20
    confidence_alpha: float = 0.25

    def __post_init__(self):
        if not 1 <= self.confirmation_count <= self.confirmation_window:
            raise ValueError("Confirmation count must fit the confirmation window")
        if not 0 < self.loss_timeout < self.end_timeout:
            raise ValueError("Require 0 < loss timeout < end timeout")
        if not 0 < self.association_threshold <= 1 or not 0 < self.centroid_threshold <= 1:
            raise ValueError("Association thresholds must be in (0, 1]")
        if self.history_length < 1 or not 0 < self.confidence_alpha <= 1:
            raise ValueError("Invalid history length or confidence smoothing")

    @classmethod
    def from_env(cls):
        return cls(**{
            name: type(default)(os.getenv("DRONEWATCH_" + name.upper(), default))
            for name, default in vars(cls()).items()
        })


def centroid(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def inside_polygon(point, polygon):
    x, y = point
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[index - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


class Tracker(Protocol):
    def update(self, source: str, camera_id: str, frame_id: str, timestamp: float, detections: list): ...
    def reset(self): ...


class TrackManager:
    def __init__(self, config=None, zones=None):
        self.config = config or TrackerConfig()
        self.zones = zones or {}
        self.reset()

    def reset(self):
        self.tracks = {}
        self.alerts = {}
        self.lifecycle = []
        self.confirmed_sightings = 0
        self.sequence = 0
        self.processed = {}

    def emit(self, track, label, severity, timestamp, explanation):
        self.sequence += 1
        self.lifecycle.insert(0, {"id": self.sequence, "track_id": track.track_id,
            "timestamp": timestamp, "source": track.source, "camera_id": track.camera_id,
            "label": label, "severity": severity, "explanation": explanation})
        del self.lifecycle[300:]

    def alert(self, track, kind, severity, now, explanation):
        key = f"{track.track_id}:{kind}"
        existing = self.alerts.get(key)
        if existing is None or existing.closed_at is not None:
            self.alerts[key] = Alert(key, track.track_id, kind, severity, now, now, explanation, track.source)
            self.emit(track, kind, severity, now, explanation)
        else:
            existing.updated_at = now

    def close_alerts(self, track, now, kind=None):
        for alert in self.alerts.values():
            if alert.track_id == track.track_id and alert.closed_at is None and (kind is None or alert.alert_type == kind):
                alert.closed_at = now
                alert.updated_at = now

    def tick(self, now, scope=None):
        for track in self.tracks.values():
            if track.state == "ended" or (scope is not None and (track.source, track.camera_id) != scope):
                continue
            elapsed = now - track.last_seen
            if elapsed >= self.config.loss_timeout and track.state != "lost":
                track.state = "lost"
                self.alert(track, "TRACK LOST", "watch", now, "No associated observation within the configured grace period.")
            if elapsed >= self.config.end_timeout:
                track.state = "ended"
                self.close_alerts(track, now)
                self.emit(track, "TRACK ENDED", "information", now, "The configured end timeout elapsed.")

    def predicted(self, track, now):
        # Used only for association, never exposed as a measured position or tail point.
        elapsed = min(max(now - track.last_seen, 0), self.config.end_timeout)
        dx, dy = track.velocity[0] * elapsed, track.velocity[1] * elapsed
        x1, y1, x2, y2 = track.bbox
        return x1 + dx, y1 + dy, x2 + dx, y2 + dy

    def update(self, source, camera_id, frame_id, timestamp, detections):
        scope = (source, camera_id)
        recent = self.processed.setdefault(scope, [])
        if frame_id in recent:
            return self.snapshot()
        recent.append(frame_id)
        del recent[:-1000]
        self.tick(timestamp, scope)
        spatial = [d for d in detections if d.bbox is not None]
        candidates = [t for t in self.tracks.values() if (t.source, t.camera_id) == scope and t.state != "ended"]
        pairs = []
        for track in candidates:
            predicted = self.predicted(track, timestamp)
            for index, detection in enumerate(spatial):
                if track.class_name != detection.class_name:
                    continue
                overlap = iou(predicted, detection.bbox)
                distance = math.dist(centroid(predicted), centroid(detection.bbox))
                if overlap >= self.config.association_threshold or distance <= self.config.centroid_threshold:
                    pairs.append((overlap - distance, track.track_id, index))
        used_tracks, used_detections = set(), set()
        for _, track_id, index in sorted(pairs, reverse=True):
            if track_id in used_tracks or index in used_detections:
                continue
            track, detection = self.tracks[track_id], spatial[index]
            used_tracks.add(track_id)
            used_detections.add(index)
            old_center, new_center = centroid(track.bbox), centroid(detection.bbox)
            elapsed = timestamp - track.last_seen
            if elapsed > 0:
                track.velocity = tuple(0.5 * v + 0.5 * (n - o) / elapsed for v, n, o in zip(track.velocity, new_center, old_center))
            was_lost = track.state == "lost"
            track.last_seen = timestamp
            track.observations += 1
            track.bbox = detection.bbox
            track.hits.append(True)
            del track.hits[:-self.config.confirmation_window]
            if detection.confidence is not None:
                alpha = self.config.confidence_alpha
                track.smoothed_confidence = detection.confidence if track.smoothed_confidence is None else alpha * detection.confidence + (1 - alpha) * track.smoothed_confidence
            track.state = "confirmed" if track.confirmed else "tentative"
            if was_lost:
                self.close_alerts(track, timestamp, "TRACK LOST")
                self.emit(track, "OBSERVED", "information", timestamp, "Previously lost track associated again; identity retained.")
            self.observe(track, detection, timestamp)
        for track in candidates:
            if track.track_id not in used_tracks:
                track.hits.append(False)
                del track.hits[:-self.config.confirmation_window]
        for index, detection in enumerate(spatial):
            if index in used_detections:
                continue
            track_id = f"TRK-{len(self.tracks) + 1:03d}"
            track = Track(track_id, camera_id, source, detection.class_name, "tentative", timestamp, timestamp,
                          smoothed_confidence=detection.confidence, bbox=detection.bbox)
            self.tracks[track_id] = track
            self.emit(track, "WATCH", "watch", timestamp, "Tentative spatial track; awaiting confirmation observations.")
            self.observe(track, detection, timestamp)
        return self.snapshot()

    def observe(self, track, detection, now):
        track.centroid_history.append({"x": centroid(detection.bbox)[0], "y": centroid(detection.bbox)[1], "timestamp": now})
        del track.centroid_history[:-self.config.history_length]
        if not track.confirmed and sum(track.hits) >= self.config.confirmation_count:
            track.confirmed = True
            track.state = "confirmed"
            self.confirmed_sightings += 1
            self.emit(track, "OBSERVED", "information", now, f"Confirmed by {self.config.confirmation_count} observations in the latest {self.config.confirmation_window} eligible frames.")
        polygon = self.zones.get(str(track.camera_id))
        zone = ("inside" if inside_polygon(centroid(detection.bbox), polygon) else "outside") if polygon else detection.zone_state
        track.zone_state = zone
        if track.confirmed and str(zone).lower() in {"inside", "restricted_zone", "zone_entry"}:
            self.alert(track, "ZONE ENTRY", "warning", now, "Observed centroid entered the configured image-space monitoring zone." if polygon else "Source explicitly reported zone entry.")
        elif str(zone).lower() == "outside":
            self.close_alerts(track, now, "ZONE ENTRY")

    def snapshot(self):
        active = [track.to_dict() for track in self.tracks.values() if track.state != "ended"]
        alerts = [alert.to_dict() for alert in self.alerts.values() if alert.closed_at is None]
        return {"tracks": active, "alerts": alerts, "lifecycle": list(self.lifecycle),
                "metrics": {"active_tracks": len(active), "confirmed_sightings": self.confirmed_sightings,
                            "open_warnings": sum(a["severity"] == "warning" for a in alerts)}}
