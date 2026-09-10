"""Reproductions of Claude Code review87a6875, with manager-selected semantics.

Keep source/receipt time distinct; do not replace observation age with receipt age.
Do not adopt maximum-confidence-object selection without a provider object adapter.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "claude-semantic-probes.db"))
    import main
    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client


def latest(client, payload):
    assert client.post("/webhook/viso", json=payload).status_code == 200
    return client.get("/api/events").json()["latest"]


def test_explicit_event_id_wins_over_camera_id_regardless_of_key_order(client):
    event = latest(client, {"camera_id": "camera-7", "id": "generic-3", "event_id": "evt-1"})
    assert event["event_id"] == "evt-1"


def test_processing_time_is_not_an_observation_timestamp(client):
    event = latest(client, {"processing_time_ms": 42, "timestamp": "2025-02-01T12:00:00Z"})
    assert event["received_at"] == "2025-02-01T12:00:00+00:00"


def test_http_status_does_not_become_zone_state(client):
    event = latest(client, {"http_status": "restricted", "label": "bird"})
    assert event["state"] == "UNKNOWN"
    assert event["severity"] == "INFO"


def test_callback_url_does_not_become_sensor_media(client):
    event = latest(client, {"callback_url": "https://example.invalid/beacon"})
    assert event["media_url"] is None


@pytest.mark.parametrize("state", ["exited_restricted_zone", "no_drone_detected", "undetected", "DRONE_ZONE_INTRUSION_CLEARED"])
def test_cleared_or_negative_states_never_project_as_active_threat(client, state):
    event = latest(client, {"state": state, "label": "drone", "confidence": 0.99})
    assert event["severity"] != "HIGH"
    target = client.get("/api/targets").json()["targets"][0]
    assert target["status"] == "UNKNOWN"


def test_ambiguous_multiple_objects_do_not_choose_max_confidence_as_ground_truth(client):
    latest(client, {"labels": [{"label": "bird", "confidence": 0.2}, {"label": "drone", "confidence": 0.99}]})
    target = client.get("/api/targets").json()["targets"][0]
    assert target["status"] == "UNKNOWN"
    assert target["confidence"] is None
    assert "multiple" in target["uncertainty"].lower() or "ambiguous" in target["uncertainty"].lower()
