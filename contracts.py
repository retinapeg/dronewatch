"""Strict provider-neutral observation contracts for DroneWatch V0.2."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "dronewatch.event.v1"
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
SYSTEM_PATTERN = r"^[A-Z][A-Z0-9_]{1,63}$"

Identifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=IDENTIFIER_PATTERN,
        description="Opaque non-secret identifier; never a URL or credential.",
    ),
]
SourceSystem = Annotated[
    str,
    Field(min_length=2, max_length=64, pattern=SYSTEM_PATTERN),
]
Confidence = Annotated[
    float,
    Field(
        strict=True,
        ge=0.0,
        le=1.0,
        description="Source-reported numeric score in the inclusive range 0.0 to 1.0; not a calibrated probability.",
    ),
]
NormalizedCoordinate = Annotated[float, Field(strict=True, ge=0.0, le=1.0)]
PositiveExtent = Annotated[float, Field(strict=True, gt=0.0, le=1.0)]


class Modality(str, Enum):
    VISUAL = "VISUAL"


class Provenance(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    REPLAYED_REAL = "REPLAYED_REAL"
    LIVE = "LIVE"


class DeliveryMode(str, Enum):
    DIRECT = "DIRECT"
    LOCAL_SIMULATION = "LOCAL_SIMULATION"
    NEAR_REAL_TIME_FILE_REPLAY = "NEAR_REAL_TIME_FILE_REPLAY"


class LifecycleState(str, Enum):
    DETECTED = "DETECTED"
    APPROACHING = "APPROACHING"
    RESTRICTED_ZONE = "RESTRICTED_ZONE"
    EXITED = "EXITED"
    UNKNOWN = "UNKNOWN"


class DetectionResult(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    UNKNOWN = "UNKNOWN"


class Classification(str, Enum):
    DRONE = "DRONE"
    NOT_DRONE = "NOT_DRONE"
    UNKNOWN = "UNKNOWN"


def _strict_rfc3339(value: Any) -> datetime:
    if not isinstance(value, str) or not RFC3339_PATTERN.fullmatch(value):
        raise ValueError("timestamp must be an RFC 3339 string with an explicit timezone")
    if value.endswith("-00:00"):
        raise ValueError("timestamp must provide a known UTC offset")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ValueError("timestamp is not a valid calendar time") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp timezone is required")
    return parsed.astimezone(timezone.utc)


class FrameCoordinates(BaseModel):
    """A normalized frame-relative bounding box; never a geographic position."""

    model_config = ConfigDict(extra="forbid", strict=True)

    coordinate_space: Literal["FRAME_NORMALIZED"]
    x: NormalizedCoordinate
    y: NormalizedCoordinate
    width: PositiveExtent
    height: PositiveExtent

    @field_validator("x", "y", "width", "height")
    @classmethod
    def normalize_signed_zero(cls, value: float) -> float:
        return 0.0 if value == 0.0 else value

    @model_validator(mode="after")
    def contained_in_frame(self) -> "FrameCoordinates":
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("frame bounding box must be contained within the normalized frame")
        return self


class InboundObservationV1(BaseModel):
    """Provider-neutral input before DroneWatch adds receipt identity and time."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    schema_version: Literal[SCHEMA_VERSION]
    source_event_id: Identifier
    source_system: SourceSystem
    source_scope: Identifier
    track_id: Identifier | None = None
    scenario_id: Identifier | None = None
    run_id: Identifier | None = None
    observed_at: datetime
    modality: Literal["VISUAL"]
    provenance: Provenance
    delivery_mode: DeliveryMode
    simulation: Annotated[bool, Field(strict=True)]
    lifecycle_state: LifecycleState
    detection_result: DetectionResult
    classification: Classification
    confidence: Confidence | None = None
    frame_coordinates: FrameCoordinates | None = None

    @field_validator("observed_at", mode="before")
    @classmethod
    def strictly_parse_observed_at(cls, value: Any) -> datetime:
        return _strict_rfc3339(value)

    @field_validator("confidence")
    @classmethod
    def normalize_confidence_signed_zero(cls, value: float | None) -> float | None:
        return 0.0 if value == 0.0 else value

    @model_validator(mode="after")
    def enforce_consistency(self) -> "InboundObservationV1":
        if (self.provenance is Provenance.SYNTHETIC) != self.simulation:
            raise ValueError("simulation must be true exactly when provenance is SYNTHETIC")
        expected_modes = {
            Provenance.SYNTHETIC: DeliveryMode.LOCAL_SIMULATION,
            Provenance.REPLAYED_REAL: DeliveryMode.NEAR_REAL_TIME_FILE_REPLAY,
            Provenance.LIVE: DeliveryMode.DIRECT,
        }
        if self.delivery_mode is not expected_modes[self.provenance]:
            raise ValueError("provenance and delivery_mode are inconsistent")
        if self.delivery_mode in {
            DeliveryMode.LOCAL_SIMULATION,
            DeliveryMode.NEAR_REAL_TIME_FILE_REPLAY,
        }:
            if self.scenario_id is None or self.run_id is None:
                raise ValueError("simulation and file replay require scenario_id and run_id")

        positive_states = {
            LifecycleState.DETECTED,
            LifecycleState.APPROACHING,
            LifecycleState.RESTRICTED_ZONE,
            LifecycleState.EXITED,
        }
        if self.detection_result is DetectionResult.POSITIVE:
            if self.classification is not Classification.DRONE:
                raise ValueError("POSITIVE detection_result requires DRONE classification")
            if self.lifecycle_state not in positive_states:
                raise ValueError("POSITIVE detection_result requires an explicit positive lifecycle state")
            if self.track_id is None:
                raise ValueError("positive lifecycle observations require track_id")
        elif self.detection_result is DetectionResult.NEGATIVE:
            if self.classification is not Classification.NOT_DRONE:
                raise ValueError("NEGATIVE detection_result requires NOT_DRONE classification")
            if self.lifecycle_state is not LifecycleState.UNKNOWN:
                raise ValueError("negative observations must use UNKNOWN lifecycle_state")
        else:
            if self.classification is not Classification.UNKNOWN:
                raise ValueError("UNKNOWN detection_result requires UNKNOWN classification")
            if self.lifecycle_state is not LifecycleState.UNKNOWN:
                raise ValueError("unknown observations must use UNKNOWN lifecycle_state")

        if self.lifecycle_state in positive_states and self.track_id is None:
            raise ValueError("lifecycle transitions require track_id")
        return self


class CanonicalObservationV1(InboundObservationV1):
    """Persisted `dronewatch.event.v1` observation."""

    observation_id: UUID
    received_at: datetime

    @field_validator("received_at", mode="before")
    @classmethod
    def strictly_parse_received_at(cls, value: Any) -> datetime:
        return _strict_rfc3339(value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def build_canonical_observation(
    inbound: InboundObservationV1,
    *,
    received_at: datetime | None = None,
    observation_id: UUID | None = None,
) -> CanonicalObservationV1:
    server_time = received_at or utcnow()
    if server_time.tzinfo is None or server_time.utcoffset() is None:
        raise ValueError("server received_at must be timezone-aware")
    payload = inbound.model_dump(mode="json")
    payload["observation_id"] = str(observation_id or uuid4())
    payload["received_at"] = rfc3339(server_time)
    return CanonicalObservationV1.model_validate(payload)


def validate_observation_time(
    observation: CanonicalObservationV1,
    *,
    max_future_seconds: int,
) -> None:
    maximum = observation.received_at + timedelta(seconds=max_future_seconds)
    if observation.observed_at > maximum:
        raise ValueError("observed_at is later than the configured future tolerance")


def normalized_source_content(observation: CanonicalObservationV1) -> dict[str, Any]:
    """Return the deterministic provider content used for retry comparison."""

    return observation.model_dump(
        mode="json",
        exclude={"observation_id", "received_at"},
        exclude_none=True,
    )


def content_digest(observation: CanonicalObservationV1) -> str:
    encoded = json.dumps(
        normalized_source_content(observation),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def observed_at_microseconds(value: datetime) -> int:
    normalized = value.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = normalized - epoch
    return ((delta.days * 86_400 + delta.seconds) * 1_000_000) + delta.microseconds


def _non_null_identifier_rule(field: str) -> dict[str, Any]:
    return {
        "required": [field],
        "properties": {field: {"type": "string", "minLength": 1}},
    }


def _semantic_json_schema_rules() -> list[dict[str, Any]]:
    """JSON Schema equivalents for the contract's cross-field invariants.

    Pydantic does not emit model-validator logic in its generated schema.  Keep
    the public schema fail-closed by expressing those relationships explicitly.
    The frame-containment sum remains a Python semantic check because standard
    JSON Schema has no portable numeric-addition keyword.
    """

    return [
        {
            "if": {"properties": {"provenance": {"const": "SYNTHETIC"}}, "required": ["provenance"]},
            "then": {
                "properties": {
                    "delivery_mode": {"const": "LOCAL_SIMULATION"},
                    "simulation": {"const": True},
                },
                "required": ["delivery_mode", "simulation", "scenario_id", "run_id"],
                "allOf": [
                    _non_null_identifier_rule("scenario_id"),
                    _non_null_identifier_rule("run_id"),
                ],
            },
        },
        {
            "if": {"properties": {"provenance": {"const": "REPLAYED_REAL"}}, "required": ["provenance"]},
            "then": {
                "properties": {
                    "delivery_mode": {"const": "NEAR_REAL_TIME_FILE_REPLAY"},
                    "simulation": {"const": False},
                },
                "required": ["delivery_mode", "simulation", "scenario_id", "run_id"],
                "allOf": [
                    _non_null_identifier_rule("scenario_id"),
                    _non_null_identifier_rule("run_id"),
                ],
            },
        },
        {
            "if": {"properties": {"provenance": {"const": "LIVE"}}, "required": ["provenance"]},
            "then": {
                "properties": {
                    "delivery_mode": {"const": "DIRECT"},
                    "simulation": {"const": False},
                },
                "required": ["delivery_mode", "simulation"],
            },
        },
        {
            "if": {
                "properties": {"detection_result": {"const": "POSITIVE"}},
                "required": ["detection_result"],
            },
            "then": {
                "properties": {
                    "classification": {"const": "DRONE"},
                    "lifecycle_state": {
                        "enum": ["DETECTED", "APPROACHING", "RESTRICTED_ZONE", "EXITED"]
                    },
                },
                "required": ["classification", "lifecycle_state", "track_id"],
                "allOf": [_non_null_identifier_rule("track_id")],
            },
        },
        {
            "if": {
                "properties": {"detection_result": {"const": "NEGATIVE"}},
                "required": ["detection_result"],
            },
            "then": {
                "properties": {
                    "classification": {"const": "NOT_DRONE"},
                    "lifecycle_state": {"const": "UNKNOWN"},
                },
                "required": ["classification", "lifecycle_state"],
            },
        },
        {
            "if": {
                "properties": {"detection_result": {"const": "UNKNOWN"}},
                "required": ["detection_result"],
            },
            "then": {
                "properties": {
                    "classification": {"const": "UNKNOWN"},
                    "lifecycle_state": {"const": "UNKNOWN"},
                },
                "required": ["classification", "lifecycle_state"],
            },
        },
    ]


def observation_json_schema(*, canonical: bool = True) -> dict[str, Any]:
    """Return the deterministic Draft 2020-12 public contract schema."""

    model = CanonicalObservationV1 if canonical else InboundObservationV1
    schema = deepcopy(model.model_json_schema(mode="validation"))
    filename = "dronewatch.event.v1.schema.json" if canonical else "dronewatch.event-input.v1.schema.json"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://dronewatch.invalid/schemas/{filename}"
    schema["title"] = "DroneWatch canonical observation v1" if canonical else "DroneWatch inbound observation v1"
    schema["allOf"] = _semantic_json_schema_rules()
    timestamp_pattern = (
        r"^(?!.*-00:00$)\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
    )
    schema["properties"]["observed_at"]["pattern"] = timestamp_pattern
    schema["properties"]["observed_at"]["description"] = (
        "Time reported by the source observation; never replaced with DroneWatch receipt time."
    )
    if canonical:
        schema["properties"]["received_at"]["pattern"] = timestamp_pattern
        schema["properties"]["received_at"]["readOnly"] = True
        schema["properties"]["received_at"]["description"] = (
            "Receipt time assigned only by DroneWatch at request entry."
        )
        schema["properties"]["observation_id"]["readOnly"] = True
        schema["properties"]["observation_id"]["description"] = (
            "DroneWatch internal observation UUID; distinct from source_event_id and track_id."
        )
    schema["$comment"] = (
        "Frame coordinates are normalized image-plane coordinates, never geographic, radar-derived, "
        "or calibrated. The Python validator additionally enforces x + width <= 1 and y + height <= 1."
    )
    return schema
