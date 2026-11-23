import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "dronewatch_test.db"))
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


