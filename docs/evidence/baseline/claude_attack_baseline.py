"""Independent adversarial probes for the DroneWatch ingestion and events API.

Every test asserts the *desired* behaviour. Tests that fail against the
31a32e1 baseline carry ``xfail(strict=True)``: pytest reports them as XFAIL
today and as XPASS (a hard failure) once the defect is fixed, at which point
the marker must be removed. Tests without a marker pass today and guard
behaviour that must not regress.

Run from the repository root with an isolated database (the fixture uses
``tmp_path``; nothing here touches a live server):

    ../dronewatch/.venv/bin/python -m pytest -q tests/claude_attack_test.py -rxX
"""
from __future__ import annotations

import importlib
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

JSON = {"content-type": "application/json"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "attack.db"))
    monkeypatch.setenv("DRONEWATCH_SIMULATION", "0")
    import main as app_module

    importlib.reload(app_module)
    # raise_server_exceptions=False so a 500 is observed as a status code
    # rather than an exception inside the test process.
    with TestClient(app_module.app, raise_server_exceptions=False) as test_client:
        yield test_client, app_module


def post_raw(test_client, body: bytes):
    return test_client.post("/webhook/viso", content=body, headers=JSON)


def latest(test_client):
    return test_client.get("/api/events?limit=1").json()["latest"]


# ---------------------------------------------------------------------------
# A. Persistent read-path poisoning
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="depth-300 payload is accepted on write and then breaks GET /api/events for every reader (pydantic depth limit on serialisation)")
def test_moderately_nested_payload_must_not_poison_the_events_api(client):
    test_client, _ = client
    body = ("[" * 300 + "]" * 300).encode()
    write = post_raw(test_client, body)
    assert write.status_code in {200, 400, 413, 422}
    read = test_client.get("/api/events")
    assert read.status_code == 200, "a single accepted webhook must never make the events feed unreadable"


@pytest.mark.xfail(strict=True, reason="100k-deep body returns 500 (RecursionError inside json.loads) instead of a 4xx")
def test_very_deep_payload_is_rejected_not_500(client):
    test_client, _ = client
    body = ("[" * 100_000 + "]" * 100_000).encode()
    response = post_raw(test_client, body)
    assert response.status_code in {400, 413, 422}


@pytest.mark.xfail(strict=True, reason="invalid UTF-8 body raises UnicodeDecodeError -> 500 (main.py:420 only catches JSONDecodeError)")
def test_invalid_utf8_body_is_rejected_with_4xx(client):
    test_client, _ = client
    response = post_raw(test_client, b"\xff\xfe{\"label\":\"drone\"}")
    assert 400 <= response.status_code < 500


# ---------------------------------------------------------------------------
# B. Non-finite and out-of-range confidence
# ---------------------------------------------------------------------------


def test_non_finite_confidence_does_not_crash_events_api_on_pinned_stack(client):
    """Codex's task text claims 1e400/NaN cause a later API JSON failure.
    On the pinned stack (fastapi 0.141.1, pydantic 2.13.5) the `Dict[str, Any]`
    return annotation makes pydantic serialise inf/nan as null, so the read
    path survives. This guards that observation; if it starts failing the
    projection must add a read-side sanitiser."""
    test_client, _ = client
    assert post_raw(test_client, b'{"label":"drone","confidence":1e400}').status_code == 200
    assert post_raw(test_client, b'{"label":"drone","confidence":NaN}').status_code == 200
    response = test_client.get("/api/events")
    assert response.status_code == 200
    for event in response.json()["events"]:
        assert event["confidence"] is None


@pytest.mark.xfail(strict=True, reason="infinite confidence is stored and drives severity WARNING via `confidence >= 0.85` (main.py:230)")
def test_infinite_confidence_must_not_raise_severity(client):
    test_client, app_module = client
    assert post_raw(test_client, b'{"label":"drone","confidence":1e400}').status_code == 200
    with sqlite3.connect(app_module.DB_PATH) as conn:
        stored_confidence, severity = conn.execute("SELECT confidence, severity FROM incidents").fetchone()
    assert stored_confidence is None or math.isfinite(stored_confidence)
    assert severity == "INFO"


@pytest.mark.xfail(strict=True, reason="coerce_float keeps 150 and -0.5 and rescales 1.5 to 0.015 (main.py:121-123)")
def test_out_of_range_confidence_becomes_null_not_warning(client):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"label": "drone", "confidence": 150})
    over = latest(test_client)
    assert over["confidence"] is None
    assert over["severity"] == "INFO"
    test_client.post("/webhook/viso", json={"label": "drone", "confidence": -0.5})
    assert latest(test_client)["confidence"] is None
    test_client.post("/webhook/viso", json={"label": "drone", "confidence": 1.5})
    assert latest(test_client)["confidence"] in (None, 1.0), "1.5 must not silently become 1.5%"


# ---------------------------------------------------------------------------
# C. State semantics: negation and precedence
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="substring matching in _normalize_state (main.py:203-220) inverts negated or cleared states")
@pytest.mark.parametrize(
    "reported, forbidden",
    [
        ("no_drone_detected", "DETECTED"),
        ("undetected", "DETECTED"),
        ("DRONE_ZONE_INTRUSION_CLEARED", "DETECTED"),
        ("not approaching", "APPROACHING"),
        ("exited_restricted_zone", "RESTRICTED_ZONE"),
        ("left restricted zone", "RESTRICTED_ZONE"),
    ],
)
def test_negated_or_cleared_states_never_raise_alert_level(client, reported, forbidden):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"state": reported})
    payload = test_client.get("/api/events?limit=1").json()
    assert payload["latest"]["state"] != forbidden
    assert payload["status"] not in {"CRITICAL"} or reported.startswith("restricted")


@pytest.mark.xfail(strict=True, reason="token matching in find_first (main.py:86-99) lets unrelated keys such as http_status supply the state")
def test_unrelated_status_key_does_not_supply_zone_state(client):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"http_status": "restricted", "label": "bird"})
    assert latest(test_client)["state"] != "RESTRICTED_ZONE"


# ---------------------------------------------------------------------------
# D. Provenance corruption through key-token capture
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="event_id candidate list contains bare 'id'; camera_id earlier in dict order wins (main.py:238-243)")
def test_explicit_event_id_wins_over_camera_id(client):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"camera_id": "cam-7", "event_id": "evt-1", "label": "drone"})
    assert latest(test_client)["event_id"] == "evt-1"


@pytest.mark.xfail(strict=True, reason="'time' token captures processing_time_ms -> received_at 1970-01-01T00:00:42 (main.py:199)")
def test_processing_time_field_does_not_become_event_time(client):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"processing_time_ms": 42, "label": "drone", "timestamp": "2026-09-10T10:00:00Z"})
    assert latest(test_client)["received_at"].startswith("2026-09-10T10:00:00")


@pytest.mark.xfail(strict=True, reason="'url' token captures callback_url as media_url (main.py:195)")
def test_callback_url_is_not_treated_as_media(client):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"callback_url": "https://evil.example/beacon", "label": "drone"})
    assert latest(test_client)["media_url"] is None


@pytest.mark.xfail(strict=True, reason="first list element wins: bird@0.2 shadows drone@0.99 in a labels array (main.py:79-99)")
def test_multi_label_payload_prefers_drone_detection(client):
    test_client, _ = client
    test_client.post(
        "/webhook/viso",
        json={"labels": [{"label": "bird", "confidence": 0.2}, {"label": "drone", "confidence": 0.99}]},
    )
    event = latest(test_client)
    assert event["drone_detected"] is True
    assert event["detection_type"] == "drone"


# ---------------------------------------------------------------------------
# E. Sender-controlled time and freshness
# ---------------------------------------------------------------------------


def _iso_timestamps(mapping):
    for key, value in mapping.items():
        if key == "raw_payload" or not isinstance(value, str):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        yield key, parsed


@pytest.mark.xfail(strict=True, reason="received_at stores the sender's timestamp; no field records the server receipt time (main.py:198-200, 277)")
def test_server_receipt_time_is_recorded_independently_of_sender_timestamp(client):
    """Field-agnostic: any top-level ISO timestamp on the event within 5 s of
    wall clock satisfies this, whatever the column is called."""
    test_client, _ = client
    future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    test_client.post("/webhook/viso", json={"timestamp": future, "label": "drone"})
    event = latest(test_client)
    now = datetime.now(timezone.utc)
    server_times = [key for key, parsed in _iso_timestamps(event) if abs(parsed - now) < timedelta(seconds=5)]
    assert server_times, f"no server receipt time on the event; timestamps present: {dict(_iso_timestamps(event))}"


def test_unparseable_timestamp_is_replaced_silently(client):
    """Documents current behaviour: garbage timestamps become 'now' with no flag."""
    test_client, _ = client
    test_client.post("/webhook/viso", json={"timestamp": "garbage", "label": "drone"})
    event = latest(test_client)
    assert abs(datetime.fromisoformat(event["received_at"]) - datetime.now(timezone.utc)) < timedelta(seconds=5)
    # nothing in the row records that the reported time was discarded
    assert "timestamp_invalid" not in event


# ---------------------------------------------------------------------------
# F. Idempotency and status window
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="no idempotency: three deliveries of the same event_id create three open incidents")
def test_redelivered_event_is_not_counted_three_times(client):
    test_client, _ = client
    for _ in range(3):
        test_client.post("/webhook/viso", json={"event_id": "evt-dup", "label": "drone", "state": "detected"})
    payload = test_client.get("/api/events").json()
    assert payload["open_count"] == 1


@pytest.mark.xfail(strict=True, reason="status is computed over the last `limit` rows only, so limit=1 and limit=200 disagree (main.py:391-401)")
def test_airspace_status_is_independent_of_page_size(client):
    test_client, _ = client
    test_client.post("/webhook/viso", json={"state": "detected", "label": "drone", "event_id": "a"})
    for i in range(5):
        test_client.post("/webhook/viso", json={"state": "exited", "label": "drone", "event_id": f"x{i}"})
    assert test_client.get("/api/events?limit=1").json()["status"] == test_client.get("/api/events?limit=200").json()["status"]


# ---------------------------------------------------------------------------
# G. Malformed bodies are stored as VISO events
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="non-JSON bodies are stored as source=VISO events and flip the dashboard WEBHOOK RECEIVED indicator")
def test_non_json_body_is_not_stored_as_a_viso_event(client):
    test_client, _ = client
    response = test_client.post("/webhook/viso", content=b"hello world")
    assert 400 <= response.status_code < 500
    assert test_client.get("/api/events").json()["events"] == []


def test_valid_empty_and_list_json_still_acknowledged(client):
    """Guard for Codex's 4xx proposal: empty-object and array JSON (the shapes
    Codex committed to preserving) must stay 2xx. Scalars are deliberately not
    asserted here; see the baseline report."""
    test_client, _ = client
    assert test_client.post("/webhook/viso", json={}).status_code == 200
    assert test_client.post("/webhook/viso", json=[{"state": "restricted"}]).status_code == 200
    assert len(test_client.get("/api/events").json()["events"]) == 2


# ---------------------------------------------------------------------------
# H. Payload volume served to the polling dashboard
# ---------------------------------------------------------------------------


def test_legacy_events_feed_duplicates_every_event(client):
    """Documents the cost driver: /api/events returns each row in `events` and
    again in `open_incidents`. The legacy contract is preserved by decision,
    so this is a measurement, not an xfail."""
    test_client, _ = client
    for _ in range(50):
        test_client.post("/webhook/viso", json={"label": "drone", "state": "detected", "frame": "y" * 50_000})
    response = test_client.get("/api/events?limit=200")
    assert response.status_code == 200
    body = response.json()
    assert body["events"][0] == body["open_incidents"][0]
    assert len(response.content) > 5_000_000


def test_targets_projection_is_bounded_for_mobile_polling(client):
    """Acceptance criterion for the canonical projection: with 50 stored
    events of 50 KB the list must stay under 1 MB and must not embed raw
    payloads. Skips until the route exists."""
    test_client, _ = client
    for _ in range(50):
        test_client.post("/webhook/viso", json={"label": "drone", "state": "detected", "frame": "y" * 50_000})
    response = test_client.get("/api/targets")
    if response.status_code == 404:
        pytest.skip("/api/targets not present in this tree yet")
    assert response.status_code == 200
    assert len(response.content) < 1_000_000, f"{len(response.content)} bytes per poll"
    assert "raw_payload" not in response.json().get("targets", [{}])[0]
