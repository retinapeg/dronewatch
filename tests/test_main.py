import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "dronewatch_test.db"))
    monkeypatch.setenv("DRONEWATCH_SIMULATION", "1")
    import main as app_module
    importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        yield client, app_module


def test_health_endpoint(client):
    test_client, _ = client
    response = test_client.get('/health')
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "database_path" not in response.json()


def test_stored_simulation_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "dronewatch_default.db"))
    monkeypatch.delenv("DRONEWATCH_SIMULATION", raising=False)
    import main as app_module
    importlib.reload(app_module)

    with TestClient(app_module.app) as test_client:
        assert test_client.get('/api/config').json()["simulation_enabled"] is False
        response = test_client.post('/dev/simulate', json={"scenario": "detected"})
        assert response.status_code == 404


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
    # A nested list must not be stringified into a detection type. The old bug
    # stored the Python repr "[1, 2, {'foo': 'bar'}]" here.
    assert events["events"][0]["detection_type"] is None


def test_webhook_does_not_infer_detection_from_narrative_or_stringify_source(client):
    test_client, _ = client
    payload = {
        "appId": "demo-app",
        "incidentId": "demo-incident",
        "summary": "No DRONE_ZONE_INTRUSION event emitted",
        "source": {"connectionId": None},
    }

    response = test_client.post('/webhook/viso', json=payload)
    assert response.status_code == 200

    latest = test_client.get('/api/events?limit=1').json()["latest"]
    assert latest["drone_detected"] is False
    assert latest["state"] == "UNKNOWN"
    assert latest["source"] == "VISO"


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


# ---------------------------------------------------------------------------
# V0.1.1 regression hardening.
#
# These tests pin down behaviour that was previously untested. Tests whose name
# begins with `test_documents_` record what the code does TODAY, including
# behaviour we consider wrong. They exist so that a deliberate fix has to change
# a test on purpose rather than drifting silently. Each one names the concern.
# ---------------------------------------------------------------------------


def test_list_under_a_detection_key_is_not_stringified():
    """The stringify bug is only reachable under a detection-type key."""
    import main

    incident = main._normalize_incident({"label": [1, 2, {"foo": "bar"}]}, "VISO")
    assert incident["detection_type"] is None


def test_timestamp_parsing_accepts_iso_epoch_and_rejects_garbage():
    import main

    assert main.parse_timestamp("2026-09-09T14:00:00Z").startswith("2026-09-09T14:00:00")
    # A naive timestamp is assumed to be UTC.
    assert main.parse_timestamp("2026-09-09T14:00:00").endswith("+00:00")
    assert main.parse_timestamp(1757426400).startswith("2025-")
    # Values past the millisecond threshold are divided by 1000.
    assert main.parse_timestamp(1757426400000).startswith("2025-")
    # Unparseable input falls back to now rather than raising.
    assert main.parse_timestamp("ITM-0002").startswith("20")
    assert main.parse_timestamp(None).startswith("20")


def test_future_timestamps_are_clamped_to_now():
    """FIXED in V0.1.1. A sender cannot date an observation in the future.

    The claimed value is still preserved verbatim inside raw_payload, so no
    evidence is lost. V0.2 should separate arrival time from event time rather
    than overloading one column.
    """
    import main
    from datetime import datetime, timezone

    incident = main._normalize_incident(
        {"label": "drone", "timestamp": "2030-01-01T00:00:00Z"}, "VISO"
    )
    assert not incident["received_at"].startswith("2030")
    stored = datetime.fromisoformat(incident["received_at"])
    assert stored <= datetime.now(timezone.utc)
    # The original claim survives as evidence.
    assert incident["raw_payload"]["timestamp"] == "2030-01-01T00:00:00Z"


def test_past_timestamps_are_left_alone():
    import main

    incident = main._normalize_incident(
        {"label": "drone", "timestamp": "2026-01-01T00:00:00Z"}, "VISO"
    )
    assert incident["received_at"].startswith("2026-01-01T00:00:00")


def test_confidence_between_zero_and_one_is_preserved():
    import main

    assert main.coerce_float(0) == 0.0
    assert main.coerce_float(0.97) == 0.97
    assert main.coerce_float(1) == 1.0


def test_confidence_supplied_as_a_percentage_is_normalised():
    import main

    assert main.coerce_float(97) == 0.97
    assert main.coerce_float("97%") == 0.97
    assert main.coerce_float(100) == 1.0


def test_confidence_outside_sensible_range_becomes_unknown():
    """FIXED in V0.1.1. An out-of-range confidence reports unknown, not maximum.

    Clamping 150 to 1.0 would fabricate maximum confidence from malformed
    input, which is worse than admitting the value is uninterpretable.
    """
    import main

    assert main.coerce_float(150) is None
    assert main.coerce_float(-5) is None
    assert main.coerce_float(1000) is None
    assert main.coerce_float("150%") is None


def test_out_of_range_confidence_does_not_escalate_severity():
    import main

    incident = main._normalize_incident({"label": "drone", "confidence": 150}, "VISO")
    assert incident["confidence"] is None
    assert incident["state"] == "DETECTED"
    assert incident["severity"] == "INFO"


def test_restricted_zone_detection_escalates_severity_and_status(client):
    test_client, _ = client
    payload = {
        "event_id": "evt-restricted-1",
        "label": "drone",
        "confidence": 0.97,
        "state": "restricted_zone",
        "source": "camera-1",
    }

    assert test_client.post('/webhook/viso', json=payload).status_code == 200

    body = test_client.get('/api/events?limit=5').json()
    assert body["latest"]["severity"] == "HIGH"
    assert body["status"] == "CRITICAL"
    assert body["open_count"] == 1


def test_approaching_and_detected_states_escalate_below_critical(client):
    test_client, _ = client

    test_client.post('/webhook/viso', json={"label": "drone", "state": "approaching"})
    assert test_client.get('/api/events?limit=5').json()["status"] == "WARNING"

    test_client.post('/webhook/viso', json={"label": "drone", "state": "detected"})
    # The most severe open incident still governs the overall status.
    assert test_client.get('/api/events?limit=5').json()["status"] == "WARNING"


def test_exited_events_are_not_counted_as_open(client):
    test_client, _ = client
    test_client.post('/webhook/viso', json={"label": "drone", "state": "left"})

    body = test_client.get('/api/events?limit=5').json()
    assert body["latest"]["state"] == "EXITED"
    assert body["open_count"] == 0
    assert body["status"] == "SAFE"


def test_malformed_body_is_stored_but_is_not_an_open_incident(client):
    """FIXED in V0.1.1. Undecodable input no longer inflates the open count.

    The event is still stored and still visible in the event list, because
    UNKNOWN does not mean clear airspace. It simply is not counted as an open
    incident, since its state was never determined.
    """
    test_client, _ = client

    response = test_client.post(
        '/webhook/viso',
        content=b'this-is-not-json',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    body = test_client.get('/api/events?limit=5').json()
    latest = body["latest"]
    assert latest["state"] == "UNKNOWN"
    assert latest["raw_payload"]["_payload_decode_failed"] is True
    assert latest["raw_payload"]["raw_body"] == "this-is-not-json"
    # Still stored and still visible, but not counted as an incident.
    assert len(body["events"]) == 1
    assert body["open_count"] == 0
    assert body["status"] == "SAFE"


def test_empty_body_is_accepted_without_a_payload(client):
    test_client, _ = client

    response = test_client.post(
        '/webhook/viso', content=b'', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 200
    assert test_client.get('/api/events?limit=5').json()["latest"]["state"] == "UNKNOWN"


def test_events_limit_is_clamped_at_both_ends(client):
    test_client, app_module = client
    for index in range(205):
        app_module._write_incident(
            app_module._normalize_incident({"label": "drone", "event_id": f"evt-{index}"}, "VISO")
        )

    # Below the floor, one event is returned rather than zero or an error.
    assert len(test_client.get('/api/events?limit=0').json()["events"]) == 1
    assert len(test_client.get('/api/events?limit=-5').json()["events"]) == 1
    # Above the ceiling, the result is capped at 200.
    assert len(test_client.get('/api/events?limit=5000').json()["events"]) == 200
    assert len(test_client.get('/api/events?limit=20').json()["events"]) == 20


def test_events_limit_rejects_a_non_numeric_value(client):
    test_client, _ = client
    assert test_client.get('/api/events?limit=abc').status_code == 422
