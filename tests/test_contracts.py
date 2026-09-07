"""Contract-level tests for the provider-neutral V0.2 observation envelope."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from contracts import (
    CanonicalObservationV1,
    InboundObservationV1,
    SCHEMA_VERSION,
    build_canonical_observation,
    content_digest,
    normalized_source_content,
    observation_json_schema,
    observed_at_microseconds,
    rfc3339,
    validate_observation_time,
)


def live_payload(**overrides):
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_event_id": "evt-001",
        "source_system": "CONTRACT_TEST",
        "source_scope": "camera-north",
        "track_id": "track-001",
        "scenario_id": None,
        "run_id": None,
        "observed_at": "2026-09-07T12:00:00.123456Z",
        "modality": "VISUAL",
        "provenance": "LIVE",
        "delivery_mode": "DIRECT",
        "simulation": False,
        "lifecycle_state": "DETECTED",
        "detection_result": "POSITIVE",
        "classification": "DRONE",
        "confidence": 0.875,
        "frame_coordinates": {
            "coordinate_space": "FRAME_NORMALIZED",
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        },
    }
    payload.update(overrides)
    return payload


def test_valid_live_contract_normalizes_timestamp_to_utc():
    payload = live_payload(observed_at="2026-09-07T13:30:00.123456+01:30")

    observation = InboundObservationV1.model_validate(payload)

    assert observation.observed_at == datetime(2026, 9, 7, 12, 0, 0, 123456, tzinfo=timezone.utc)
    assert observation.schema_version == SCHEMA_VERSION
    assert observation.frame_coordinates.coordinate_space == "FRAME_NORMALIZED"


@pytest.mark.parametrize(
    "observed_at",
    [
        "2026-09-07T12:00:00",
        "2026-09-07 12:00:00Z",
        "2026-09-07T12:00:00-00:00",
        "2026-02-30T12:00:00Z",
        "2026-09-07T12:00:00.1234567Z",
        1_789_000_000,
        datetime(2026, 9, 7, tzinfo=timezone.utc),
    ],
)
def test_observed_at_requires_strict_valid_rfc3339(observed_at):
    with pytest.raises(ValidationError):
        InboundObservationV1.model_validate(live_payload(observed_at=observed_at))


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "dronewatch.event.v2"),
        ("modality", "RADAR"),
        ("source_event_id", "https://provider.example/events/1"),
        ("source_event_id", "event id"),
        ("source_event_id", "event@example.com"),
        ("source_scope", "camera/north"),
        ("source_system", "contract-test"),
        ("source_system", "A"),
    ],
)
def test_contract_rejects_unsupported_values_and_unsafe_identifiers(field, value):
    with pytest.raises(ValidationError):
        InboundObservationV1.model_validate(live_payload(**{field: value}))


def test_contract_forbids_unknown_and_server_owned_fields():
    for field, value in (
        ("unexpected", "value"),
        ("observation_id", "00000000-0000-0000-0000-000000000001"),
        ("received_at", "2026-09-07T12:00:01Z"),
    ):
        with pytest.raises(ValidationError):
            InboundObservationV1.model_validate(live_payload(**{field: value}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"provenance": "SYNTHETIC", "delivery_mode": "DIRECT", "simulation": True},
        {"provenance": "SYNTHETIC", "delivery_mode": "LOCAL_SIMULATION", "simulation": False},
        {"provenance": "LIVE", "delivery_mode": "LOCAL_SIMULATION", "simulation": False},
        {"provenance": "LIVE", "delivery_mode": "DIRECT", "simulation": True},
        {
            "provenance": "REPLAYED_REAL",
            "delivery_mode": "DIRECT",
            "simulation": False,
        },
        {
            "provenance": "REPLAYED_REAL",
            "delivery_mode": "NEAR_REAL_TIME_FILE_REPLAY",
            "simulation": True,
        },
    ],
)
def test_provenance_delivery_and_simulation_matrix_is_closed(overrides):
    with pytest.raises(ValidationError):
        InboundObservationV1.model_validate(live_payload(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "provenance": "SYNTHETIC",
            "delivery_mode": "LOCAL_SIMULATION",
            "simulation": True,
            "scenario_id": None,
            "run_id": "run-1",
        },
        {
            "provenance": "REPLAYED_REAL",
            "delivery_mode": "NEAR_REAL_TIME_FILE_REPLAY",
            "simulation": False,
            "scenario_id": "scenario-1",
            "run_id": None,
        },
    ],
)
def test_simulation_and_replay_require_scenario_and_run(overrides):
    with pytest.raises(ValidationError):
        InboundObservationV1.model_validate(live_payload(**overrides))


@pytest.mark.parametrize(
    "provenance,delivery_mode,simulation",
    [
        ("SYNTHETIC", "LOCAL_SIMULATION", True),
        ("REPLAYED_REAL", "NEAR_REAL_TIME_FILE_REPLAY", False),
    ],
)
def test_valid_non_live_provenance_pairs(provenance, delivery_mode, simulation):
    observation = InboundObservationV1.model_validate(
        live_payload(
            provenance=provenance,
            delivery_mode=delivery_mode,
            simulation=simulation,
            scenario_id="scenario-1",
            run_id="run-1",
        )
    )
    assert observation.provenance.value == provenance


@pytest.mark.parametrize(
    "overrides",
    [
        {"classification": "NOT_DRONE"},
        {"lifecycle_state": "UNKNOWN"},
        {"track_id": None},
        {"detection_result": "NEGATIVE", "classification": "DRONE", "lifecycle_state": "UNKNOWN"},
        {"detection_result": "NEGATIVE", "classification": "NOT_DRONE", "lifecycle_state": "DETECTED"},
        {"detection_result": "UNKNOWN", "classification": "DRONE", "lifecycle_state": "UNKNOWN"},
        {"detection_result": "UNKNOWN", "classification": "UNKNOWN", "lifecycle_state": "EXITED"},
    ],
)
def test_detection_classification_lifecycle_consistency(overrides):
    with pytest.raises(ValidationError):
        InboundObservationV1.model_validate(live_payload(**overrides))


@pytest.mark.parametrize(
    "result,classification",
    [("NEGATIVE", "NOT_DRONE"), ("UNKNOWN", "UNKNOWN")],
)
def test_negative_and_unknown_observations_are_explicit(result, classification):
    observation = InboundObservationV1.model_validate(
        live_payload(
            track_id=None,
            lifecycle_state="UNKNOWN",
            detection_result=result,
            classification=classification,
            confidence=None,
            frame_coordinates=None,
        )
    )
    assert observation.detection_result.value == result
    assert observation.classification.value == classification


@pytest.mark.parametrize("state", ["DETECTED", "APPROACHING", "RESTRICTED_ZONE", "EXITED"])
def test_all_positive_lifecycle_states_are_supported(state):
    observation = InboundObservationV1.model_validate(live_payload(lifecycle_state=state))
    assert observation.lifecycle_state.value == state


@pytest.mark.parametrize(
    "frame_coordinates",
    [
        {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        {"coordinate_space": "PIXELS", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        {"coordinate_space": "FRAME_NORMALIZED", "x": -0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        {"coordinate_space": "FRAME_NORMALIZED", "x": 0.9, "y": 0.2, "width": 0.2, "height": 0.4},
        {"coordinate_space": "FRAME_NORMALIZED", "x": 0.1, "y": 0.2, "width": 0.0, "height": 0.4},
        {"coordinate_space": "FRAME_NORMALIZED", "x": True, "y": 0.2, "width": 0.3, "height": 0.4},
        {"coordinate_space": "FRAME_NORMALIZED", "x": "0", "y": 0.2, "width": 0.3, "height": 0.4},
        {"coordinate_space": "FRAME_NORMALIZED", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4, "z": 0.5},
    ],
)
def test_frame_coordinates_are_explicit_normalized_bounded_and_strict(frame_coordinates):
    with pytest.raises(ValidationError):
        InboundObservationV1.model_validate(live_payload(frame_coordinates=frame_coordinates))


@pytest.mark.parametrize("confidence", [-0.01, 1.01, True, "0.8", {"score": 0.8}])
def test_confidence_is_strict_and_bounded(confidence):
    with pytest.raises(ValidationError):
        InboundObservationV1.model_validate(live_payload(confidence=confidence))


def test_integral_json_numbers_are_valid_number_values():
    observation = InboundObservationV1.model_validate(
        live_payload(
            confidence=1,
            frame_coordinates={
                "coordinate_space": "FRAME_NORMALIZED",
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
            },
        )
    )
    assert observation.confidence == 1.0
    assert observation.frame_coordinates.width == 1.0


def test_signed_zero_is_canonicalized():
    observation = InboundObservationV1.model_validate(
        live_payload(
            confidence=-0.0,
            frame_coordinates={
                "coordinate_space": "FRAME_NORMALIZED",
                "x": -0.0,
                "y": 0.2,
                "width": 0.3,
                "height": 0.4,
            },
        )
    )
    assert str(observation.confidence) == "0.0"
    assert str(observation.frame_coordinates.x) == "0.0"


def test_server_builds_identity_and_receipt_time():
    inbound = InboundObservationV1.model_validate(live_payload())
    received_at = datetime(2026, 9, 7, 12, 0, 1, 654321, tzinfo=timezone.utc)

    canonical = build_canonical_observation(inbound, received_at=received_at)

    assert isinstance(canonical, CanonicalObservationV1)
    assert isinstance(canonical.observation_id, UUID)
    assert canonical.received_at == received_at
    assert canonical.observation_id is not None


def test_server_build_rejects_naive_receipt_time():
    inbound = InboundObservationV1.model_validate(live_payload())
    with pytest.raises(ValueError, match="timezone-aware"):
        build_canonical_observation(inbound, received_at=datetime(2026, 9, 7, 12, 0, 1))


def test_content_digest_ignores_server_identity_but_not_source_content():
    inbound = InboundObservationV1.model_validate(live_payload())
    first = build_canonical_observation(
        inbound, received_at=datetime(2026, 9, 7, 12, 0, 1, tzinfo=timezone.utc)
    )
    second = build_canonical_observation(
        inbound, received_at=datetime(2026, 9, 7, 12, 1, 1, tzinfo=timezone.utc)
    )
    changed = build_canonical_observation(
        InboundObservationV1.model_validate(live_payload(confidence=0.876)),
        received_at=second.received_at,
    )

    assert first.observation_id != second.observation_id
    assert normalized_source_content(first) == normalized_source_content(second)
    assert content_digest(first) == content_digest(second)
    assert content_digest(first) != content_digest(changed)


def test_future_tolerance_has_an_inclusive_boundary():
    inbound = InboundObservationV1.model_validate(
        live_payload(observed_at="2026-09-07T12:01:00.000000Z")
    )
    canonical = build_canonical_observation(
        inbound, received_at=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    )
    validate_observation_time(canonical, max_future_seconds=60)

    too_early_receipt = canonical.model_copy(
        update={"received_at": canonical.received_at - timedelta(microseconds=1)}
    )
    with pytest.raises(ValueError, match="future tolerance"):
        validate_observation_time(too_early_receipt, max_future_seconds=60)


def test_rfc3339_and_epoch_microseconds_are_exact():
    value = datetime(1969, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    assert rfc3339(value) == "1969-12-31T23:59:59.999999Z"
    assert observed_at_microseconds(value) == -1


def test_canonical_round_trip_remains_strict():
    inbound = InboundObservationV1.model_validate(live_payload())
    canonical = build_canonical_observation(
        inbound, received_at=datetime(2026, 9, 7, 12, 0, 1, tzinfo=timezone.utc)
    )
    dumped = deepcopy(canonical.model_dump(mode="json"))
    dumped["received_at"] = "2026-09-07T12:00:01-00:00"
    with pytest.raises(ValidationError):
        CanonicalObservationV1.model_validate(dumped)


def test_public_schemas_are_valid_draft_2020_12_and_checked_in_exactly():
    root = Path(__file__).resolve().parent.parent
    for canonical, filename in (
        (False, "dronewatch.event-input.v1.schema.json"),
        (True, "dronewatch.event.v1.schema.json"),
    ):
        generated = observation_json_schema(canonical=canonical)
        Draft202012Validator.check_schema(generated)
        checked_in = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        assert checked_in == generated
        assert generated["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert generated["additionalProperties"] is False


def test_inbound_json_schema_accepts_the_same_valid_semantic_contract():
    schema = observation_json_schema(canonical=False)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(live_payload())
    validator.validate(
        live_payload(
            provenance="REPLAYED_REAL",
            delivery_mode="NEAR_REAL_TIME_FILE_REPLAY",
            simulation=False,
            scenario_id="scenario-1",
            run_id="run-1",
        )
    )


def _invalid_schema_parity_corpus():
    corpus = []
    for overrides in (
        {"provenance": "SYNTHETIC", "delivery_mode": "DIRECT", "simulation": True},
        {"provenance": "LIVE", "delivery_mode": "DIRECT", "simulation": True},
        {
            "provenance": "REPLAYED_REAL",
            "delivery_mode": "NEAR_REAL_TIME_FILE_REPLAY",
            "scenario_id": None,
            "run_id": "run-1",
        },
        {"track_id": None},
        {"classification": "NOT_DRONE"},
        {
            "detection_result": "NEGATIVE",
            "classification": "NOT_DRONE",
            "lifecycle_state": "DETECTED",
        },
        {
            "detection_result": "UNKNOWN",
            "classification": "DRONE",
            "lifecycle_state": "UNKNOWN",
        },
        {"observed_at": "2026-09-07T12:00:00-00:00"},
        {"confidence": True},
        {"source_scope": "https://secret.example/scope"},
        {"unexpected": "closed-world"},
    ):
        corpus.append(live_payload(**overrides))
    return corpus


@pytest.mark.parametrize("payload", _invalid_schema_parity_corpus())
def test_python_and_json_schema_reject_the_same_invalid_semantic_corpus(payload):
    validator = Draft202012Validator(
        observation_json_schema(canonical=False), format_checker=FormatChecker()
    )
    with pytest.raises(ValidationError):
        InboundObservationV1.model_validate(payload)
    assert list(validator.iter_errors(payload)), payload


def test_canonical_schema_requires_server_owned_fields_but_inbound_schema_forbids_them():
    inbound = live_payload()
    canonical_validator = Draft202012Validator(
        observation_json_schema(canonical=True), format_checker=FormatChecker()
    )
    inbound_validator = Draft202012Validator(
        observation_json_schema(canonical=False), format_checker=FormatChecker()
    )
    assert list(canonical_validator.iter_errors(inbound))

    canonical = build_canonical_observation(
        InboundObservationV1.model_validate(inbound),
        received_at=datetime(2026, 9, 7, 12, 0, 1, tzinfo=timezone.utc),
    ).model_dump(mode="json")
    canonical_validator.validate(canonical)
    assert list(inbound_validator.iter_errors(canonical))
