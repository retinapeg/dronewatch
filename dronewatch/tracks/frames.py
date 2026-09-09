"""Builds a replayable timeline of track states.

The server runs the tracker once over a scenario and emits snapshots at a fixed
rate. The browser replays those snapshots, so what an operator sees is exactly
what the tested Python tracker produced, and playback speed cannot change the
result.

Only observations reach this module. It has no access to ground truth, and the
M1 import guard enforces that.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ..domain.enums import Modality
from ..domain.observation import GeoPosition, SensorObservation
from .attention import PRIORITY_ORDER, AttentionModel
from .site import MonitoredSite
from .tracker import Tracker, TrackerConfig, TrackState

#: Snapshot rate. Fine enough to look continuous, coarse enough to stay small.
FRAME_HZ = 5.0

#: The tracker consumes one positional modality. Fusing five is a later slice.
TRACKING_MODALITY = Modality.RADAR


def _sim_seconds(moment: datetime, t_zero: datetime) -> float:
    return (moment - t_zero).total_seconds()


def _as_measurement(observation: SensorObservation, t_zero: datetime) -> Optional[Dict[str, Any]]:
    position = observation.position
    if not isinstance(position, GeoPosition):
        return None
    # M2 stores local simulation metres in this container; see the preview API.
    return {
        "observation_id": observation.observation_id,
        "t": _sim_seconds(observation.observed_at, t_zero),
        "received_t": _sim_seconds(observation.received_at, t_zero),
        "x": position.latitude,
        "y": position.longitude,
        "z": position.altitude_m,
    }


def build_timeline(
    observations: Sequence[SensorObservation],
    *,
    t_zero: datetime,
    duration_s: float,
    site: Optional[MonitoredSite] = None,
    config: Optional[TrackerConfig] = None,
    frame_hz: float = FRAME_HZ,
) -> Dict[str, Any]:
    """Run the tracker over a scenario and snapshot it at a fixed rate."""
    site = site or MonitoredSite()
    tracker = Tracker(config)
    attention = AttentionModel(site)

    measurements = [
        measurement
        for measurement in (
            _as_measurement(observation, t_zero)
            for observation in observations
            if observation.modality is TRACKING_MODALITY
        )
        if measurement is not None
    ]
    # Delivery order, which is what a live system would see.
    measurements.sort(key=lambda m: (m["received_t"], m["observation_id"]))

    frames: List[Dict[str, Any]] = []
    step = 1.0 / frame_hz
    cursor = 0
    frame_count = int(round(duration_s * frame_hz)) + 1

    for index in range(frame_count):
        now = round(index * step, 3)
        due = []
        while cursor < len(measurements) and measurements[cursor]["received_t"] <= now:
            due.append(measurements[cursor])
            cursor += 1

        tracker.process(due, now=now)

        snapshots = []
        for track in tracker.visible_tracks():
            rule = attention.update(track, now)
            distance = site.range_to(track.x, track.y)
            # Kept deliberately small: 5 Hz x up to 10 tracks x 90 s adds up,
            # and velocity is recoverable from speed and heading.
            snapshots.append({
                "id": track.track_id,
                "x": round(track.x, 1),
                "y": round(track.y, 1),
                "speed": round(track.speed_m_s, 1),
                "heading": round(track.heading_deg, 1),
                "status": track.status.value,
                "priority": rule.priority.value,
                "reason": rule.reason,
                "range_m": round(distance),
                "altitude_m": (
                    round(track.last_altitude_m)
                    if track.last_altitude_m is not None else None
                ),
                "age_s": round(now - track.last_update_at, 1),
            })

        snapshots.sort(key=lambda s: (PRIORITY_ORDER[_priority(s)], s["range_m"]))
        frames.append({"t": now, "tracks": snapshots, "obs": cursor})

    return {
        "site": {
            "name": site.name, "x": site.x, "y": site.y,
            "radius_m": site.radius_m,
        },
        "frame_hz": frame_hz,
        "duration_s": duration_s,
        "frames": frames,
        "measurement_count": len(measurements),
        "tracking_modality": TRACKING_MODALITY.value,
        "tracks_confirmed": tracker.created_count,
        "tracks_created": tracker.created_count,
        "tracks_spawned": tracker.spawn_count,
        "duplicates_ignored": tracker.duplicate_count,
    }


def _priority(snapshot: Dict[str, Any]):
    from .attention import Priority

    return Priority(snapshot["priority"])
