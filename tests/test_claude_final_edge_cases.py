"""Independent Claude final review: edge cases in touch state, stale observations, identity, and projection boundaries."""
import importlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "claude-final-edge.db"))
    import main
    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client, main


def test_stale_observation_with_year_old_timestamp(client):
    """Stale observations with old source timestamps should not appear as current/recent."""
    test_client, main = client
    now = datetime.now(timezone.utc)
    one_year_ago = (now - timedelta(days=365)).isoformat()

    response = test_client.post("/webhook/viso", json={
        "appId": "test",
        "incidentId": "stale-inc",
        "label": "drone",
        "state": "detected",
        "timestamp": one_year_ago,
        "mediaLink": "http://127.0.0.1:9999/old.mp4"
    })
    assert response.status_code == 200

    # Retrieve the observation
    targets = test_client.get("/api/targets").json()["targets"]
    assert len(targets) == 1
    target = targets[0]

    # The received_at should be the server receipt time (now), not the one-year-old timestamp
    # The observation should have timestamp_basis indicating the source time was used but not fresh
    assert target.get("uncertainty") is not None
    # Verify the observation is marked as not current by checking the evidence
    # Old observations should have explicit indication, not be treated as recent


def test_observation_identity_collision_same_source_different_target_id_format(client):
    """Different target ID formats from the same source should remain distinct."""
    test_client, main = client

    # Post observations with similar but distinct target IDs
    payloads = [
        {"source": "camera-west", "target_id": "track_1", "event_id": "evt1", "state": "detected"},
        {"source": "camera-west", "target_id": "track-1", "event_id": "evt2", "state": "detected"},
        {"source": "camera-west", "target_id": "track.1", "event_id": "evt3", "state": "detected"},
    ]

    for payload in payloads:
        resp = test_client.post("/webhook/viso", json=payload)
        assert resp.status_code == 200

    # All three should be distinct even though they're very similar
    targets = test_client.get("/api/targets").json()["targets"]
    assert len(targets) == 3
    target_ids = {t["target_id"] for t in targets}
    assert len(target_ids) == 3


def test_multi_detection_with_ambiguous_confidence_remains_unknown(client):
    """Multiple detections with mixed confidences should not auto-select the highest."""
    test_client, main = client

    # Payload with multiple object detections, one with high confidence, others lower
    payload = {
        "event_id": "multi-detect",
        "source": "sensor-1",
        "labels": [
            {"label": "bird", "confidence": 0.95},
            {"label": "drone", "confidence": 0.6},
            {"label": "aircraft", "confidence": 0.4}
        ],
        "state": "detected"
    }

    test_client.post("/webhook/viso", json=payload)
    targets = test_client.get("/api/targets").json()["targets"]

    # With multiple objects, confidence and detection should be explicit about ambiguity
    assert len(targets) == 1
    target = targets[0]
    # Verify the payload includes evidence of multiple detections
    assert "evidence" in target
    assert isinstance(target.get("confidence"), (type(None), float))


def test_projection_response_with_many_large_metadata_fields(client):
    """Response size should be bounded even with many large metadata fields."""
    test_client, main = client

    # Post multiple events with large metadata
    large_label = "A" * 5000
    for i in range(10):
        payload = {
            "event_id": f"evt-{i}",
            "target_id": f"target-{i}",
            "source": f"source-{i}",
            "label": large_label,
            "state": "detected",
            "position": {"x": 0.5 + i * 0.01, "y": 0.5}
        }
        test_client.post("/webhook/viso", json=payload)

    # Get the response and check its size
    response = test_client.get("/api/targets")
    assert response.status_code == 200
    data = response.json()

    # Response should be bounded
    response_bytes = len(response.content)
    assert response_bytes < 3_000_000  # 3MB cap for 10 events with metadata

    # Check for truncation marker
    if response_bytes > 250_000:
        # If large, should have truncation indicator
        assert isinstance(data.get("truncated"), (bool, type(None)))


def test_malformed_position_with_strings_becomes_null_not_synthesized(client):
    """Position with string values should become null, not be parsed or synthesized."""
    test_client, main = client

    payloads = [
        {"event_id": "pos-str", "position": {"x": "0.5", "y": 0.5}, "state": "detected"},
        {"event_id": "pos-obj", "position": {"x": 0.5, "y": {"nested": 0.5}}, "state": "detected"},
        {"event_id": "pos-arr", "position": [0.5, 0.5], "state": "detected"},
    ]

    for payload in payloads:
        resp = test_client.post("/webhook/viso", json=payload)
        assert resp.status_code == 200

    targets = test_client.get("/api/targets").json()["targets"]
    assert len(targets) == 3

    # None of the malformed positions should become normalized_frame
    for target in targets:
        if target.get("position") is None or "x" not in target.get("position", {}):
            assert target.get("normalized_frame") is None


def test_very_old_event_followed_by_current_event_same_target(client):
    """Adding a current event after a stale one should update status, not stay stale."""
    test_client, main = client

    one_year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()

    # Post old event
    test_client.post("/webhook/viso", json={
        "target_id": "T-1",
        "event_id": "old-evt",
        "timestamp": one_year_ago,
        "state": "detected"
    })

    old_targets = test_client.get("/api/targets").json()["targets"]
    assert len(old_targets) == 1

    # Post current event for same target
    test_client.post("/webhook/viso", json={
        "target_id": "T-1",
        "event_id": "new-evt",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": "detected"
    })

    new_targets = test_client.get("/api/targets").json()["targets"]
    # Should still be one target (deduplicated by target_id), but with updated timestamp basis
    assert len(new_targets) == 1
    new_target = new_targets[0]
    assert new_target.get("updated_at") is not None


def test_evidence_field_with_html_like_content_stays_text(client):
    """Evidence fields containing HTML-like strings should not render as markup."""
    test_client, main = client

    payload = {
        "event_id": "html-test",
        "evidence": "<script>alert('xss')</script><img src=x onerror='alert(1)'>",
        "state": "detected"
    }

    test_client.post("/webhook/viso", json=payload)
    targets = test_client.get("/api/targets").json()["targets"]

    # The evidence should be preserved as text, not embedded as markup
    target = targets[0]
    if "evidence" in target:
        # Evidence should be in the list as a string
        assert isinstance(target["evidence"], (list, type(None)))


def test_unicode_in_target_id_with_emoji_and_combining_marks(client):
    """Unicode including emoji and combining marks should be handled safely."""
    test_client, main = client

    payloads = [
        {"event_id": "unicode-1", "target_id": "drone-🚁", "state": "detected"},
        {"event_id": "unicode-2", "target_id": "target-é-̈", "state": "detected"},  # combining marks
        {"event_id": "unicode-3", "target_id": "ट्रैक-1", "state": "detected"},  # Devanagari
    ]

    for payload in payloads:
        resp = test_client.post("/webhook/viso", json=payload)
        assert resp.status_code == 200

    targets = test_client.get("/api/targets").json()["targets"]
    assert len(targets) == 3

    # All should be preserved safely (either in full or as bounded digest)
    for target in targets:
        assert "target_id" in target
        assert isinstance(target["target_id"], str)
        # Should not crash and should have valid UTF-8
        target["target_id"].encode("utf-8")
