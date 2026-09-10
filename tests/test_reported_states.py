"""Negative observations must never become positive alarms by substring matching."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "negative-observations.db"))
    import main
    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.mark.parametrize("payload", [
    {"label": "bird", "state": "not_detected", "drone_detected": False},
    {"label": "drone", "state": "not_restricted", "drone_detected": False},
    {"label": "not a drone", "drone_detected": False},
    {"label": "not a drone"},
    {"label": "drone", "drone_detected": False},
    {"label": "drone", "state": "no_drone_detected"},
])
def test_negative_observations_do_not_raise_positive_incidents(client, payload):
    assert client.post("/webhook/viso", json=payload).status_code == 200
    latest = client.get("/api/events").json()["latest"]
    assert latest["state"] == "UNKNOWN"
    assert latest["severity"] == "INFO"
    assert latest["drone_detected"] is False


def test_reported_exit_remains_an_exit_when_detection_is_false(client):
    client.post("/webhook/viso", json={"state": "EXITED", "drone_detected": False})
    assert client.get("/api/events").json()["latest"]["state"] == "EXITED"


def test_negated_exit_does_not_falsely_clear_observation(client):
    client.post("/webhook/viso", json={"label": "drone", "state": "not_exited"})
    assert client.get("/api/events").json()["latest"]["state"] == "UNKNOWN"


@pytest.mark.parametrize("state", ["APPROACHING", "RESTRICTED_ZONE"])
def test_explicit_reported_state_remains_supported_without_a_label(client, state):
    client.post("/webhook/viso", json={"state": state})
    latest = client.get("/api/events").json()["latest"]
    assert latest["state"] == state
    # State reports do not imply a positive drone detection field.
    assert latest["drone_detected"] is False
