import importlib
import json
import math
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "boundary.db"))
    monkeypatch.setenv("DRONEWATCH_SIMULATION", "1")
    import main as app_module

    importlib.reload(app_module)
    with TestClient(app_module.app) as test_client:
        yield test_client, app_module


@pytest.mark.parametrize("confidence", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_webhook_rejects_non_finite_json_numbers_without_poisoning_events(client, confidence):
    test_client, _ = client
    response = test_client.post(
        "/webhook/viso",
        content=f'{{"event_id":"bad-number","confidence":{confidence}}}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    events = test_client.get("/api/events")
    assert events.status_code == 200
    assert events.json()["events"] == []


def test_webhook_rejects_invalid_utf8_and_malformed_json(client):
    test_client, _ = client
    invalid_utf8 = test_client.post(
        "/webhook/viso", content=b'{"label":"drone","note":"\xff"}', headers={"content-type": "application/json"}
    )
    malformed = test_client.post(
        "/webhook/viso", content=b'{"label":', headers={"content-type": "application/json"}
    )
    assert invalid_utf8.status_code == 400
    assert malformed.status_code == 400


def test_webhook_bounds_body_and_nesting_but_preserves_empty_arrays(client):
    test_client, app_module = client
    too_large = b'{"padding":"' + (b"x" * app_module.MAX_WEBHOOK_BYTES) + b'"}'
    response = test_client.post("/webhook/viso", content=too_large, headers={"content-type": "application/json"})
    assert response.status_code == 413

    value = 0
    for _ in range(app_module.MAX_JSON_DEPTH + 1):
        value = [value]
    response = test_client.post("/webhook/viso", content=json.dumps(value))
    assert response.status_code == 400

    response = test_client.post("/webhook/viso", json=[])
    assert response.status_code == 200
    assert test_client.get("/api/events?limit=1").json()["latest"]["raw_payload"] == []


def test_confidence_percentages_normalize_and_out_of_range_becomes_unknown(client):
    test_client, _ = client
    assert test_client.post("/webhook/viso", json={"event_id": "pct", "confidence": 87}).status_code == 200
    assert test_client.post("/webhook/viso", json={"event_id": "high", "confidence": 101}).status_code == 200
    events = test_client.get("/api/events").json()["events"]
    assert events[0]["confidence"] is None
    assert events[1]["confidence"] == 0.87


def test_targets_schema_provenance_deduplication_and_absent_kinematics(client):
    test_client, _ = client
    first = {
        "event_id": "evt-old",
        "tracking_id": "track-7",
        "label": "drone",
        "confidence": 85,
        "state": "detected",
        "source": "viso-camera-2",
        "timestamp": "2026-09-10T10:00:00Z",
        "position": {"x": 0, "y": 0.75},
        "speed": 42,
        "heading": 180,
    }
    newest = dict(first, event_id="evt-new", confidence=0.93, state="restricted_zone", timestamp="2026-09-10T10:01:00Z")
    assert test_client.post("/webhook/viso", json=first).status_code == 200
    assert test_client.post("/webhook/viso", json=newest).status_code == 200
    assert test_client.post("/dev/simulate", json={"scenario": "restricted"}).status_code == 200

    response = test_client.get("/api/targets")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"schema_version", "targets", "received_at"}
    assert body["schema_version"] == 1
    assert len(body["targets"]) == 2

    real = next(target for target in body["targets"] if target["source_kind"] == "WEBHOOK_EVENT")
    assert {"target_id", "event_id", "source_kind", "status", "confidence", "position", "velocity",
            "heading", "source", "updated_at", "timestamp_basis", "last_received_at", "evidence",
            "alternative_interpretation", "uncertainty", "status_basis"} <= set(real)
    assert real["target_id"] == "track-7"
    assert real["event_id"] == "evt-new"
    assert real["status"] == "THREAT"
    assert real["status_basis"] == "reported_event"
    assert real["timestamp_basis"] == "reported_event_time"
    assert real["last_received_at"]
    assert real["confidence"] == 0.93 and math.isfinite(real["confidence"])
    assert real["position"] == {"x": 0.0, "y": 0.75, "coordinate_system": "normalized_frame"}
    assert real["velocity"] is None
    assert real["heading"] is None
    assert "hostile intent" in real["uncertainty"].lower()

    simulated = next(target for target in body["targets"] if target["source_kind"] == "SYNTHETIC_EVENT")
    assert simulated["status_basis"] == "scenario_authored"


def test_ambiguous_identity_and_position_are_not_inferred(client):
    test_client, _ = client
    payload = {
        "event_id": "event-fallback",
        "target_id": "one",
        "nested": {"target_id": "two", "position": {"x": 0.1, "y": 0.2}},
        "position": {"x": 0.3, "y": 0.4},
    }
    assert test_client.post("/webhook/viso", json=payload).status_code == 200
    target = test_client.get("/api/targets").json()["targets"][0]
    assert target["target_id"] == "event-fallback"
    assert target["position"] is None


def test_database_migration_adds_receipt_time_without_rewriting_existing_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL,
                received_at TEXT NOT NULL, detection_type TEXT, drone_detected INTEGER NOT NULL DEFAULT 0,
                confidence REAL, state TEXT NOT NULL DEFAULT 'UNKNOWN', severity TEXT NOT NULL DEFAULT 'INFO',
                source TEXT, media_url TEXT, raw_payload TEXT NOT NULL, is_simulated INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            """INSERT INTO incidents
               (event_id, received_at, raw_payload) VALUES (?, ?, ?)""",
            ("legacy-event", "2025-01-01T00:00:00+00:00", '{"label":"drone"}'),
        )

    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(db_path))
    import main as app_module
    importlib.reload(app_module)
    app_module.ensure_db()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(incidents)")}
        row = conn.execute("SELECT event_id, received_at, ingested_at, raw_payload FROM incidents").fetchone()
    assert "ingested_at" in columns
    assert row == ("legacy-event", "2025-01-01T00:00:00+00:00", None, '{"label":"drone"}')


def test_static_mount_cannot_escape_assets_and_legacy_is_scoped(client):
    test_client, app_module = client
    assert test_client.get("/assets/../main.py").status_code == 404
    assert test_client.get("/assets/%2e%2e/main.py").status_code == 404
    legacy = test_client.get("/legacy")
    assert legacy.status_code in {200, 404}
    if not (app_module.BASE_DIR / "legacy.html").exists():
        assert legacy.status_code == 404
