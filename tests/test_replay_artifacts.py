import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from replay_artifacts import (
    ArtifactJsonError,
    EvidenceStatus,
    FixtureManifestV1,
    ReplayRunRecordV1,
    ReplayState,
    VisoEvidenceRecordV1,
    dump_artifact,
    load_fixture_manifest,
    load_replay_run_record,
    load_viso_evidence_record,
    strict_json_object,
    validate_artifact_json,
)
from scripts.verify_replay_artifacts import _validate_evidence_manifest_link


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "fixtures" / "halmstad-selection.v1.json"
EVIDENCE_TEMPLATE_PATH = ROOT / "evidence" / "viso-run-template.v1.json"
PINNED_REVISION = "442d0c6750708cc221636f7a1fd31cbd8cb0aeb8"


EXPECTED_MEDIA = {
    "halmstad-v-drone-001": (
        144518,
        "9db5a800377c01db8369dfba808d400ca52cd393e0a32850e1d20a4861eaecbe",
    ),
    "halmstad-ir-drone-001": (
        25853,
        "19ec2ccbcccfdaf3566fff5122c30f8b82172b9e610c975d37558214dcd349d6",
    ),
    "halmstad-v-bird-003": (
        87927,
        "502229dcf0c3633148e97635fcbc8a2bec520b091da3735a51ee6c7b06e074f4",
    ),
    "halmstad-v-airplane-004": (
        96903,
        "940f2243e5a22701c28229b077347026f539070552254dc62be275819f47df9f",
    ),
    "halmstad-v-helicopter-004": (
        93602,
        "7cb2561d567d62086bae684cdd392eeb4c77ee33903a3b068793a6d1a5ef1781",
    ),
    "halmstad-ir-bird-003": (
        20489,
        "5017cbe6415994364987ac5db9dce375059c4709e5ea3d0ecd3aed527926bfdf",
    ),
}


def _manifest_payload():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _run_payload():
    digest = "a" * 64
    return {
        "schema_version": "dronewatch.replay-run.v1",
        "scenario_id": "scenario-1",
        "run_id": "run-1",
        "fixture_id": "fixture-1",
        "manifest_id": "manifest.v1",
        "delivery_mode": "NEAR_REAL_TIME_FILE_REPLAY",
        "provenance": "REPLAYED_REAL",
        "source_sha256": digest,
        "requested_count": 2,
        "interval_seconds": 20.0,
        "started_at": "2026-09-07T10:00:00.000000Z",
        "completed_at": "2026-09-07T10:00:21.000000Z",
        "state": "SUCCEEDED",
        "failure_code": None,
        "completed_count": 2,
        "copies": [
            {
                "sequence_number": 1,
                "source_sha256": digest,
                "destination_basename": "copy-001.mp4",
                "started_at": "2026-09-07T10:00:00.100000Z",
                "completed_at": "2026-09-07T10:00:00.500000Z",
                "completed_copy_sha256": digest,
                "state": "SUCCEEDED",
                "failure_code": None,
            },
            {
                "sequence_number": 2,
                "source_sha256": digest,
                "destination_basename": "copy-002.mp4",
                "started_at": "2026-09-07T10:00:20.500000Z",
                "completed_at": "2026-09-07T10:00:20.900000Z",
                "completed_copy_sha256": digest,
                "state": "SUCCEEDED",
                "failure_code": None,
            },
        ],
        "proof_boundary": (
            "LOCAL_ATOMIC_COPY_ONLY_NOT_DRIVE_SYNC_VISO_PROCESSING_OR_WEBHOOK_DELIVERY"
        ),
    }


def _evidence_payload():
    return {
        "schema_version": "dronewatch.viso-evidence.v1",
        "record_status": "RECORDED",
        "template_notice": None,
        "exact_tested_git_commit": "1" * 40,
        "viso_agent_configuration_date": "2026-09-07",
        "viso_agent_id": "agent-redacted-1",
        "viso_configuration_id": "config-redacted-1",
        "scenario_id": "scenario-1",
        "run_id": "run-1",
        "fixture_id": "halmstad-v-drone-001",
        "fixture_sha256": EXPECTED_MEDIA["halmstad-v-drone-001"][1],
        "local_copy_completed_at": "2026-09-07T10:00:00.000000Z",
        "provider_observed_at": None,
        "dronewatch_received_at": "2026-09-07T10:00:01.500000Z",
        "response_status": 201,
        "redacted_request_sha256": "3" * 64,
        "latency_basis": "RECEIPT_MINUS_LOCAL_COPY_COMPLETED",
        "latency_ms": 1500.0,
        "authentication_route": "BEARER_HEADER_DIRECT",
        "actual_result": "MISS",
        "actual_result_notes": "No positive observation was delivered in the bounded window.",
        "delivery_mode": "NEAR_REAL_TIME_FILE_REPLAY",
        "provenance": "REPLAYED_REAL",
        "limitations": [
            "One supervised transport run cannot establish detection accuracy.",
            "The recorded source is a replayed file rather than a live video stream."
        ],
        "secrets_or_sensitive_data_included": False,
    }


def test_checked_halmstad_manifest_has_exact_verified_selection():
    manifest = load_fixture_manifest(MANIFEST_PATH)
    assert manifest.manifest_id == "halmstad-selection.v1"
    assert manifest.status.value == "VERIFIED"
    assert manifest.dataset.pinned_revision == PINNED_REVISION
    assert manifest.dataset.licences.data.spdx_id == "CC0-1.0"
    assert manifest.dataset.licences.data.source_sha256 == (
        "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"
    )
    assert manifest.dataset.licences.code.status == "NOT_USED"
    assert manifest.dataset.licences.paper.status == "NOT_USED"
    assert manifest.dataset.licences.model.status == "NOT_USED"
    assert len(manifest.fixtures) == 6
    assert {
        fixture.fixture_id: (fixture.derived_bytes, fixture.derived_sha256)
        for fixture in manifest.fixtures
    } == EXPECTED_MEDIA
    assert sum(fixture.expected_result.value == "POSITIVE" for fixture in manifest.fixtures) == 2
    assert sum(fixture.expected_result.value == "NEGATIVE" for fixture in manifest.fixtures) == 4
    assert {fixture.modality.value for fixture in manifest.fixtures} == {
        "VISIBLE",
        "THERMAL_INFRARED",
    }
    assert manifest.selection_method == "PRESELECTED_BEFORE_ANY_VISO_RESULT"
    assert all(
        PINNED_REVISION in str(fixture.source_url) for fixture in manifest.fixtures
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"manifest_id": "."}),
        lambda payload: payload.update({"manifest_id": ".."}),
        lambda payload: payload["fixtures"][0].update({"transformations": []}),
        lambda payload: payload["fixtures"][0].update({"derived_sha256": "0" * 64}),
        lambda payload: payload["fixtures"][0].update({"expected_result": "NEGATIVE"}),
        lambda payload: payload["fixtures"][0].update(
            {"source_url": "https://example.invalid/unpinned/source.mp4"}
        ),
    ],
)
def test_manifest_semantic_tampering_fails_closed(mutate):
    payload = _manifest_payload()
    mutate(payload)
    with pytest.raises(ValidationError):
        FixtureManifestV1.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "body",
    [
        b'{"outer":{"key":1,"key":2}}',
        b'{"number":NaN}',
        b'{"number":Infinity}',
        b'{"number":1e9999}',
        b'{"number":' + (b"9" * 5_000) + b"}",
        b'["not", "an", "object"]',
        b"\xff",
        b'{"unterminated":',
    ],
)
def test_artifact_json_parser_rejects_duplicate_nonfinite_and_malformed_input(body):
    with pytest.raises(ArtifactJsonError):
        strict_json_object(body)


def test_artifact_json_parser_accepts_nested_finite_object():
    assert strict_json_object(b'{"a":{"b":1.25},"items":[true,null]}') == {
        "a": {"b": 1.25},
        "items": [True, None],
    }


def test_run_record_validates_sequence_counts_state_and_relative_basenames(tmp_path):
    payload = _run_payload()
    record = ReplayRunRecordV1.model_validate_json(json.dumps(payload))
    assert record.state is ReplayState.SUCCEEDED
    assert record.completed_count == 2

    path = tmp_path / "run.json"
    path.write_bytes(dump_artifact(record))
    assert load_replay_run_record(path) == record

    invalid = _run_payload()
    invalid["copies"][1]["sequence_number"] = 1
    with pytest.raises(ValidationError):
        ReplayRunRecordV1.model_validate_json(json.dumps(invalid))

    invalid = _run_payload()
    invalid["completed_count"] = 1
    with pytest.raises(ValidationError):
        ReplayRunRecordV1.model_validate_json(json.dumps(invalid))

    invalid = _run_payload()
    invalid["copies"][0]["destination_basename"] = "/private/tmp/copy.mp4"
    with pytest.raises(ValidationError):
        ReplayRunRecordV1.model_validate_json(json.dumps(invalid))

    invalid = _run_payload()
    invalid["run_id"] = ".."
    with pytest.raises(ValidationError):
        ReplayRunRecordV1.model_validate_json(json.dumps(invalid))


def test_strict_run_record_loader_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "run.json"
    path.write_bytes(b'{"schema_version":"one","schema_version":"two"}')
    with pytest.raises(ArtifactJsonError):
        load_replay_run_record(path)


def test_blank_evidence_template_is_valid_and_contains_no_run_claims():
    evidence = load_viso_evidence_record(EVIDENCE_TEMPLATE_PATH)
    assert evidence.record_status is EvidenceStatus.TEMPLATE_DO_NOT_USE_AS_EVIDENCE
    assert evidence.template_notice is not None
    assert evidence.exact_tested_git_commit is None
    assert evidence.viso_agent_id is None
    assert evidence.viso_configuration_id is None
    assert evidence.fixture_sha256 is None
    assert evidence.response_status is None
    assert evidence.delivery_mode is None
    assert evidence.provenance is None
    assert evidence.secrets_or_sensitive_data_included is False


def test_template_cannot_be_mistaken_for_recorded_evidence():
    payload = json.loads(EVIDENCE_TEMPLATE_PATH.read_text(encoding="utf-8"))
    payload["run_id"] = "not-a-real-run"
    with pytest.raises(ValidationError):
        VisoEvidenceRecordV1.model_validate_json(json.dumps(payload))

    payload = _evidence_payload()
    payload["record_status"] = "TEMPLATE_DO_NOT_USE_AS_EVIDENCE"
    with pytest.raises(ValidationError):
        VisoEvidenceRecordV1.model_validate_json(json.dumps(payload))


def test_complete_evidence_requires_all_fields_and_recomputes_latency(tmp_path):
    payload = _evidence_payload()
    evidence = VisoEvidenceRecordV1.model_validate_json(json.dumps(payload))
    assert evidence.record_status is EvidenceStatus.RECORDED
    assert evidence.actual_result.value == "MISS"

    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_bytes(dump_artifact(evidence))
    assert load_viso_evidence_record(evidence_path) == evidence

    missing = _evidence_payload()
    missing["viso_configuration_id"] = None
    with pytest.raises(ValidationError):
        VisoEvidenceRecordV1.model_validate_json(json.dumps(missing))

    wrong_latency = _evidence_payload()
    wrong_latency["latency_ms"] = 1499.0
    with pytest.raises(ValidationError):
        VisoEvidenceRecordV1.model_validate_json(json.dumps(wrong_latency))

    non_utc = _evidence_payload()
    non_utc["dronewatch_received_at"] = "2026-09-07T11:00:01.500000+01:00"
    with pytest.raises(ValidationError):
        VisoEvidenceRecordV1.model_validate_json(json.dumps(non_utc))

    unsafe_id = _evidence_payload()
    unsafe_id["authentication_route"] = "https://secret.example/token"
    with pytest.raises(ValidationError):
        VisoEvidenceRecordV1.model_validate_json(json.dumps(unsafe_id))


def test_recorded_evidence_must_link_to_exact_manifest_fixture_digest():
    manifest = load_fixture_manifest(MANIFEST_PATH)
    evidence = VisoEvidenceRecordV1.model_validate_json(json.dumps(_evidence_payload()))
    _validate_evidence_manifest_link(manifest, evidence)

    mismatched = _evidence_payload()
    mismatched["fixture_sha256"] = "2" * 64
    mismatched_evidence = VisoEvidenceRecordV1.model_validate_json(json.dumps(mismatched))
    with pytest.raises(ValueError):
        _validate_evidence_manifest_link(manifest, mismatched_evidence)

    absent = _evidence_payload()
    absent["fixture_id"] = "not-in-manifest"
    absent_evidence = VisoEvidenceRecordV1.model_validate_json(json.dumps(absent))
    with pytest.raises(ValueError):
        _validate_evidence_manifest_link(manifest, absent_evidence)


def test_provider_timestamp_is_optional_only_with_local_copy_latency_basis():
    payload = _evidence_payload()
    payload["latency_basis"] = "RECEIPT_MINUS_PROVIDER_OBSERVED"
    with pytest.raises(ValidationError):
        VisoEvidenceRecordV1.model_validate_json(json.dumps(payload))

    payload["provider_observed_at"] = "2026-09-07T10:00:01.000000Z"
    payload["latency_ms"] = 500.0
    evidence = VisoEvidenceRecordV1.model_validate_json(json.dumps(payload))
    assert evidence.latency_ms == 500.0


def test_model_json_schemas_include_strict_bounds_and_no_extra_properties():
    manifest_schema = FixtureManifestV1.model_json_schema()
    run_schema = ReplayRunRecordV1.model_json_schema()
    evidence_schema = VisoEvidenceRecordV1.model_json_schema()
    assert manifest_schema["additionalProperties"] is False
    assert run_schema["additionalProperties"] is False
    assert evidence_schema["additionalProperties"] is False
    assert run_schema["properties"]["requested_count"]["maximum"] == 20
    assert run_schema["properties"]["interval_seconds"]["minimum"] == 20.0
    assert run_schema["properties"]["interval_seconds"]["maximum"] == 30.0


def test_validate_artifact_json_rejects_unknown_fields_without_leaking_values():
    payload = _run_payload()
    payload["unknown"] = "secret-looking-value"
    with pytest.raises(ArtifactJsonError) as failure:
        validate_artifact_json(
            ReplayRunRecordV1, json.dumps(payload).encode("utf-8")
        )
    assert "secret-looking-value" not in str(failure.value)
