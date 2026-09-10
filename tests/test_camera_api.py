"""Camera evidence must be authenticated, durable, and visibly distinct from scene truth."""
import importlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def camera_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "incidents.db"))
    monkeypatch.setenv("DRONEWATCH_CAMERA_EVIDENCE_DB", str(tmp_path / "camera.sqlite3"))
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setenv("DRONEWATCH_CAMERA_MEDIA_DIR", str(media))
    monkeypatch.setenv("DRONEWATCH_WEBHOOK_SECRET", "camera-test-secret")
    monkeypatch.delenv("DRONEWATCH_CAMERA_FEED_STATE", raising=False)
    import main
    import dronewatch.api.camera as camera
    importlib.reload(main)
    with TestClient(main.app) as client:
        yield client, camera, media


def _post(client, payload):
    return client.post("/v2/webhook/viso", json=payload, headers={"X-DroneWatch-Token": "camera-test-secret"})


def test_unauthenticated_or_malformed_payloads_never_become_camera_results(camera_client):
    client, _, _ = camera_client
    payload = {"appId": "test", "incidentId": "incident", "summary": "Drone visible"}
    assert client.post("/v2/webhook/viso", json=payload).status_code == 401
    assert client.post("/v2/webhook/viso?token=wrong", json=payload).status_code == 401
    assert client.post("/v2/webhook/viso", content=b"invalid", headers={"X-DroneWatch-Token": "camera-test-secret"}).status_code == 400
    status = client.get("/api/camera/status").json()
    assert status["delivery_count"] == 0
    assert status["results"] == []


@pytest.mark.parametrize("payload", [{}, [], {"value": None}, {"nested": {"empty": []}}])
def test_connection_probes_are_receipts_but_never_detections(camera_client, payload):
    client, _, _ = camera_client
    assert _post(client, payload).status_code == 200
    status = client.get("/api/camera/status").json()
    assert status["delivery_count"] == status["probe_count"] == 1
    assert status["mapped_count"] == 0
    assert status["results"] == []


def test_mapped_receipts_preserve_sender_text_without_invented_boxes(camera_client):
    client, _, _ = camera_client
    payload = {
        "appId": "camera-app", "incidentId": "camera-incident",
        "summary": "No drone intrusion event emitted",
        "source_filename": "synthetic-camera.mp4",
        "detections": [{"label": "drone", "box": [0.1, 0.2, 0.3, 0.4]}],
    }
    assert _post(client, payload).status_code == 200
    status = client.get("/api/camera/status").json()
    assert status["mapped_count"] == 1
    result = status["results"][0]
    assert result["summary"] == payload["summary"]
    assert result["incident_reference"] == "camera-incident"
    assert result["source_filename"] == "synthetic-camera.mp4"
    assert result["boxes"] == []
    assert result["synthetic_sender"] is False
    assert "classification" not in result


def test_unknown_result_evidence_is_retained_privately_with_secrets_scrubbed(camera_client):
    client, camera, _ = camera_client
    payload = {"vendorReply": {"summary": "Result ready camera-test-secret", "modelAnswer": "unmapped actual content"}, "api_key": "private-value"}
    response = _post(client, payload)
    assert response.json()["outcome"] == "UNMAPPED"
    status = client.get("/api/camera/status").json()
    assert status["mapped_count"] == 0
    result = status["results"][0]
    assert result["summary"] == "Result ready [REDACTED]"
    assert result["source_filename"] is None
    assert "modelAnswer" not in json.dumps(status)
    with sqlite3.connect(camera.evidence_path()) as connection:
        evidence = connection.execute("SELECT evidence_json FROM camera_receipts").fetchone()[0]
    assert "unmapped actual content" in evidence
    assert "private-value" not in evidence
    assert "camera-test-secret" not in evidence


def test_restart_preserves_counts_and_history(camera_client):
    client, camera, _ = camera_client
    assert _post(client, {"appId": "app", "incidentId": "saved", "summary": "Saved result"}).status_code == 200
    before = client.get("/api/camera/status").json()
    importlib.reload(camera)
    after = camera.camera_status()
    assert after["results"] == before["results"]
    assert after["delivery_count"] == after["mapped_count"] == 1
    assert after["last_receipt_at"] == before["last_receipt_at"]


def test_explicit_synthetic_sender_does_not_count_as_a_real_mapped_result(camera_client):
    client, _, _ = camera_client
    assert _post(client, {"appId": "app", "incidentId": "fake", "synthetic": True, "summary": "Generated sender result"}).status_code == 200
    status = client.get("/api/camera/status").json()
    assert status["delivery_count"] == 1
    assert status["mapped_count"] == 0
    assert status["results"][0]["synthetic_sender"] is True


def test_media_supports_video_ranges_and_rejects_paths_private_files_and_symlinks(camera_client, tmp_path):
    client, _, media = camera_client
    (media / "clip.mp4").write_bytes(b"0123456789")
    (media / "clip.png").write_bytes(b"png-placeholder")
    (media / "secret.txt").write_text("never public")
    (tmp_path / "external.png").write_bytes(b"private external image")
    (media / "link.png").symlink_to(tmp_path / "external.png")
    status = client.get("/api/camera/status").json()
    assert [item["filename"] for item in status["media"]] == ["clip.mp4", "clip.png"]
    assert status["media"][0]["poster_url"] == "/api/camera/media/clip.png"
    assert status["results"] == []
    response = client.get("/api/camera/media/clip.mp4", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    for path in ("secret.txt", "link.png", "..%2Fexternal.png", "..%5Cexternal.png", "%00.png"):
        assert client.get("/api/camera/media/" + path).status_code == 404


def test_receipt_history_and_private_evidence_are_bounded(camera_client, monkeypatch):
    client, camera, _ = camera_client
    monkeypatch.setattr(camera, "MAX_RESULTS", 3)
    for i in range(5):
        assert _post(client, {"summary": str(i), "details": "x" * 70_000}).status_code == 200
    status = client.get("/api/camera/status").json()
    assert status["delivery_count"] == 5
    assert [result["summary"] for result in status["results"]] == ["4", "3", "2"]
    with sqlite3.connect(camera.evidence_path()) as connection:
        sizes = connection.execute("SELECT length(evidence_json) FROM camera_receipts").fetchall()
    assert len(sizes) == 3
    assert max(size[0] for size in sizes) <= camera.MAX_EVIDENCE_CHARS


def test_feed_manifest_exposes_only_safe_fields(camera_client, tmp_path, monkeypatch):
    client, _, _ = camera_client
    manifest = tmp_path / "feed.json"
    manifest.write_text(json.dumps({
        "transport": "GOOGLE_DRIVE", "folder_name": "DroneWatchIngest", "state": "submitted",
        "uploads": [{"filename": "clip.mp4", "drive_file_id": "drive-id", "uploaded_at": "now", "secret": "hidden"}],
        "message": "Awaiting processing", "token": "hidden",
    }))
    monkeypatch.setenv("DRONEWATCH_CAMERA_FEED_STATE", str(manifest))
    status = client.get("/api/camera/status").json()
    assert status["feed"]["state"] == "submitted"
    assert status["feed"]["uploads"][0]["filename"] == "clip.mp4"
    assert "hidden" not in json.dumps(status)
    assert status["results"] == []


def test_nonfinite_sender_numbers_do_not_break_receipt_capture(camera_client):
    client, camera, _ = camera_client
    response = client.post(
        "/v2/webhook/viso", content=b'{"summary":"Unknown numeric scale","score":NaN}',
        headers={"X-DroneWatch-Token": "camera-test-secret", "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    with sqlite3.connect(camera.evidence_path()) as connection:
        evidence = json.loads(connection.execute("SELECT evidence_json FROM camera_receipts").fetchone()[0])
    assert evidence["score"] is None
    assert client.get("/api/camera/status").json()["results"][0]["summary"] == "Unknown numeric scale"


def test_evidenced_label_schema_preserves_actual_labels_without_parsing_prose(camera_client):
    client, _, _ = camera_client
    _post(client, {"appId": "app", "incidentId": "labels", "summary": "Do not derive a missile class from this sentence",
                   "decision": "zone intrusion", "severity": "high",
                   "labels": [{"label": "drone", "confidence": 0.95, "approximate_position": "upper left",
                               "zone_state": "EXITED"}, {"label": "unknown scale", "confidence": 95}]})
    result = client.get("/api/camera/status").json()["results"][0]
    assert [item["label"] for item in result["labels"]] == ["drone", "unknown scale"]
    assert result["labels"][0]["confidence"] == 0.95
    assert result["labels"][0]["zone_state"] == "EXITED"
    assert result["labels"][1]["confidence"] is None
    assert result["boxes"] == []
    assert result["decision"] == "zone intrusion"


def _schematic_manifest(media):
    (media / "schematic.mp4").write_bytes(b"video")
    (media / "schematic.png").write_bytes(b"image")
    (media / "manifest.json").write_text(json.dumps({"clips": [{
        "file": "schematic.mp4", "still": "schematic.png", "scenario": "operator_demo",
        "seed": 42, "count": 6, "mode": "radar_off_30s_viso", "sim_start_s": 40,
        "sim_end_s": 70, "still_sim_time_s": 58, "frame": "LOCAL_SIM_METRES",
        "duration_seconds": 8,
        "entity_id": "must-not-leak", "true_class": "must-not-leak",
    }]}))


def test_preview_evidence_matches_filename_scenario_and_replay_time_without_future_leak(camera_client):
    client, _, media = camera_client
    _schematic_manifest(media)
    for filename in ("schematic.mp4", "schematic.png"):
        _post(client, {"appId": "app", "incidentId": filename, "fileName": filename, "labels": [{"label": "drone", "confidence": 0.9}]})
    base = "/api/preview/viso/evidence?name=operator_demo&seed=42&count=6&mode=radar_off_30s_viso&t="
    before = client.get(base + "57").json()
    assert before["results"] == [] and before["pending_count"] == 2
    snapshot = client.get(base + "58").json()
    assert [item["source_filename"] for item in snapshot["results"]] == ["schematic.png"]
    completed = client.get(base + "70").json()
    assert len(completed["results"]) == 2
    assert completed["position_updates"] is False
    assert "must-not-leak" not in json.dumps(completed)
    assert all(item["boxes"] == [] for item in completed["results"])
    wrong_seed = client.get(base.replace("seed=42", "seed=43") + "70").json()
    assert wrong_seed["results"] == []
    assert wrong_seed["uncorrelated_results"] == []


def test_media_contains_manifest_timing_for_synchronized_operator_playback(camera_client):
    client, _, media = camera_client
    _schematic_manifest(media)
    clips = client.get("/api/camera/status").json()["media"]
    video = next(item for item in clips if item["filename"] == "schematic.mp4")
    still = next(item for item in clips if item["filename"] == "schematic.png")
    assert video["scenario_context"]["sim_start_s"] == 40
    assert video["scenario_context"]["sim_end_s"] == 70
    assert video["scenario_context"]["duration_seconds"] == 8
    assert still["scenario_context"]["sim_start_s"] == 58
    assert still["scenario_context"]["duration_seconds"] == 0
    assert "must-not-leak" not in json.dumps(clips)


def test_unrelated_footage_is_explicitly_separate_from_operator_evidence(camera_client):
    client, _, media = camera_client
    _schematic_manifest(media)
    _post(client, {"appId": "app", "incidentId": "airport", "fileName": "clip-02.mp4", "labels": [{"label": "drone", "confidence": 0.95}]})
    _post(client, {"appId": "app", "incidentId": "fake", "synthetic": True, "fileName": "schematic.png"})
    _post(client, {"unmapped": True, "fileName": "schematic.png"})
    evidence = client.get("/api/preview/viso/evidence?t=90").json()
    assert evidence["results"] == []
    assert len(evidence["uncorrelated_results"]) == 1
    assert evidence["uncorrelated_results"][0]["source_filename"] == "clip-02.mp4"
    assert evidence["uncorrelated_results"][0]["scenario_context"] is None


def test_explicit_label_survives_bounded_private_evidence_truncation(camera_client):
    client, _, _ = camera_client
    payload = {"appId": "app", "incidentId": "large",
               "details": {str(i): "x" * 4000 for i in range(80)},
               "labels": [{"label": "drone", "confidence": 0.95}]}
    assert _post(client, payload).status_code == 200
    result = client.get("/api/camera/status").json()["results"][0]
    assert result["labels"][0]["label"] == "drone"
    assert result["labels"][0]["confidence"] == 0.95
