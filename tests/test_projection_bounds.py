"""Claude H1 follow-up: projection size and identity must survive hostile metadata."""
import importlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "projection-bounds.db"))
    import main
    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client, main


@pytest.mark.parametrize("field", ["target_id", "source", "label"])
def test_accepted_200k_metadata_cannot_poison_frontend_or_expand_projection(client, field):
    test_client, _ = client
    assert test_client.post("/webhook/viso", json={field: "A" * 200000}).status_code == 200
    response = test_client.get("/api/targets")
    target = response.json()["targets"][0]
    assert len(target["target_id"].encode()) <= 128
    assert len(target["event_id"].encode()) <= 128
    assert len(target["source"].encode()) <= 128
    assert all(len(item.encode()) <= 160 for item in target["evidence"])
    assert len(response.content) < 2000


@pytest.mark.parametrize("field", ["target_id", "source"])
def test_long_shared_prefix_identifiers_remain_distinct_and_stable(client, field):
    test_client, _ = client
    for suffix in ("one", "two"):
        payload = {"event_id": suffix, "target_id": "shared-target", "source": "camera", field: "same-prefix-" * 1000 + suffix}
        assert test_client.post("/webhook/viso", json=payload).status_code == 200
    first = test_client.get("/api/targets").json()["targets"]
    second = test_client.get("/api/targets").json()["targets"]
    assert len(first) == 2
    assert len({item[field] for item in first}) == 2
    assert first == second
    assert all(len(item[field].encode()) <= 128 for item in first)


def test_short_input_cannot_spoof_generated_long_identifier(client):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"event_id": "long", "target_id": "X" * 2000})
    generated = test_client.get("/api/targets").json()["targets"][0]["target_id"]
    test_client.post("/webhook/viso", json={"event_id": "spoof", "target_id": generated})
    targets = test_client.get("/api/targets").json()["targets"]
    assert len(targets) == 2
    assert len({item["target_id"] for item in targets}) == 2


def test_identity_hashes_are_scoped_to_fields_and_unicode_is_byte_bounded(client):
    test_client, _ = client
    value = "🚀" * 1000
    test_client.post("/webhook/viso", json={"event_id": value, "target_id": value, "source": value})
    target = test_client.get("/api/targets").json()["targets"][0]
    assert len({target[key] for key in ("event_id", "target_id", "source")}) == 3
    assert all(len(target[key].encode()) <= 128 for key in ("event_id", "target_id", "source"))


def test_canonical_response_has_explicit_byte_budget(client):
    test_client, main = client
    # Saturate every bounded metadata field with JSON-escaped text. Directly
    # insert valid normalized records to avoid spending time on 200 HTTP posts.
    for index in range(200):
        payload = {"event_id": '"\\' * 2000 + str(index), "target_id": '"\\' * 2000 + str(index), "source": '"\\' * 2000 + str(index), "label": '"\\' * 2000}
        main._write_incident(main._normalize_incident(payload, "VISO"))
    response = test_client.get("/api/targets")
    assert response.status_code == 200
    assert len(response.content) <= 256 * 1024
    assert response.json().get("truncated") is True
    assert 0 < len(response.json()["targets"]) < 200


def test_old_deep_raw_payload_does_not_poison_canonical_response(client):
    test_client, main = client
    test_client.post("/webhook/viso", json={"event_id": "legacy-deep"})
    raw = {}
    for _ in range(300):
        raw = {"nested": raw}
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute("UPDATE incidents SET raw_payload = ?, ingested_at = NULL", (json.dumps(raw),))
    response = test_client.get("/api/targets")
    assert response.status_code == 200
    assert len(response.content) < 2000
    assert response.json()["targets"][0]["target_id"] == "legacy-deep"


def test_legacy_track_id_alias_coalesces_repeated_events_within_source(client):
    test_client, _ = client
    for event_id, source in (("evt-1", "camera-a"), ("evt-2", "camera-a"), ("evt-3", "camera-b")):
        test_client.post("/webhook/viso", json={"event_id": event_id, "track_id": "SIM001", "source": source})
    targets = test_client.get("/api/targets").json()["targets"]
    assert len(targets) == 2
    assert {target["target_id"] for target in targets} == {"SIM001"}
    assert {target["event_id"] for target in targets} == {"evt-2", "evt-3"}
    assert {target["source"] for target in targets} == {"camera-a", "camera-b"}


def test_conflicting_track_aliases_remain_ambiguous(client):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"event_id": "ambiguous", "track_id": "one", "tracking_id": "two"})
    assert test_client.get("/api/targets").json()["targets"][0]["target_id"] == "ambiguous"
