"""Common airspace representation. ENU metres are never inferred from camera pixels."""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def iso_time(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def compass_angle(east, north):
    if not all(math.isfinite(value) for value in (east, north)):
        raise ValueError("coordinates must be finite")
    if math.hypot(east, north) < 1e-9:
        return None
    return math.degrees(math.atan2(east, north)) % 360


@dataclass(frozen=True)
class Position:
    x_m: float
    y_m: float
    z_m: float

    def __post_init__(self):
        if not all(math.isfinite(value) for value in (self.x_m, self.y_m, self.z_m)):
            raise ValueError("position must be finite ENU metres")


@dataclass(frozen=True)
class Velocity:
    vx_mps: float
    vy_mps: float
    vz_mps: float

    def __post_init__(self):
        if not all(math.isfinite(value) for value in (self.vx_mps, self.vy_mps, self.vz_mps)):
            raise ValueError("velocity must be finite metres per second")


@dataclass(frozen=True)
class AirspaceConfig:
    max_range_m: float = 2500.0
    warning_radius_m: float = 1200.0
    restricted_radius_m: float = 500.0
    update_hz: int = 10
    history_length: int = 120

    def __post_init__(self):
        if not (0 < self.restricted_radius_m < self.warning_radius_m < self.max_range_m < 1_000_000):
            raise ValueError("require 0 < restricted radius < warning radius < maximum range")
        if not 5 <= self.update_hz <= 10 or not 2 <= self.history_length <= 300:
            raise ValueError("update_hz must be 5-10 and history_length 2-300")

    @classmethod
    def from_env(cls):
        defaults = asdict(cls())
        return cls(**{name: type(default)(os.environ.get("DRONEWATCH_" + name.upper(), default))
                      for name, default in defaults.items()})


def derived_telemetry(position: Optional[Position], velocity: Optional[Velocity]):
    """Horizontal range/speed; altitude is up from the local origin, not AGL."""
    return {
        "range_m": math.hypot(position.x_m, position.y_m) if position else None,
        "bearing_deg": compass_angle(position.x_m, position.y_m) if position else None,
        "altitude_m": position.z_m if position else None,
        "ground_speed_mps": math.hypot(velocity.vx_mps, velocity.vy_mps) if velocity else None,
        "heading_deg": compass_angle(velocity.vx_mps, velocity.vy_mps) if velocity else None,
    }


def zone_state(position, velocity, config, phase="TRANSIT"):
    distance = math.hypot(position.x_m, position.y_m)
    if distance < config.restricted_radius_m:
        return "RESTRICTED", "RESTRICTED_ZONE", "HIGH"
    if distance <= config.warning_radius_m:
        closing = position.x_m * velocity.vx_mps + position.y_m * velocity.vy_mps < 0
        state = "LOITERING" if phase == "LOITERING" else "APPROACHING" if closing else "EXITING"
        return "WARNING", state, "WARNING"
    return "OUTER", "DETECTED", "INFO"


@dataclass
class AirspaceTrack:
    track_id: str
    source: str
    synthetic: bool
    position_source: str
    first_seen: str
    last_seen: str
    position: Optional[Position] = None
    velocity: Optional[Velocity] = None
    object_class: str = "UAS"
    confidence: Optional[float] = None
    state: str = "DETECTED"
    severity: str = "INFO"
    zone: str = "UNKNOWN"
    phase: str = "TRANSIT"
    history: list = field(default_factory=list)
    observation_count: int = 0
    spatial: bool = True
    source_payload_reference: Optional[str] = None

    def snapshot(self):
        data = asdict(self)
        data.update(derived_telemetry(self.position, self.velocity))
        data["coordinate_frame"] = "LOCAL_ENU_METRES" if self.position else None
        data["confidence_source"] = "SCENARIO_PARAMETER" if self.synthetic else "SENSOR_REPORTED"
        return data


def primary_track(tracks):
    candidates = [track for track in tracks if track.position is not None and track.state != "EXITED"]
    if not candidates:
        return None
    rank = {"HIGH": 3, "WARNING": 2, "INFO": 1}
    return min(candidates, key=lambda track: (-rank.get(track.severity, 0),
        math.hypot(track.position.x_m, track.position.y_m), track.track_id)).track_id


def visual_sighting(event):
    """Adapter boundary: a camera observation is not a positioned physical track.

    Keep range/bearing/velocity null even if the payload contains image boxes or
    qualitative prose. A future positioned-sensor adapter must supply a validated
    coordinate frame and measured Position/Velocity explicitly.
    """
    confidence = event.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        confidence = None
    return AirspaceTrack(
        track_id="OBS-%s" % event["id"], source="VISO", synthetic=False,
        position_source="NOT PROVIDED", first_seen=event["received_at"], last_seen=event["received_at"],
        object_class=event.get("detection_type") or "UNCLASSIFIED", confidence=confidence,
        state=event.get("state", "UNKNOWN"), severity=event.get("severity", "INFO"),
        spatial=False, source_payload_reference=str(event["id"]), observation_count=1,
    ).snapshot()
