from dronewatch.domain import Detection, detections_from_event, normalized_box
from dronewatch.tracking import TrackManager, TrackerConfig


def detection(x=0.2, y=0.3, confidence=0.8, camera="cam-1"):
    return Detection("det", "VISO", camera, 0.0, "drone", confidence, (x, y, x + 0.04, y + 0.03))


def test_one_object_confirms_once_and_confidence_is_smoothed():
    manager = TrackManager()
    for index, score in enumerate([0.8, 0.9, 0.7, 1.0, 0.9]):
        manager.update("VISO", "cam-1", str(index), index * 0.2, [detection(0.2 + index * 0.008, confidence=score)])
    state = manager.snapshot()
    assert state["metrics"]["confirmed_sightings"] == 1
    assert len(state["tracks"]) == 1
    assert state["tracks"][0]["observations"] == 5
    assert state["tracks"][0]["state"] == "confirmed"
    assert state["tracks"][0]["smoothed_confidence"] != 0.9


def test_short_gap_preserves_track_id_and_lost_reacquires():
    manager = TrackManager()
    for i in range(3):
        manager.update("VISO", "cam-1", str(i), i * 0.2, [detection()])
    identity = manager.snapshot()["tracks"][0]["track_id"]
    manager.update("VISO", "cam-1", "gap", 0.8, [])
    manager.update("VISO", "cam-1", "back", 1.1, [detection()])
    assert manager.snapshot()["tracks"][0]["track_id"] == identity
    manager.tick(2.2)
    assert manager.snapshot()["tracks"][0]["state"] == "lost"
    manager.update("VISO", "cam-1", "back-again", 2.3, [detection()])
    assert manager.snapshot()["tracks"][0]["state"] == "confirmed"
    assert manager.confirmed_sightings == 1


def test_distant_object_and_different_camera_have_separate_tracks():
    manager = TrackManager()
    manager.update("VISO", "cam-1", "0", 0, [detection(), detection(0.8, 0.8)])
    manager.update("VISO", "cam-2", "0", 0, [detection(camera="cam-2")])
    assert len(manager.snapshot()["tracks"]) == 3


def test_lost_track_ends_and_reset_clears_transient_state():
    manager = TrackManager()
    manager.update("VISO", "cam-1", "0", 0, [detection()])
    manager.tick(1.1)
    assert manager.snapshot()["tracks"][0]["state"] == "lost"
    manager.tick(4.1)
    assert manager.snapshot()["tracks"] == []
    assert any(event["label"] == "TRACK LOST" for event in manager.lifecycle)
    manager.reset()
    assert manager.tracks == {} and manager.alerts == {} and manager.confirmed_sightings == 0


def test_confirmation_uses_recent_eligible_frames_and_duplicate_frame_is_ignored():
    manager = TrackManager(TrackerConfig(loss_timeout=10, end_timeout=20))
    for i in range(6):
        manager.update("VISO", "cam-1", str(i), i * 0.1, [detection()] if i in (0, 4, 5) else [])
    assert manager.confirmed_sightings == 0
    manager.update("VISO", "cam-1", "6", 0.6, [detection()])
    manager.update("VISO", "cam-1", "6", 0.6, [detection()])
    assert manager.confirmed_sightings == 1
    assert manager.snapshot()["tracks"][0]["observations"] == 4


def test_history_is_bounded_and_zone_alert_is_not_emitted_each_frame():
    manager = TrackManager(zones={"cam-1": [[0.1, 0.1], [0.6, 0.1], [0.6, 0.6], [0.1, 0.6]]})
    for i in range(30):
        manager.update("VISO", "cam-1", str(i), i * 0.1, [detection()])
    assert len(manager.snapshot()["tracks"][0]["centroid_history"]) == 20
    assert manager.snapshot()["metrics"]["open_warnings"] == 1
    assert sum(event["label"] == "ZONE ENTRY" for event in manager.lifecycle) == 1


def test_missing_bbox_keeps_real_viso_payload_as_sighting_only():
    event = {"id": 6, "source": "VISO", "received_at": "2026-09-03T18:40:53+00:00", "detection_type": "drone", "drone_detected": True,
             "raw_payload": {"appId": "sanitized", "incidentId": "sanitized", "labels": [{"label": "drone", "confidence": "high", "approximate_position": "center-right to right", "zone_state": "OUTSIDE"}]}}
    observations = detections_from_event(event)
    assert observations[0].bbox is None
    assert observations[0].confidence is None
    assert observations[0].confidence_label == "high"
    manager = TrackManager()
    manager.update("VISO", None, "6", observations[0].timestamp, observations)
    assert manager.snapshot()["tracks"] == []
    assert manager.confirmed_sightings == 0


def test_box_formats_require_real_dimensions_or_explicit_normalized_units():
    assert normalized_box({"bbox": [0, 0, 20, 20]}, 100, 100) is None
    assert normalized_box({"bbox": [0, 0, 20, 20], "bbox_format": "xyxy"}) is None
    assert normalized_box({"bbox": [0, 0, 20, 20], "bbox_format": "xyxy"}, 100, 100) == (0, 0, 0.2, 0.2)
    assert normalized_box({"bbox": [-1, 0, 20, 20], "bbox_format": "xyxy"}, 100, 100) is None
