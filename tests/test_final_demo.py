import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dronewatch.final_demo import (
    FinalDemo, WARNING_AT, RESTRICTED_AT, SCENARIOS, bearing,
    snapshot, trajectory, install_final_demo,
)


class Clock:
    now = 0.0
    def __call__(self):
        return self.now


@pytest.mark.parametrize("x,y,expected", [(0, 1, 0), (1, 0, 90), (0, -1, 180), (-1, 0, 270)])
def test_compass(x, y, expected):
    assert bearing(x, y) == expected


def test_drone_milestones():
    for t in [0, 2.999]:
        state = snapshot("drone", t)
        assert state["banner"] == "AIRSPACE CLEAR"
        assert state["detection"] is None and state["track"] is None
    detection = snapshot("drone", 3)
    assert detection["detection"]["class"] == "UAS"
    assert detection["detection"]["label"] == "UAS"
    assert detection["detection"]["confidence"] == .96
    assert detection["banner"] == "VISUAL CONTACT DETECTED"
    assert detection["events"][-1]["message"] == "UAS DETECTED"
    assert detection["track"] is None
    assert snapshot("drone", 6)["system_state"] == "ACQUIRED"
    assert snapshot("drone", 6)["track"]["class"] == "UAS"
    assert snapshot("drone", 8)["system_state"] == "APPROACHING"
    assert snapshot("drone", WARNING_AT - .001)["severity"] == "NORMAL"
    assert snapshot("drone", WARNING_AT)["severity"] == "WARNING"
    assert snapshot("drone", WARNING_AT + .001)["severity"] == "WARNING"
    assert snapshot("drone", WARNING_AT)["track"]["range_m"] == pytest.approx(1000)
    assert snapshot("drone", RESTRICTED_AT - .001)["severity"] == "WARNING"
    assert snapshot("drone", RESTRICTED_AT)["severity"] == "HIGH"
    assert snapshot("drone", RESTRICTED_AT)["track"]["range_m"] == pytest.approx(500)
    assert snapshot("drone", 35)["banner"] == "RESTRICTED AIRSPACE PENETRATION"
    assert 24 <= WARNING_AT <= 28
    assert 30 <= RESTRICTED_AT <= 35


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_geometry_derivatives_and_hold(scenario):
    for t in [6.1, 9, 12]:
        state = snapshot(scenario, t)
        track = state["track"]
        x, y, z = track["x"], track["y"], track["z"]
        assert track["range_m"] == math.hypot(x, y)
        assert track["bearing_deg"] == bearing(x, y)
        assert track["altitude_m"] == z
        assert track["heading_deg"] == bearing(track["vx"], track["vy"])
        assert track["speed_mps"] == math.sqrt(sum(track[key] ** 2 for key in ["vx", "vy", "vz"]))
        next_position, _ = trajectory(scenario, t + .01)
        for value, next_value, key in zip((x,y,z), next_position, ("vx","vy","vz")):
            assert (next_value-value)/.01 == pytest.approx(track[key])
        assert track["id"] == SCENARIOS[scenario]["id"]
    end = snapshot(scenario, SCENARIOS[scenario]["duration"])
    assert end == snapshot(scenario, 1000)
    assert end["complete"]
    assert end["track"]["speed_mps"] == 0
    assert end["track"]["heading_deg"] is None


def test_aircraft_is_safe_normal_transit():
    detected = snapshot("aircraft", 3)
    assert detected["banner"] == "AIRCRAFT DETECTED"
    assert detected["detection"]["label"] == "AIRCRAFT"
    assert detected["track"] is None
    for tick in range(601):
        state = snapshot("aircraft", tick / 10)
        assert state["severity"] == "NORMAL"
        assert not any(event["category"] in {"WARNING", "HIGH"} for event in state["events"])
        if state["track"]:
            assert state["track"]["range_m"] >= 1400
            assert state["track"]["id"] == "AC-001"
            assert state["detection"]["confidence"] == .94
    assert snapshot("aircraft", 10)["banner"] == "AIRCRAFT TRACKED — NORMAL"


def test_bird_never_raises_uas_threat():
    detected = snapshot("bird", 3)
    assert detected["banner"] == "BIRD DETECTED — NON-UAS CONTACT"
    assert detected["system_state"] == "NON_UAS"
    assert detected["track"] is None
    for tick in range(601):
        state = snapshot("bird", tick / 10)
        assert state["severity"] == "NORMAL"
        assert state["system_state"] not in {"APPROACHING", "WARNING", "RESTRICTED"}
        assert not any(event["category"] in {"WARNING", "HIGH"} for event in state["events"])
        if state["detection"]:
            assert state["detection"]["class"] == "BIRD"
            assert state["detection"]["confidence"] == .88
        if state["track"]:
            assert state["track"]["state"] == "NON_UAS"
            assert "NON-UAS CONTACT" in state["banner"]


def test_repeat_reset_pause_and_exactly_once_events():
    clock = Clock()
    demo = FinalDemo(clock)
    runs = []
    for _ in range(2):
        demo.start("drone")
        start = clock.now
        clock.now = start + 15
        paused = demo.pause()
        clock.now += 50
        assert demo.state() == paused
        demo.pause()
        clock.now += 20
        end = demo.state()
        assert end["track"]["id"] == "DW-001" and end["complete"]
        assert len(end["events"]) == 5
        assert len({e["id"] for e in end["events"]}) == 5
        assert [e["category"] for e in end["events"]] == ["SYSTEM", "SENSOR", "TRACK", "WARNING", "HIGH"]
        clock.now += 100
        assert demo.state() == end
        runs.append(end["track"])
        clear = demo.reset()
        assert clear["system_state"] == "CLEAR"
        assert clear["track"] is None and clear["detection"] is None
        assert len(clear["events"]) == 1
    assert runs[0] == runs[1]
    with pytest.raises(ValueError):
        demo.start("unknown")


def test_api_start_scenarios_validation_and_cache():
    app = FastAPI()
    clock = Clock()
    install_final_demo(app, FinalDemo(clock))
    with TestClient(app) as client:
        assert client.get("/api/demo/state").headers["cache-control"] == "no-store"
        for scenario in SCENARIOS:
            result = client.post("/api/demo/start", json={"scenario": scenario})
            assert result.status_code == 200
            assert result.json()["scenario"] == scenario
            assert result.json()["running"]
        assert client.post("/api/demo/start", json={"scenario": "unknown"}).status_code == 422
        assert client.post("/api/demo/pause").json()["running"] is False


def test_real_app_reset_preserves_legacy_api_and_database(tmp_path, monkeypatch):
    from dronewatch import main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.post("/webhook/viso", json={"label": "drone", "event_id": "preserved"}).status_code == 200
        for scenario in SCENARIOS:
            assert client.post("/api/demo/start", json={"scenario": scenario}).status_code == 200
            reset = client.post("/api/demo/reset").json()
            assert reset["system_state"] == "CLEAR" and reset["track"] is None
            assert client.get("/api/events").json()["total_count"] == 1
        assert client.post("/api/demo/reset", json={}).json()["system_state"] == "CLEAR"
        legacy = client.post("/api/demo/reset", json={"mode": "VISO_LIVE"}).json()
        assert legacy["permanent_events_deleted"] == 0
        assert "console" in legacy
        assert client.get("/api/events").json()["total_count"] == 1


def test_local_assets_only_and_svg_visibility():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "final-demo.html").read_text()
    js = (root / "static/final-demo.js").read_text()
    assert 'src="http' not in html and 'href="https:' not in html
    assert "toggleAttribute('hidden', !state.detection)" in js
    assert "toggleAttribute('hidden', !state.track)" in js
