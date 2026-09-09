"""V0.2 preview API and Viso ingestion contracts.

The properties that matter most here are negative ones: ground truth must not
reach a browser, synthetic playback must not touch the database or the Viso
connection state, and unauthenticated external ingestion must be impossible.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
SECRET = "test-secret-value"


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """A client with an isolated database and no webhook secret configured."""
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "preview_test.db"))
    monkeypatch.delenv("DRONEWATCH_WEBHOOK_SECRET", raising=False)
    import main as app_module
    import dronewatch.api.preview as preview_module
    importlib.reload(app_module)
    importlib.reload(preview_module)
    # Reloading main rebuilds the app; re-mount the reloaded router.
    app_module.app.include_router(preview_module.router)
    preview_module.STATUS.reset()
    preview_module.QUARANTINE.clear()
    preview_module._CACHE.clear()
    with TestClient(app_module.app) as client:
        yield client, app_module, preview_module


@pytest.fixture
def secured_client(app_client, monkeypatch):
    _, _, preview_module = app_client
    monkeypatch.setenv("DRONEWATCH_WEBHOOK_SECRET", SECRET)
    preview_module.STATUS.reset()
    return app_client


# --- the preview page and scenario listing ---------------------------------

def test_preview_page_is_served_and_the_v1_dashboard_is_untouched(app_client):
    client, _, _ = app_client
    preview = client.get("/preview")
    assert preview.status_code == 200
    assert "DroneWatch Operator Preview" in preview.text
    assert "SIMULATION" in preview.text

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert dashboard.text == (REPO_ROOT / "index.html").read_text(encoding="utf-8")


def test_index_html_is_byte_identical_to_the_committed_version():
    committed = subprocess.run(
        ["git", "show", "HEAD:index.html"], cwd=REPO_ROOT,
        capture_output=True, check=True,
    ).stdout
    assert (REPO_ROOT / "index.html").read_bytes() == committed


def test_featured_scenarios_are_all_real_registry_entries(app_client):
    client, _, _ = app_client
    body = client.get("/api/preview/scenarios").json()
    from dronewatch.synthetic.scenarios import SCENARIO_NAMES

    assert body["default"] == {"scenario": "mixed_threat_decoy", "seed": 42}
    for name in ("mixed_threat_decoy", "sensor_disagreement", "sensor_dropout",
                 "delayed_out_of_order", "single_threat", "small_swarm"):
        assert name in body["featured"]
        assert name in SCENARIO_NAMES


# --- playback ordering ------------------------------------------------------

def test_observations_are_returned_in_stable_delivery_order(app_client):
    client, _, _ = app_client
    body = client.get("/api/preview/scenario?name=delayed_out_of_order&seed=42").json()
    keys = [(o["received_at"], o["observation_id"]) for o in body["observations"]]
    assert keys == sorted(keys)

    again = client.get("/api/preview/scenario?name=delayed_out_of_order&seed=42").json()
    assert [o["observation_id"] for o in again["observations"]] == [
        o["observation_id"] for o in body["observations"]
    ]


def test_observed_and_received_times_are_both_preserved(app_client):
    client, _, _ = app_client
    body = client.get("/api/preview/scenario?name=delayed_out_of_order&seed=42").json()
    assert any(o["received_at"] > o["observed_at"] for o in body["observations"])
    assert all(o["transport_delay_s"] >= 0 for o in body["observations"])
    # Simulation time is exposed so the UI never has to compare with wall-clock.
    assert all("sim_time_s" in o for o in body["observations"])


# --- ground-truth exclusion -------------------------------------------------

FORBIDDEN = ("true_class", "true_control_mode", "control_mode", "entity_id",
             "ground_truth", "provenance", "intent", "gt-")


@pytest.mark.parametrize("scenario", [
    "mixed_threat_decoy", "sensor_disagreement", "sensor_dropout",
    "delayed_out_of_order", "single_threat", "small_swarm",
])
def test_no_preview_response_contains_ground_truth(app_client, scenario):
    client, _, _ = app_client
    raw = client.get(f"/api/preview/scenario?name={scenario}&seed=42").text.lower()
    for token in FORBIDDEN:
        assert token not in raw, f"{token} leaked into the {scenario} response"


def test_preview_uses_the_observations_only_accessor(app_client):
    """A structural check: the API module must not import generate_scenario."""
    source = (REPO_ROOT / "dronewatch" / "api" / "preview.py").read_text()
    assert "observations_only" in source
    assert "import generate_scenario" not in source
    assert "ScenarioGroundTruth" not in source


def test_m1_import_guard_still_passes():
    from tests.test_domain import (  # noqa: F401
        test_invariant_9_ground_truth_never_reaches_evaluated_modules as guard,
    )
    guard()


# --- coordinate honesty -----------------------------------------------------

def test_positions_use_a_local_simulation_frame_not_geography(app_client):
    client, _, _ = app_client
    response = client.get("/api/preview/scenario?name=mixed_threat_decoy&seed=42")
    raw = response.text
    for token in ("latitude", "longitude", "altitude_m"):
        assert token not in raw, f"{token} must not appear in a preview response"

    body = response.json()
    assert body["frame"] == "LOCAL_SIM_METRES"
    spatial = [o for o in body["observations"] if o["position"] is not None]
    assert spatial, "expected some spatial observations"
    for observation in spatial:
        position = observation["position"]
        assert position["frame"] == "LOCAL_SIM_METRES"
        assert set(position) == {"frame", "x", "y", "z"}


def test_rf_and_acoustic_keep_their_synthetic_positions(app_client):
    """M2 gives these modalities noisy positions; they belong on the map."""
    client, _, _ = app_client
    body = client.get("/api/preview/scenario?name=mixed_threat_decoy&seed=42").json()
    for modality in ("RF", "ACOUSTIC"):
        located = [
            o for o in body["observations"]
            if o["modality"] == modality and o["position"] is not None
        ]
        assert located, f"{modality} observations should carry a position"


def test_counts_of_spatial_and_non_spatial_observations_agree(app_client):
    client, _, _ = app_client
    body = client.get("/api/preview/scenario?name=mixed_threat_decoy&seed=42").json()
    spatial = sum(1 for o in body["observations"] if o["position"] is not None)
    assert body["spatial_observation_count"] == spatial
    assert body["non_spatial_observation_count"] == len(body["observations"]) - spatial


# --- bounded execution ------------------------------------------------------

def test_scenario_requests_are_bounded(app_client):
    client, _, _ = app_client
    assert client.get("/api/preview/scenario?name=small_swarm&seed=42&count=500").status_code == 422
    assert client.get("/api/preview/scenario?name=mixed_threat_decoy&seed=42&duration_s=9000").status_code == 422
    assert client.get("/api/preview/scenario?name=mixed_threat_decoy&seed=-1").status_code == 422
    assert client.get("/api/preview/scenario?name=not_a_scenario&seed=42").status_code == 404


def test_swarm_size_is_honoured_within_bounds(app_client):
    client, _, _ = app_client
    body = client.get("/api/preview/scenario?name=small_swarm&seed=42&count=3&duration_s=40").json()
    assert body["observation_count"] > 0
    assert body["count"] == 3


# --- database isolation -----------------------------------------------------

def _incident_count(app_module) -> int:
    connection = sqlite3.connect(app_module.DB_PATH)
    try:
        return connection.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    finally:
        connection.close()


def test_synthetic_playback_never_writes_to_the_incident_database(app_client):
    client, app_module, _ = app_client
    before = _incident_count(app_module)
    client.get("/api/preview/scenarios")
    for scenario in ("mixed_threat_decoy", "sensor_dropout", "small_swarm"):
        client.get(f"/api/preview/scenario?name={scenario}&seed=42")
    client.get("/api/preview/viso/status")
    assert _incident_count(app_module) == before == 0


# --- Viso connection state --------------------------------------------------

def test_status_reports_not_configured_without_a_secret(app_client):
    client, _, _ = app_client
    body = client.get("/api/preview/viso/status").json()
    assert body["state"] == "NOT CONFIGURED"
    assert body["configured"] is False
    assert body["webhook_path"] == "/v2/webhook/viso"


def test_external_ingestion_is_disabled_without_a_secret(app_client):
    client, _, _ = app_client
    response = client.post("/v2/webhook/viso", json={"appId": "a", "incidentId": "i"})
    assert response.status_code == 503
    assert client.get("/api/preview/viso/status").json()["state"] == "NOT CONFIGURED"


def test_the_synthetic_preview_still_works_without_a_secret(app_client):
    client, _, _ = app_client
    assert client.get("/preview").status_code == 200
    assert client.get("/api/preview/scenario?name=single_threat&seed=42").status_code == 200


def test_a_missing_or_wrong_token_is_rejected(secured_client):
    client, _, _ = secured_client
    payload = {"appId": "a", "incidentId": "i"}
    assert client.post("/v2/webhook/viso", json=payload).status_code == 401
    assert client.post(
        "/v2/webhook/viso", json=payload, headers={"X-DroneWatch-Token": "wrong"}
    ).status_code == 401


def test_a_valid_delivery_is_mapped_and_reported(secured_client):
    client, app_module, _ = secured_client
    response = client.post(
        "/v2/webhook/viso",
        json={"appId": "demo-app", "incidentId": "demo-incident"},
        headers={"X-DroneWatch-Token": SECRET},
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "MAPPED"

    status = client.get("/api/preview/viso/status").json()
    assert status["state"] == "VALID DELIVERY RECEIVED"
    assert status["mapped_count"] == 1
    assert status["last_receipt_at"] is not None
    # A genuine delivery reaches the V0.1 store, as it would have in V0.1.
    assert _incident_count(app_module) == 1


def test_a_url_query_token_is_accepted(secured_client):
    client, _, _ = secured_client
    response = client.post(
        f"/v2/webhook/viso?token={SECRET}",
        json={"incidentUrl": "https://now.viso.ai/incidents/7"},
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "MAPPED"


def test_an_unknown_payload_is_quarantined_not_turned_into_a_detection(secured_client):
    client, app_module, _ = secured_client
    response = client.post(
        "/v2/webhook/viso", json={"something": "unexpected", "value": 3},
        headers={"X-DroneWatch-Token": SECRET},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "quarantined"

    status = client.get("/api/preview/viso/status").json()
    assert status["state"] == "UNMAPPED PAYLOAD"
    assert status["unmapped_count"] == 1
    assert _incident_count(app_module) == 0, "an unmapped payload must not be stored"


def test_narrative_text_never_produces_a_positive_result(secured_client):
    client, app_module, _ = secured_client
    response = client.post(
        "/v2/webhook/viso",
        json={"summary": "No drone intrusion event emitted", "note": "drone drone drone"},
        headers={"X-DroneWatch-Token": SECRET},
    )
    assert response.json()["outcome"] == "UNMAPPED"
    assert _incident_count(app_module) == 0


def test_missing_times_and_positions_remain_unknown(secured_client):
    from datetime import datetime, timezone
    from dronewatch.ingest.viso import adapt

    delivery = adapt(
        {"appId": "a", "incidentId": "i"},
        received_at=datetime.now(timezone.utc), delivery_id="x",
    )
    assert delivery.observation.position is None
    assert delivery.observed_at_supplied is False
    assert delivery.observation.raw["observed_at_supplied"] is False
    assert delivery.observation.confidence is None
    # No classification is inferred from a delivery: all mass stays on UNKNOWN.
    from dronewatch.domain.enums import ObjectClass

    distribution = delivery.observation.classification
    assert distribution.probability(ObjectClass.UNKNOWN) == 1.0
    assert distribution.probability(ObjectClass.THREAT) == 0.0


def test_an_oversized_body_is_refused(secured_client, monkeypatch):
    client, _, preview_module = secured_client
    monkeypatch.setattr(preview_module, "MAX_BODY_BYTES", 512)
    response = client.post(
        "/v2/webhook/viso", content=b"x" * 4096,
        headers={"X-DroneWatch-Token": SECRET, "Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_undecodable_body_is_an_error_not_a_detection(secured_client):
    client, app_module, _ = secured_client
    response = client.post(
        "/v2/webhook/viso", content=b"this-is-not-json",
        headers={"X-DroneWatch-Token": SECRET, "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert client.get("/api/preview/viso/status").json()["state"] == "ERROR"
    assert _incident_count(app_module) == 0


def test_the_secret_is_never_echoed_to_a_browser(secured_client):
    client, _, _ = secured_client
    client.post("/v2/webhook/viso", json={"appId": "a", "incidentId": "i", "token": SECRET},
                headers={"X-DroneWatch-Token": SECRET})
    body = client.get("/api/preview/viso/status").text
    assert SECRET not in body


def test_raw_payload_values_are_never_returned_to_a_browser(secured_client):
    client, _, _ = secured_client
    client.post(
        "/v2/webhook/viso",
        json={"siteName": "SECRET-SITE-NAME", "mediaLink": "https://private/video.mp4"},
        headers={"X-DroneWatch-Token": SECRET},
    )
    body = client.get("/api/preview/viso/status").text
    assert "SECRET-SITE-NAME" not in body
    assert "private/video.mp4" not in body
    # Key names are allowed, so the operator can see the shape that arrived.
    assert "siteName" in body


# --- the legacy route and synthetic data cannot fake a connection ----------

def test_legacy_webhook_keeps_its_v1_behaviour(app_client):
    client, app_module, _ = app_client
    response = client.post("/webhook/viso", json={"label": "drone", "confidence": 0.9})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert _incident_count(app_module) == 1


def test_legacy_webhook_and_simulation_never_make_viso_appear_connected(secured_client):
    client, _, _ = secured_client
    client.post("/webhook/viso", json={"appId": "a", "incidentId": "i"})
    client.get("/api/preview/scenario?name=mixed_threat_decoy&seed=42")

    status = client.get("/api/preview/viso/status").json()
    assert status["state"] == "WAITING FOR DELIVERY"
    assert status["delivery_count"] == 0


# --- hardening -------------------------------------------------------------

def test_a_url_token_is_redacted_from_the_access_log():
    """Uvicorn logs the query string, so a URL token must never reach the log."""
    import logging
    from dronewatch.api.preview import _RedactToken

    record = logging.LogRecord(
        name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
        msg='%s - "%s %s HTTP/1.1" %d',
        args=("127.0.0.1:5000", "POST", "/v2/webhook/viso?token=super-secret-value", 200),
        exc_info=None,
    )
    assert _RedactToken().filter(record) is True
    message = record.getMessage()
    assert "super-secret-value" not in message
    assert "token=REDACTED" in message
    # The rest of the request line survives so the log stays useful.
    assert "/v2/webhook/viso" in message and "200" in message


def test_the_access_log_filter_is_attached_at_import():
    import logging
    from dronewatch.api.preview import _RedactToken

    filters = logging.getLogger("uvicorn.access").filters
    assert any(isinstance(f, _RedactToken) for f in filters)


def test_a_log_line_without_a_token_is_left_alone():
    import logging
    from dronewatch.api.preview import _RedactToken

    record = logging.LogRecord(
        name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
        msg='%s - "%s %s HTTP/1.1" %d',
        args=("127.0.0.1:5000", "GET", "/preview", 200), exc_info=None,
    )
    _RedactToken().filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "GET /preview HTTP/1.1" 200'


def test_a_non_ascii_token_is_rejected_without_raising(secured_client):
    """A query token can carry non-ASCII; comparing it must 401, not crash.

    HTTP headers are latin-1 only, so the query string is the reachable path
    for this. hmac.compare_digest raises TypeError on non-ASCII str input,
    which would surface as an unhandled 500.
    """
    client, _, _ = secured_client
    response = client.post(
        "/v2/webhook/viso?token=t%C3%B6k%C3%A9n-with-accents",
        json={"appId": "a", "incidentId": "i"},
    )
    assert response.status_code == 401


def test_the_scenario_cache_is_bounded(app_client):
    client, _, preview_module = app_client
    for seed in range(preview_module.MAX_CACHED_SCENARIOS + 6):
        client.get(f"/api/preview/scenario?name=single_threat&seed={seed}&duration_s=20")
    assert len(preview_module._CACHE) <= preview_module.MAX_CACHED_SCENARIOS


def test_manual_simulation_requests_never_make_viso_appear_connected(secured_client, monkeypatch):
    """`/dev/simulate` is a manual test path; it must not touch the connection."""
    client, app_module, _ = secured_client
    monkeypatch.setenv("DRONEWATCH_SIMULATION", "1")
    importlib.reload(app_module)
    import dronewatch.api.preview as preview_module
    app_module.app.include_router(preview_module.router)

    with TestClient(app_module.app) as simulation_client:
        assert simulation_client.post(
            "/dev/simulate", json={"scenario": "detected"}
        ).status_code == 200
        status = simulation_client.get("/api/preview/viso/status").json()
        assert status["delivery_count"] == 0
        assert status["state"] != "VALID DELIVERY RECEIVED"


# --- operator track view ---------------------------------------------------

OPERATOR_FORBIDDEN = ("true_class", "true_control_mode", "control_mode", "entity_id",
                      "ground_truth", "provenance", "intent", "gt-contact",
                      "latitude", "longitude")


def test_operator_preview_page_is_served(app_client):
    client, _, _ = app_client
    page = client.get("/preview")
    assert page.status_code == 200
    assert "DroneWatch Operator Preview" in page.text
    assert "SIMULATION" in page.text


def test_the_raw_observation_viewer_moved_to_diagnostics(app_client):
    """The research view is preserved, not deleted."""
    client, _, _ = app_client
    page = client.get("/preview/diagnostics")
    assert page.status_code == 200
    assert "DroneWatch Diagnostics" in page.text
    # And it still serves the observation API it depends on.
    assert client.get("/api/preview/scenario?name=mixed_threat_decoy&seed=42").status_code == 200


@pytest.mark.parametrize("count", [3, 6, 10])
def test_track_timeline_confirms_one_track_per_configured_entity(app_client, count):
    client, _, _ = app_client
    body = client.get(f"/api/preview/tracks?name=operator_demo&seed=42&count={count}").json()
    assert body["configured_entities"] == count
    assert body["tracks_confirmed"] == count, "tracker should not fragment on the demo"

    settled = [f for f in body["frames"] if f["t"] >= 15.0]
    matching = sum(1 for f in settled if len(f["tracks"]) == count)
    assert matching / len(settled) >= 0.95


def test_track_counts_are_not_observation_counts(app_client):
    """Three different quantities that must never be conflated."""
    client, _, _ = app_client
    body = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6").json()
    assert body["configured_entities"] == 6
    assert body["observation_count"] > 100
    assert body["measurement_count"] < body["observation_count"]
    assert len(body["frames"][-1]["tracks"]) == 6


def test_track_response_contains_no_ground_truth(app_client):
    client, _, _ = app_client
    raw = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6").text.lower()
    for token in OPERATOR_FORBIDDEN:
        assert token not in raw, f"{token} leaked into the track response"


def test_track_positions_are_local_simulation_metres(app_client):
    client, _, _ = app_client
    body = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6").json()
    assert body["frame"] == "LOCAL_SIM_METRES"
    assert body["site"]["radius_m"] == 600
    track = body["frames"][-1]["tracks"][0]
    assert set(track) >= {"id", "x", "y", "speed", "heading", "status", "priority",
                          "reason", "range_m", "age_s"}
    # Simulation metres, not degrees.
    assert abs(track["x"]) > 5 or abs(track["y"]) > 5


def test_track_ids_are_stable_across_the_run(app_client):
    """A contact keeps one display ID; one observation is not one drone."""
    client, _, _ = app_client
    body = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6").json()
    settled = [f for f in body["frames"] if f["t"] >= 20.0]
    first_ids = {t["id"] for t in settled[0]["tracks"]}
    for frame in settled[:len(settled) // 2]:
        assert {t["id"] for t in frame["tracks"]} == first_ids


def test_priority_reasons_are_from_the_documented_set(app_client):
    client, _, _ = app_client
    body = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6").json()
    allowed_priority = {"HIGH PRIORITY", "WATCH", "LOW PRIORITY"}
    allowed_reason = {"Inside monitored area", "Approaching boundary", "Near boundary",
                      "Approaching area", "Moving away", "Passing outside area",
                      "Position update overdue"}
    seen_priority, seen_reason = set(), set()
    for frame in body["frames"]:
        for track in frame["tracks"]:
            assert track["priority"] in allowed_priority
            assert track["reason"] in allowed_reason
            seen_priority.add(track["priority"])
            seen_reason.add(track["reason"])
    # The demonstration must actually exercise every attention level.
    assert seen_priority == allowed_priority
    assert "Inside monitored area" in seen_reason and "Moving away" in seen_reason


def test_the_scenario_is_deterministic_across_requests(app_client):
    client, _, preview_module = app_client
    first = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6").json()
    preview_module._TRACK_CACHE.clear()
    second = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6").json()
    assert first["frames"] == second["frames"]


def test_contact_loss_scenario_shows_coasting_and_stale(app_client):
    client, _, _ = app_client
    body = client.get(
        "/api/preview/tracks?name=operator_demo_signal_loss&seed=42&count=6"
    ).json()
    statuses = {t["status"] for f in body["frames"] for t in f["tracks"]}
    assert "COASTING" in statuses, "a brief gap should be visibly coasted"
    assert "STALE" in statuses, "an extended gap should be marked stale"
    assert "TRACKING" in statuses


def test_track_requests_are_bounded(app_client):
    client, _, _ = app_client
    assert client.get("/api/preview/tracks?name=operator_demo&seed=42&count=2").status_code == 422
    assert client.get("/api/preview/tracks?name=operator_demo&seed=42&count=11").status_code == 422
    assert client.get("/api/preview/tracks?name=mixed_threat_decoy&seed=42").status_code == 404


def test_the_track_cache_is_bounded(app_client, monkeypatch):
    client, _, preview_module = app_client
    # Lower the cap rather than generating twenty scenarios; the eviction path
    # is what is being tested, not the generator.
    monkeypatch.setattr(preview_module, "MAX_CACHED_SCENARIOS", 2)
    for seed in range(5):
        client.get(f"/api/preview/tracks?name=operator_demo&seed={seed}&count=3&duration_s=20")
    assert len(preview_module._TRACK_CACHE) <= 2


def test_the_operator_view_never_writes_to_the_incident_database(app_client):
    client, app_module, _ = app_client
    before = _incident_count(app_module)
    client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6")
    client.get("/api/preview/tracks?name=operator_demo_signal_loss&seed=42&count=3")
    assert _incident_count(app_module) == before == 0


def test_simulation_playback_never_marks_viso_connected(secured_client):
    client, _, _ = secured_client
    client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6")
    status = client.get("/api/preview/viso/status").json()
    assert status["state"] == "WAITING FOR DELIVERY"
    assert status["delivery_count"] == 0
