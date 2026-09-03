import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "dronewatch_test.db"))
    monkeypatch.setenv("DRONEWATCH_SIMULATION", "1")
    import dronewatch.main as app_module
    importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        yield client, app_module


def test_health_endpoint(client):
    test_client, _ = client
    response = test_client.get('/health')
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_webhook_valid_payload(client):
    test_client, app_module = client
    payload = {
        "event_id": "evt-test-1",
        "label": "drone",
        "confidence": 0.91,
        "state": "restricted_zone",
        "source": "camera-1",
        "media_url": "https://example.com/video.mp4",
    }

    response = test_client.post('/webhook/viso', json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    events = test_client.get('/api/events?limit=5').json()
    assert len(events["events"]) == 1
    latest = events["events"][0]
    assert latest["event_id"] == "evt-test-1"
    assert latest["detection_type"] == "drone"
    assert latest["state"] == "RESTRICTED_ZONE"
    assert latest["drone_detected"] is True


def test_webhook_unexpected_json(client):
    test_client, _ = client

    response = test_client.post('/webhook/viso', json={"unexpected": [1, 2, {"foo": "bar"}], "weird": True})
    assert response.status_code == 200

    events = test_client.get('/api/events?limit=5').json()
    assert events["events"][0]["detection_type"] in (None, "", "[1, 2, {'foo': 'bar'}]")


def test_webhook_empty_json(client):
    test_client, _ = client
    response = test_client.post('/webhook/viso', json={})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_database_persistence(client):
    test_client, app_module = client
    payload = {"label": "drone", "confidence": 0.72, "source": "camera-db"}
    test_client.post('/webhook/viso', json=payload)

    conn = sqlite3.connect(app_module.DB_PATH)
    rows = conn.execute("SELECT event_id, detection_type, confidence, source FROM incidents").fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][1] == "drone"
    assert rows[0][3] == "camera-db"
