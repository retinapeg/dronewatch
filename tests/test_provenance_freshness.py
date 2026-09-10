"""Manager review: unauthenticated delivery and receipt time are not sensor proof."""
import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "provenance.db"))
    import main
    importlib.reload(main)
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client, main


@pytest.mark.parametrize("payload,expected", [
    ({"source": "camera-1", "label": "drone"}, "WEBHOOK_EVENT"),
    ({"source": "VISO", "appId": "app", "incidentId": "evt"}, "WEBHOOK_EVENT"),
    ({"source": "manual-test", "label": "drone"}, "TEST_EVENT"),
    ({"source": "SIMULATED", "label": "drone"}, "SYNTHETIC_EVENT"),
    ({"source": "camera-1", "is_simulated": True}, "SYNTHETIC_EVENT"),
    ({"source": "camera-1", "SIMULATED": True}, "SYNTHETIC_EVENT"),
])
def test_unverified_webhook_provenance_cannot_claim_sensor_origin(client, payload, expected):
    test_client, _ = client
    assert test_client.post("/webhook/viso", json=payload).status_code == 200
    target = test_client.get("/api/targets").json()["targets"][0]
    assert target["source_kind"] == expected


@pytest.mark.parametrize("timestamp", [None, "yesterday", "", True, 10 ** 400])
def test_missing_or_invalid_source_time_does_not_look_recent(client, timestamp):
    test_client, _ = client
    payload = {"label": "drone"}
    if timestamp is not None:
        payload["timestamp"] = timestamp
    assert test_client.post("/webhook/viso", json=payload).status_code == 200
    target = test_client.get("/api/targets").json()["targets"][0]
    assert target["updated_at"] == ""
    assert target["timestamp_basis"] == "receipt_time_only"
    assert target["last_received_at"]


def test_source_and_receipt_timestamps_remain_distinct(client):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"timestamp": "2025-01-01T00:00:00Z", "label": "drone"})
    target = test_client.get("/api/targets").json()["targets"][0]
    assert target["updated_at"] == "2025-01-01T00:00:00+00:00"
    assert target["timestamp_basis"] == "reported_event_time"
    assert target["last_received_at"] > target["updated_at"]


@pytest.mark.parametrize("body", [b'{"label":"\\ud800"}', b'{"\\ud800":"value"}'])
def test_unpaired_unicode_surrogate_returns_400_not_500(client, body):
    test_client, _ = client
    assert test_client.post("/webhook/viso", content=body).status_code == 400
    assert test_client.get("/api/events").json()["events"] == []


def test_valid_unicode_surrogate_pair_remains_supported(client):
    test_client, _ = client
    assert test_client.post("/webhook/viso", content=b'{"label":"\\ud83d\\ude80"}').status_code == 200


def test_receipt_timestamp_is_persisted_without_overwriting_source_timestamp(client):
    test_client, main = client
    test_client.post("/webhook/viso", json={"timestamp": "2025-01-01T00:00:00Z"})
    with sqlite3.connect(main.DB_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(incidents)")}
        assert "ingested_at" in columns
        row = conn.execute("SELECT received_at, ingested_at FROM incidents").fetchone()
    assert row[0] == "2025-01-01T00:00:00+00:00"
    assert row[1] > row[0]


def test_legacy_fallback_timestamp_is_not_promoted_to_verified_source_time(client):
    test_client, main = client
    test_client.post("/webhook/viso", json={"event_id": "legacy-without-source-time", "label": "drone"})
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute("UPDATE incidents SET received_at = ?, ingested_at = NULL", ("2026-09-10T12:00:00+00:00",))
    target = test_client.get("/api/targets").json()["targets"][0]
    assert target["updated_at"] == ""
    assert target["timestamp_basis"] == "receipt_time_only"
    assert target["last_received_at"] == ""
