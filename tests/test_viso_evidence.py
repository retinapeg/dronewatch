"""Offline provenance/contract guards; these fixtures never prove vendor compliance."""
from datetime import date, datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import pytest

from dronewatch.domain.enums import ObjectClass
from dronewatch.ingest.viso import adapt


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/viso"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())
# Closed, authored values: changes cannot introduce real identifiers or URLs
# simply by recomputing the manifest hashes. No production data is inspected.
SAFE_PAYLOADS = {
    "identified_incident.json": {
        "appId": "synthetic-app", "incidentId": "synthetic-incident",
    },
    "incident_url.json": {
        "incidentUrl": "https://now.viso.ai/incidents/synthetic-incident",
    },
    "narrative_negative.json": {
        "summary": "No drone intrusion event emitted", "note": "drone drone drone",
    },
    "unknown_payload.json": {"something": "unexpected", "value": 3},
}
CONTRACT_SOURCES = {
    "webhook_payload": ["webhook-api", "custom-output-messages"],
    "webhook_authentication": ["webhook-api"],
    "file_video_submission": ["media-processing-model", "input-connectors"],
    "processing_result_retrieval": ["reviewing-results", "webhook-api"],
}


def test_manifest_identifies_only_fabricated_synthetic_fixtures():
    assert MANIFEST["schema_version"] == 1
    assert MANIFEST["data_mode"] == "SYNTHETIC"
    assert MANIFEST["origin"] == "FABRICATED_LOCAL"
    assert MANIFEST["captured_vendor_delivery"] is False
    assert MANIFEST["sanitization"]
    records = MANIFEST["fixtures"]
    assert len(records) == len(SAFE_PAYLOADS)
    assert {entry["path"] for entry in records} == set(SAFE_PAYLOADS)
    assert {p.name for p in FIXTURES.glob("*.json")} == {
        "manifest.json", *SAFE_PAYLOADS,
    }


@pytest.mark.parametrize("entry", MANIFEST["fixtures"], ids=lambda e: e["path"])
def test_fixture_hash_origin_and_safe_identifiers(entry):
    path = FIXTURES / entry["path"]
    assert path.resolve().parent == FIXTURES.resolve()
    assert not path.is_symlink()
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    assert json.loads(raw) == SAFE_PAYLOADS[entry["path"]]
    assert entry["expected_local_outcome"] in {"MAPPED", "UNMAPPED"}
    source_file, source_test = entry["based_on"].split("::")
    assert source_file == "tests/test_preview_api.py"
    assert f"def {source_test}(" in (ROOT / source_file).read_text()


def test_contract_evidence_is_dated_official_and_has_no_unverified_mapping():
    entries = MANIFEST["contract_evidence"]
    assert len(entries) == len(CONTRACT_SOURCES)
    assert {e["contract"] for e in entries} == set(CONTRACT_SOURCES)
    document = (ROOT / "docs/VISO_INTEGRATION.md").read_text()
    for entry in entries:
        assert date.fromisoformat(entry["accessed_on"]) == date(2026, 10, 4)
        assert entry["accessed_on"] in document
        assert entry["status"] == "UNRESOLVED"
        assert entry["retrieval"] == "HTML_METADATA_ONLY"
        assert entry["evidence"].strip()
        assert entry["supported_mapping"] == []
        expected = ["https://docs.now.viso.ai/" + page
                    for page in CONTRACT_SOURCES[entry["contract"]]]
        assert entry["source_urls"] == expected
        for url in entry["source_urls"]:
            parsed = urlsplit(url)
            assert parsed.scheme == "https" and parsed.hostname == "docs.now.viso.ai"
            assert not parsed.username and not parsed.password and not parsed.query
            assert url in document


@pytest.mark.parametrize("entry", MANIFEST["fixtures"], ids=lambda e: e["path"])
def test_synthetic_compatibility_fixtures_never_infer_detection(entry):
    payload = json.loads((FIXTURES / entry["path"]).read_text())
    received = datetime(2026, 10, 4, tzinfo=timezone.utc)
    delivery = adapt(payload, received_at=received, delivery_id="synthetic-delivery")
    assert delivery.outcome.value == entry["expected_local_outcome"]
    assert delivery.observed_at_supplied is False
    assert delivery.position_supplied is False
    if entry["expected_local_outcome"] == "UNMAPPED":
        assert delivery.observation is None
    else:
        observation = delivery.observation
        assert observation is not None
        assert observation.position is None
        assert observation.confidence is None
        assert observation.observed_at == received
        assert observation.classification.probability(ObjectClass.UNKNOWN) == 1.0
        assert observation.classification.probability(ObjectClass.THREAT) == 0.0


@pytest.mark.parametrize("entry", MANIFEST["fixtures"], ids=lambda e: e["path"])
def test_manifest_fixtures_through_protected_webhook(entry, tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "synthetic-viso.db"))
    monkeypatch.setenv("DRONEWATCH_WEBHOOK_SECRET", "synthetic-test-only")
    monkeypatch.delenv("DRONEWATCH_SIMULATION", raising=False)
    import main
    import dronewatch.api.preview as preview
    importlib.reload(preview)
    importlib.reload(main)
    payload = json.loads((FIXTURES / entry["path"]).read_text())
    with TestClient(main.app) as client:
        response = client.post("/v2/webhook/viso", json=payload,
                               headers={"X-DroneWatch-Token": "synthetic-test-only"})
        assert response.status_code == 200
        assert response.json()["outcome"] == entry["expected_local_outcome"]
        events = client.get("/api/events").json()["events"]
        if entry["expected_local_outcome"] == "UNMAPPED":
            assert response.json()["status"] == "quarantined"
            assert events == []
        else:
            assert len(events) == 1
            assert events[0]["drone_detected"] is False
            assert events[0]["state"] == "UNKNOWN"
