"""Adversarial follow-up: JSON integers also need numeric overflow handling."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "oversized-numeric.db"))
    import main
    importlib.reload(main)
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.mark.parametrize("key", ["confidence", "timestamp"])
def test_huge_json_integer_does_not_crash_ingestion(client, key):
    payload = '{"' + key + '":' + ('1' + '0' * 400) + '}'
    response = client.post("/webhook/viso", content=payload)
    assert response.status_code in {200, 400}
    assert client.get("/api/events").status_code == 200
    assert client.get("/api/targets").status_code == 200
    if response.status_code == 200 and key == "confidence":
        assert client.get("/api/targets").json()["targets"][0]["confidence"] is None


def test_huge_coordinate_does_not_poison_target_api(client):
    payload = '{"position":{"x":' + ('1' + '0' * 400) + ',"y":0}}'
    response = client.post("/webhook/viso", content=payload)
    assert response.status_code in {200, 400}
    targets = client.get("/api/targets")
    assert targets.status_code == 200
    if response.status_code == 200:
        assert targets.json()["targets"][0]["position"] is None


def test_explicit_non_frame_coordinate_system_is_not_relabelled(client):
    client.post("/webhook/viso", json={"position": {"x": 0.2, "y": 0.4, "coordinate_system": "metres"}})
    assert client.get("/api/targets").json()["targets"][0]["position"] is None
