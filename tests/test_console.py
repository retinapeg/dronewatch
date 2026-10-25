import asyncio
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dronewatch.realtime import stream_events
from dronewatch.replay import ReplayEngine


@pytest.fixture
def console_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "console.db"))
    monkeypatch.delenv("DRONEWATCH_REPLAY_PATH", raising=False)
    monkeypatch.delenv("DRONEWATCH_MODEL_PATH", raising=False)
    import dronewatch.main as module
    importlib.reload(module)
    with TestClient(module.app) as client:
        yield client, module


def test_existing_api_contract_and_reset_keep_permanent_events(console_client):
    client, module = console_client
    response = client.post("/webhook/viso", json={"appId": "test", "incidentId": "1", "label": "drone"})
    assert response.status_code == 200
    before = client.get("/api/events").json()
    assert {"status", "latest", "open_incidents", "open_count", "events", "received_at"} <= before.keys()
    assert before["total_count"] == 1
    state = client.get("/api/console").json()
    assert state["spatial_available"] is False and state["tracks"] == []
    reset = client.post("/api/demo/reset", json={"mode": "VISO_LIVE"}).json()
    assert reset["permanent_events_deleted"] == 0
    assert reset["console"]["sightings"] == []
    assert client.get("/api/events").json()["events"] == before["events"]


def test_stream_emits_new_event_heartbeat_and_resumes_cursor(console_client):
    client, module = console_client
    class Request:
        async def is_disconnected(self):
            return False
    async def scenario():
        hub = module.app.state.event_hub
        generator = stream_events(Request(), hub, lambda: module.api_events(200), module._query_events_since,
                                  module.console_runtime, "VISO_LIVE", heartbeat=0.01)
        assert "event: snapshot" in await generator.__anext__()
        assert client.post("/webhook/viso", json={"label": "drone", "source": "test"}).status_code == 200
        first = await asyncio.wait_for(generator.__anext__(), 1)
        assert "event: observation" in first and "id: 1" in first
        assert "event: snapshot" in await generator.__anext__()
        assert "event: heartbeat" in await asyncio.wait_for(generator.__anext__(), 1)
        await generator.aclose()
        assert len(hub.listeners) == 0
        client.post("/webhook/viso", json={"label": "drone", "source": "test"})
        reconnect = stream_events(Request(), hub, lambda: module.api_events(200), module._query_events_since,
                                 module.console_runtime, "VISO_LIVE", after_id=1)
        assert "id: 2" in await reconnect.__anext__()
        assert "event: snapshot" in await reconnect.__anext__()
        await reconnect.aclose()
    asyncio.run(scenario())


def test_optional_model_absent_does_not_break_base_modes(console_client):
    client, _ = console_client
    assert client.get("/health").status_code == 200
    assert client.get("/api/sources").json()["local_inference"]["available"] is False
    assert client.post("/api/local/start").status_code == 503
    assert client.get("/api/console?mode=BENCHMARK_REPLAY").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_replay_pause_restart_and_track_sequence_are_deterministic():
    clock = [0.0]
    path = Path(__file__).parents[1] / "samples/synthetic_replay.json"
    replay = ReplayEngine(path, clock=lambda: clock[0])
    replay.control("play", loop=False)
    for i in range(50):
        clock[0] = i / 5
        replay.update()
    first = replay.snapshot()
    assert first["metrics"]["confirmed_sightings"] == 2
    assert first["watermark"] == "RECORDED BENCHMARK REPLAY"
    assert all(track["smoothed_confidence"] is None for track in first["tracks"])
    replay.control("pause")
    paused = replay.current_time
    clock[0] += 10
    replay.update()
    assert replay.current_time == paused
    replay.restart(True)
    origin = clock[0]
    for i in range(50):
        clock[0] = origin + i / 5
        replay.update()
    assert replay.snapshot()["metrics"] == first["metrics"]
    replay.restart(False)
    assert replay.snapshot()["tracks"] == []
    assert replay.snapshot()["metrics"]["confirmed_sightings"] == 0
