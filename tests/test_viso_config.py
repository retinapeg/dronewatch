"""Offline synthetic configuration/receipt checks; no vendor connection is made."""
import importlib
import logging
import sqlite3
from datetime import datetime

from fastapi.testclient import TestClient
import pytest

from dronewatch.config import ALIAS_CONFLICT, read_viso_config

API_KEY = "synthetic-outbound-key"
INBOUND = "synthetic-inbound-secret"
OTHER = "synthetic-conflicting-secret"
ENV_NAMES = ("VISO_API_KEY", "VISO_WEBHOOK_SECRET", "DRONEWATCH_WEBHOOK_SECRET")
PAYLOAD = {"appId": "synthetic-app", "incidentId": "synthetic-incident"}


@pytest.fixture
def config_client(tmp_path, monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DRONEWATCH_WEBHOOK_HEADER", raising=False)
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "incidents.db"))
    monkeypatch.setenv("DRONEWATCH_CAMERA_EVIDENCE_DB", str(tmp_path / "camera.sqlite3"))
    import main
    import dronewatch.api.preview as preview
    importlib.reload(main)
    monkeypatch.setattr(preview, "STATUS", preview.VisoStatus())
    monkeypatch.setattr(preview, "QUARANTINE", [])
    with TestClient(main.app) as client:
        yield client, preview


SETTINGS_CASES = [
    ({}, False, False, False),
    (dict.fromkeys(ENV_NAMES, ""), False, False, False),
    (dict.fromkeys(ENV_NAMES, " \t\n"), False, False, False),
    ({"VISO_API_KEY": API_KEY}, False, True, False),
    ({"VISO_WEBHOOK_SECRET": INBOUND}, True, False, False),
    ({"DRONEWATCH_WEBHOOK_SECRET": INBOUND}, True, False, False),
    ({"VISO_API_KEY": API_KEY, "VISO_WEBHOOK_SECRET": INBOUND}, True, True, False),
    ({"VISO_WEBHOOK_SECRET": INBOUND, "DRONEWATCH_WEBHOOK_SECRET": INBOUND}, True, False, False),
    ({"VISO_WEBHOOK_SECRET": " \t", "DRONEWATCH_WEBHOOK_SECRET": INBOUND}, True, False, False),
    ({"VISO_WEBHOOK_SECRET": INBOUND, "DRONEWATCH_WEBHOOK_SECRET": " \t"}, True, False, False),
    ({"VISO_API_KEY": " " + API_KEY + " ", "VISO_WEBHOOK_SECRET": " " + INBOUND + "\n",
      "DRONEWATCH_WEBHOOK_SECRET": INBOUND}, True, True, False),
    ({"VISO_WEBHOOK_SECRET": INBOUND, "DRONEWATCH_WEBHOOK_SECRET": OTHER}, False, False, True),
    ({"VISO_API_KEY": API_KEY, "VISO_WEBHOOK_SECRET": INBOUND,
      "DRONEWATCH_WEBHOOK_SECRET": OTHER}, False, True, True),
]


@pytest.mark.parametrize("settings,inbound,outbound,conflict", SETTINGS_CASES)
def test_configuration_and_health_never_claim_connection(
    config_client, monkeypatch, caplog, capsys, settings, inbound, outbound, conflict,
):
    client, preview = config_client
    caplog.set_level(logging.INFO)
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    config = read_viso_config()
    assert config.inbound_configured is inbound
    assert config.outbound_configured is outbound
    assert config.configuration_error == (ALIAS_CONFLICT if conflict else None)
    if conflict:
        assert config.webhook_secret is None
    response = client.get("/health")
    assert response.status_code == 200
    health = response.json()
    assert health["status"] == "ok"
    assert datetime.fromisoformat(health["received_at"]).utcoffset() is not None
    provider = health["providers"]["viso"]
    expected = ("CONFIGURATION_ERROR" if conflict else
                "CONFIGURED_UNVERIFIED" if inbound or outbound else "NOT_CONFIGURED")
    assert provider["state"] == expected
    if expected == "NOT_CONFIGURED":
        assert provider["message"] == "Viso: not configured"
    assert provider["inbound_configured"] is inbound
    assert provider["outbound_configured"] is outbound
    assert provider["connection_verified"] is False
    assert provider["delivery_received"] is False
    assert provider["configuration_error"] == config.configuration_error
    status_response = client.get("/api/preview/viso/status")
    status = status_response.json()
    assert status["state"] == ("ERROR" if conflict else "WAITING FOR DELIVERY" if inbound else "NOT CONFIGURED")
    assert status["configured"] is inbound
    assert status["delivery_count"] == 0
    assert status["configuration_error"] == config.configuration_error
    camera_response = client.get("/api/camera/status")
    assert camera_response.json()["configured"] is inbound
    # All settings are fabricated. Verify normal output and diagnostics without
    # ever putting actual environment credentials into test reports.
    denied = client.post("/v2/webhook/viso", json=PAYLOAD)
    assert denied.status_code == (401 if inbound else 503)
    assert preview.STATUS.delivery_count == 0
    captured = capsys.readouterr()
    output = (response.text + status_response.text + camera_response.text + denied.text
              + repr(config) + caplog.text + captured.out + captured.err)
    for value in (API_KEY, INBOUND, OTHER):
        assert value not in output


@pytest.mark.parametrize("name", ["VISO_WEBHOOK_SECRET", "DRONEWATCH_WEBHOOK_SECRET"])
@pytest.mark.parametrize("transport", ["header", "custom_header", "query"])
def test_inbound_aliases_preserve_authentication_transports(config_client, monkeypatch, name, transport):
    client, _ = config_client
    monkeypatch.setenv(name, INBOUND)
    kwargs = {}
    if transport == "query":
        kwargs["params"] = {"token": INBOUND}
    else:
        header = "X-Local-Test" if transport == "custom_header" else "X-DroneWatch-Token"
        if transport == "custom_header":
            monkeypatch.setenv("DRONEWATCH_WEBHOOK_HEADER", header)
        kwargs["headers"] = {header: INBOUND}
    response = client.post("/v2/webhook/viso", json=PAYLOAD, **kwargs)
    assert response.status_code == 200
    assert response.json()["outcome"] == "MAPPED"
    assert client.get("/api/preview/viso/status").json()["state"] == "VALID DELIVERY RECEIVED"
    provider = client.get("/health").json()["providers"]["viso"]
    assert provider["state"] == "DELIVERY_RECEIVED"
    assert provider["delivery_received"] is True
    assert provider["connection_verified"] is False


@pytest.mark.parametrize("token", [INBOUND, OTHER, API_KEY])
def test_conflicting_aliases_reject_both_secrets_without_writes(config_client, monkeypatch, token):
    client, preview = config_client
    for key, value in zip(ENV_NAMES, (API_KEY, INBOUND, OTHER)):
        monkeypatch.setenv(key, value)
    response = client.post("/v2/webhook/viso", json=PAYLOAD, headers={"X-DroneWatch-Token": token})
    assert response.status_code == 503
    assert response.json()["detail"] == ALIAS_CONFLICT
    assert preview.STATUS.delivery_count == 0
    assert preview.QUARANTINE == []
    assert client.get("/api/events").json()["events"] == []
    assert client.get("/api/camera/status").json()["delivery_count"] == 0


@pytest.mark.parametrize("payload,preview_state", [
    (PAYLOAD, "VALID DELIVERY RECEIVED"),
    ({"unexpected": "synthetic"}, "UNMAPPED PAYLOAD"),
])
def test_receipt_is_local_evidence_not_vendor_verification(config_client, monkeypatch, payload, preview_state):
    client, _ = config_client
    monkeypatch.setenv("VISO_WEBHOOK_SECRET", INBOUND)
    headers = {"X-DroneWatch-Token": INBOUND}
    assert client.post("/v2/webhook/viso", json=payload, headers=headers).status_code == 200
    provider = client.get("/health").json()["providers"]["viso"]
    assert provider["state"] == "DELIVERY_RECEIVED"
    assert provider["delivery_received"] is True
    assert provider["connection_verified"] is False
    assert client.get("/api/preview/viso/status").json()["state"] == preview_state
    monkeypatch.delenv("VISO_WEBHOOK_SECRET")
    provider = client.get("/health").json()["providers"]["viso"]
    assert provider["state"] == "NOT_CONFIGURED"
    assert provider["delivery_received"] is True  # history, not current readiness
    assert client.get("/api/preview/viso/status").json()["state"] == "NOT CONFIGURED"


def test_bad_auth_malformed_json_and_legacy_route_do_not_verify_connection(config_client, monkeypatch):
    client, _ = config_client
    monkeypatch.setenv("VISO_WEBHOOK_SECRET", INBOUND)
    monkeypatch.setenv("VISO_API_KEY", API_KEY)
    assert client.post("/v2/webhook/viso", json=PAYLOAD,
                       headers={"X-DroneWatch-Token": API_KEY}).status_code == 401
    assert client.post("/v2/webhook/viso", content=b"invalid-json",
                       headers={"X-DroneWatch-Token": INBOUND}).status_code == 400
    assert client.get("/api/preview/viso/status").json()["state"] == "ERROR"
    assert client.post("/webhook/viso", json=PAYLOAD).status_code == 200
    provider = client.get("/health").json()["providers"]["viso"]
    assert provider["state"] == "CONFIGURED_UNVERIFIED"
    assert provider["connection_verified"] is False
    assert provider["delivery_received"] is False


def test_new_credentials_are_redacted_from_camera_evidence(config_client, monkeypatch, caplog, capsys):
    client, _ = config_client
    monkeypatch.setenv("VISO_WEBHOOK_SECRET", INBOUND)
    monkeypatch.setenv("VISO_API_KEY", API_KEY)
    caplog.set_level(logging.INFO)
    response = client.post("/v2/webhook/viso", json={"summary": f"Synthetic {INBOUND} {API_KEY}"},
                           headers={"X-DroneWatch-Token": INBOUND})
    assert response.status_code == 200
    camera_status = client.get("/api/camera/status")
    assert camera_status.json()["results"][0]["summary"] == "Synthetic [REDACTED] [REDACTED]"
    from dronewatch.api.camera import evidence_path
    with sqlite3.connect(evidence_path()) as connection:
        evidence = connection.execute("SELECT evidence_json FROM camera_receipts").fetchone()[0]
    captured = capsys.readouterr()
    output = (evidence + camera_status.text + response.text + client.get("/health").text
              + client.get("/api/preview/viso/status").text + caplog.text + captured.out + captured.err)
    assert INBOUND not in output
    assert API_KEY not in output


def test_synthetic_preview_and_process_reset_preserve_honest_status(config_client, monkeypatch):
    client, preview = config_client
    monkeypatch.setenv("VISO_WEBHOOK_SECRET", INBOUND)
    assert client.get("/api/preview/scenario?name=single_threat&seed=42&duration_s=1").status_code == 200
    assert client.get("/health").json()["providers"]["viso"]["state"] == "CONFIGURED_UNVERIFIED"
    assert client.post("/v2/webhook/viso", json=PAYLOAD,
                       headers={"X-DroneWatch-Token": INBOUND}).status_code == 200
    preview.STATUS.reset()
    provider = client.get("/health").json()["providers"]["viso"]
    assert provider["state"] == "CONFIGURED_UNVERIFIED"
    assert provider["delivery_received"] is False
