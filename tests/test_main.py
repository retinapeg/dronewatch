"""HTTP and security regression tests for the DroneWatch V0.2 receiver."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TOKEN = "dronewatch-test-token-0123456789abcdef"


def canonical_payload(**overrides):
    payload = {
        "schema_version": "dronewatch.event.v1",
        "source_event_id": "evt-http-001",
        "source_system": "HTTP_TEST",
        "source_scope": "camera-north",
        "track_id": "track-http-1",
        "scenario_id": None,
        "run_id": None,
        "observed_at": (
            datetime.now(timezone.utc) - timedelta(seconds=2)
        ).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "modality": "VISUAL",
        "provenance": "LIVE",
        "delivery_mode": "DIRECT",
        "simulation": False,
        "lifecycle_state": "DETECTED",
        "detection_result": "POSITIVE",
        "classification": "DRONE",
        "confidence": 0.91,
        "frame_coordinates": {
            "coordinate_space": "FRAME_NORMALIZED",
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        },
    }
    payload.update(overrides)
    return payload


def auth_headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def reload_app(monkeypatch, database_path: Path, *, token=TOKEN, simulation=False, max_bytes=1024):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(database_path))
    if token is None:
        monkeypatch.delenv("DRONEWATCH_WEBHOOK_TOKEN", raising=False)
    else:
        monkeypatch.setenv("DRONEWATCH_WEBHOOK_TOKEN", token)
    monkeypatch.setenv("DRONEWATCH_SIMULATION", "1" if simulation else "0")
    monkeypatch.setenv("DRONEWATCH_WEBHOOK_MAX_BYTES", str(max_bytes))
    monkeypatch.setenv("DRONEWATCH_MAX_FUTURE_SECONDS", "60")
    monkeypatch.setenv("DRONEWATCH_OBSERVATION_RETENTION_DAYS", "30")
    monkeypatch.setenv("DRONEWATCH_OBSERVATION_MAX_COUNT", "10000")
    monkeypatch.setenv("DRONEWATCH_CONFLICT_RETENTION_DAYS", "7")
    monkeypatch.setenv("DRONEWATCH_CONFLICT_MAX_COUNT", "1000")
    import main as app_module

    return importlib.reload(app_module)


@pytest.fixture
def client(tmp_path, monkeypatch):
    app_module = reload_app(monkeypatch, tmp_path / "dronewatch-test.db")
    with TestClient(app_module.app) as test_client:
        yield test_client, app_module


def raw_asgi_request(app, *, path, body, headers, chunks=None):
    """Issue a precise ASGI request without an HTTP client rewriting headers."""

    async def run():
        body_chunks = list(chunks if chunks is not None else [body])
        request_messages = [
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(body_chunks) - 1,
            }
            for index, chunk in enumerate(body_chunks)
        ]
        sent = []

        async def receive():
            if request_messages:
                return request_messages.pop(0)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (
                    name if isinstance(name, bytes) else name.lower().encode("ascii"),
                    value if isinstance(value, bytes) else value.encode("latin-1"),
                )
                for name, value in headers
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        await app(scope, receive, send)
        start = next(message for message in sent if message["type"] == "http.response.start")
        response_body = b"".join(
            message.get("body", b"")
            for message in sent
            if message["type"] == "http.response.body"
        )
        return start["status"], dict(start.get("headers", [])), response_body

    return asyncio.run(run())


def direct_headers(*, token=TOKEN, content_type="application/json", length=None):
    headers = [("authorization", f"Bearer {token}")]
    if content_type is not None:
        headers.append(("content-type", content_type))
    if length is not None:
        headers.append(("content-length", str(length)))
    return headers


def database_counts(app_module):
    with sqlite3.connect(app_module.DB_PATH) as connection:
        return {
            "observations": connection.execute("SELECT COUNT(*) FROM observations_v1").fetchone()[0],
            "keys": connection.execute("SELECT COUNT(*) FROM delivery_keys").fetchone()[0],
            "conflicts": connection.execute("SELECT COUNT(*) FROM delivery_conflicts").fetchone()[0],
        }


def test_health_and_config_do_not_disclose_database_path(client):
    test_client, app_module = client
    health = test_client.get("/health")
    config = test_client.get("/api/config")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert config.status_code == 200
    assert config.json() == {
        "simulation_enabled": False,
        "webhook_auth_configured": True,
        "viso_adapter_configured": False,
        "webhook_max_bytes": 1024,
        "observation_retention_days": 30,
        "observation_max_count": 10000,
    }
    combined = health.text + config.text
    assert "database_path" not in combined
    assert str(app_module.DB_PATH) not in combined


def test_root_still_serves_the_preserved_v01_dashboard(client):
    test_client, _ = client
    response = test_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "DRONEWATCH" in response.text


def test_simulation_is_disabled_by_default(tmp_path, monkeypatch):
    app_module = reload_app(monkeypatch, tmp_path / "simulation-off.db", simulation=False)
    with TestClient(app_module.app) as test_client:
        response = test_client.post(
            "/dev/simulate", json={"scenario": "detected"}, headers=auth_headers()
        )
        assert response.status_code == 404
        assert database_counts(app_module)["observations"] == 0


def test_enabled_simulation_requires_auth_and_uses_canonical_storage(tmp_path, monkeypatch):
    app_module = reload_app(monkeypatch, tmp_path / "simulation-on.db", simulation=True)
    with TestClient(app_module.app) as test_client:
        assert test_client.post("/dev/simulate", json={"scenario": "detected"}).status_code == 401
        response = test_client.post(
            "/dev/simulate", json={"scenario": "restricted"}, headers=auth_headers()
        )
        assert response.status_code == 201
        latest = test_client.get("/api/events?limit=1").json()["latest"]
        assert latest["provenance"] == "SYNTHETIC"
        assert latest["delivery_mode"] == "LOCAL_SIMULATION"
        assert latest["is_simulated"] is True
        assert latest["state"] == "RESTRICTED_ZONE"
        assert database_counts(app_module) == {"observations": 1, "keys": 1, "conflicts": 0}


def test_enabled_simulation_authenticates_before_bounded_stable_body_validation(
    tmp_path, monkeypatch
):
    app_module = reload_app(
        monkeypatch,
        tmp_path / "simulation-boundary.db",
        simulation=True,
        max_bytes=1024,
    )
    marker = "SENSITIVE_MARKER"
    malformed = {"scenario": "detected", "secret": marker}
    with TestClient(app_module.app) as test_client:
        unauthenticated = test_client.post("/dev/simulate", json=malformed)
        assert unauthenticated.status_code == 401
        assert unauthenticated.json() == {
            "status": "error",
            "code": "authentication_failed",
        }
        assert marker not in unauthenticated.text

        authenticated = test_client.post(
            "/dev/simulate", json=malformed, headers=auth_headers()
        )
        assert authenticated.status_code == 422
        assert authenticated.json() == {
            "status": "error",
            "code": "invalid_simulation_request",
        }
        assert marker not in authenticated.text

        oversized = test_client.post(
            "/dev/simulate",
            content=b'{' + b'"scenario":"' + (b"x" * 1100) + b'"}',
            headers={**auth_headers(), "content-type": "application/json"},
        )
        assert oversized.status_code == 413
        assert oversized.json() == {"status": "error", "code": "request_too_large"}
        assert database_counts(app_module) == {
            "observations": 0,
            "keys": 0,
            "conflicts": 0,
        }


def test_enabled_simulation_rejects_unknown_scenario(tmp_path, monkeypatch):
    app_module = reload_app(monkeypatch, tmp_path / "simulation-unknown.db", simulation=True)
    with TestClient(app_module.app) as test_client:
        response = test_client.post(
            "/dev/simulate", json={"scenario": "imaginary"}, headers=auth_headers()
        )
        assert response.status_code == 400
        assert response.json() == {"status": "error", "code": "unsupported_scenario"}


def test_valid_canonical_webhook_is_stored_and_projected(client):
    test_client, app_module = client
    payload = canonical_payload()
    response = test_client.post("/webhook/canonical", json=payload, headers=auth_headers())
    assert response.status_code == 201
    assert response.json()["status"] == "accepted"
    assert response.json()["duplicate"] is False
    events_response = test_client.get("/api/events?limit=5")
    assert events_response.status_code == 200
    assert events_response.headers["cache-control"] == "no-store"
    assert events_response.headers["x-content-type-options"] == "nosniff"
    events = events_response.json()
    assert events["status"] == "ALERT"
    assert events["open_count"] == 1
    assert len(events["events"]) == 1
    latest = events["latest"]
    assert latest["event_id"] == payload["source_event_id"]
    assert latest["detection_type"] == "drone"
    assert latest["state"] == "DETECTED"
    assert latest["drone_detected"] is True
    assert latest["media_url"] is None
    assert database_counts(app_module) == {"observations": 1, "keys": 1, "conflicts": 0}


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer wrong-token-that-is-long-enough-000000",
        "Basic Zm9vOmJhcg==",
        "Bearer",
        "Bearer  token-with-leading-gap",
        "bearer ",
    ],
)
def test_canonical_webhook_rejects_missing_or_malformed_auth(client, authorization):
    test_client, app_module = client
    headers = {} if authorization is None else {"Authorization": authorization}
    response = test_client.post("/webhook/canonical", json=canonical_payload(), headers=headers)
    assert response.status_code == 401
    assert response.json() == {"status": "error", "code": "authentication_failed"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert database_counts(app_module)["observations"] == 0


def test_duplicate_authorization_headers_are_rejected(client):
    _, app_module = client
    body = json.dumps(canonical_payload()).encode("utf-8")
    status, _, response_body = raw_asgi_request(
        app_module.app,
        path="/webhook/canonical",
        body=body,
        headers=[
            ("authorization", f"Bearer {TOKEN}"),
            ("authorization", f"Bearer {TOKEN}"),
            ("content-type", "application/json"),
            ("content-length", str(len(body))),
        ],
    )
    assert status == 401
    assert json.loads(response_body) == {"status": "error", "code": "authentication_failed"}
    assert database_counts(app_module)["observations"] == 0


def test_authentication_happens_before_body_or_media_validation(client):
    test_client, app_module = client
    response = test_client.post(
        "/webhook/canonical",
        content=b"not-json" * 1000,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"
    assert database_counts(app_module)["observations"] == 0


def test_unconfigured_receiver_fails_closed(tmp_path, monkeypatch):
    app_module = reload_app(monkeypatch, tmp_path / "unconfigured.db", token=None)
    with TestClient(app_module.app) as test_client:
        response = test_client.post("/webhook/canonical", json=canonical_payload())
        assert response.status_code == 503
        assert response.json() == {"status": "error", "code": "receiver_unavailable"}
        assert database_counts(app_module)["observations"] == 0


@pytest.mark.parametrize(
    "content_type,encoding,expected_status",
    [
        (None, None, 415),
        ("text/plain", None, 415),
        ("application/json; charset=latin-1", None, 415),
        ("application/json; charset=utf-8; version=1", None, 415),
        ("application/json", "gzip", 415),
        ("Application/JSON; Charset=UTF-8", "identity", 201),
    ],
)
def test_content_type_charset_and_encoding_are_strict(client, content_type, encoding, expected_status):
    test_client, app_module = client
    headers = auth_headers()
    if content_type is not None:
        headers["Content-Type"] = content_type
    if encoding is not None:
        headers["Content-Encoding"] = encoding
    body = json.dumps(canonical_payload()).encode("utf-8")
    response = test_client.post("/webhook/canonical", content=body, headers=headers)
    assert response.status_code == expected_status
    assert database_counts(app_module)["observations"] == (1 if expected_status == 201 else 0)


def test_duplicate_content_type_or_content_encoding_headers_are_rejected(client):
    _, app_module = client
    body = json.dumps(canonical_payload()).encode("utf-8")
    for duplicated_name, duplicated_value in (
        ("content-type", "application/json"),
        ("content-encoding", "identity"),
    ):
        headers = direct_headers(length=len(body))
        if duplicated_name == "content-type":
            headers.append((duplicated_name, duplicated_value))
        else:
            headers.extend(
                [
                    (duplicated_name, duplicated_value),
                    (duplicated_name, duplicated_value),
                ]
            )
        status, _, response_body = raw_asgi_request(
            app_module.app,
            path="/webhook/canonical",
            body=body,
            headers=headers,
        )
        assert status == 415
        assert json.loads(response_body)["code"] == "unsupported_media_type"
    assert database_counts(app_module)["observations"] == 0


@pytest.mark.parametrize(
    "body,expected_code,expected_status",
    [
        (b"", "empty_body", 400),
        (b"   \n", "empty_body", 400),
        (b"{", "invalid_json", 400),
        (b'[{"valid":"json"}]', "invalid_observation", 422),
        (b'{"a":1,"a":2}', "invalid_json", 400),
        (b'{"nested":{"a":1,"a":2}}', "invalid_json", 400),
        (b'{"confidence":NaN}', "invalid_json", 400),
        (b'{"confidence":Infinity}', "invalid_json", 400),
        (b'{"bad":"\xff"}', "invalid_json", 400),
    ],
)
def test_body_json_and_utf8_fail_closed(client, body, expected_code, expected_status):
    test_client, app_module = client
    response = test_client.post(
        "/webhook/canonical",
        content=body,
        headers={**auth_headers(), "Content-Type": "application/json"},
    )
    assert response.status_code == expected_status
    assert response.json() == {"status": "error", "code": expected_code}
    assert database_counts(app_module)["observations"] == 0


@pytest.mark.parametrize(
    "path,body",
    [
        ("/webhook/canonical", b'{"confidence":' + (b"9" * 5_000) + b"}"),
        ("/webhook/viso", b'{"confidence":' + (b"9" * 5_000) + b"}"),
        ("/dev/simulate", b'{"scenario":' + (b"9" * 5_000) + b"}"),
    ],
)
def test_shared_json_reader_rejects_oversized_integer_literals_stably(
    tmp_path, monkeypatch, path, body
):
    app_module = reload_app(
        monkeypatch,
        tmp_path / (path.strip("/").replace("/", "-") + ".db"),
        simulation=True,
        max_bytes=65_536,
    )
    with TestClient(app_module.app) as test_client:
        response = test_client.post(
            path,
            content=body,
            headers={**auth_headers(), "Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json() == {"status": "error", "code": "invalid_json"}
        assert database_counts(app_module)["observations"] == 0


def test_excessive_json_depth_is_rejected_before_contract_validation(client):
    test_client, app_module = client
    nested = "0"
    for _ in range(25):
        nested = f"[{nested}]"
    response = test_client.post(
        "/webhook/canonical",
        content=f'{{"nested":{nested}}}'.encode("utf-8"),
        headers={**auth_headers(), "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_json"
    assert database_counts(app_module)["observations"] == 0


@pytest.mark.parametrize("declared", ["-1", "+10", "1.0", "ten"])
def test_invalid_content_length_is_rejected(client, declared):
    _, app_module = client
    body = json.dumps(canonical_payload()).encode("utf-8")
    status, _, response_body = raw_asgi_request(
        app_module.app,
        path="/webhook/canonical",
        body=body,
        headers=direct_headers(length=declared),
    )
    assert status == 400
    assert json.loads(response_body)["code"] == "invalid_content_length"
    assert database_counts(app_module)["observations"] == 0


def test_pathological_content_length_is_rejected_without_integer_conversion(client):
    _, app_module = client
    body = b"{}"
    status, _, response_body = raw_asgi_request(
        app_module.app,
        path="/webhook/canonical",
        body=body,
        headers=direct_headers(length="9" * 5_000),
    )
    assert status == 413
    assert json.loads(response_body) == {
        "status": "error",
        "code": "request_too_large",
    }
    assert database_counts(app_module)["observations"] == 0


def test_duplicate_content_length_headers_are_rejected(client):
    _, app_module = client
    body = json.dumps(canonical_payload()).encode("utf-8")
    headers = direct_headers(length=len(body))
    headers.append(("content-length", str(len(body))))
    status, _, response_body = raw_asgi_request(
        app_module.app, path="/webhook/canonical", body=body, headers=headers
    )
    assert status == 400
    assert json.loads(response_body)["code"] == "invalid_content_length"
    assert database_counts(app_module)["observations"] == 0


def test_missing_content_length_is_streamed_and_accepted(client):
    _, app_module = client
    body = json.dumps(canonical_payload()).encode("utf-8")
    status, _, response_body = raw_asgi_request(
        app_module.app,
        path="/webhook/canonical",
        body=body,
        chunks=[body[:50], body[50:]],
        headers=direct_headers(),
    )
    assert status == 201
    assert json.loads(response_body)["status"] == "accepted"
    assert database_counts(app_module)["observations"] == 1


def test_understated_content_length_is_rejected_after_streaming(client):
    _, app_module = client
    body = json.dumps(canonical_payload()).encode("utf-8")
    status, _, response_body = raw_asgi_request(
        app_module.app,
        path="/webhook/canonical",
        body=body,
        headers=direct_headers(length=len(body) - 1),
    )
    assert status == 400
    assert json.loads(response_body)["code"] == "invalid_content_length"
    assert database_counts(app_module)["observations"] == 0


def test_oversized_declared_body_is_rejected_without_read_or_write(client):
    _, app_module = client
    status, headers, response_body = raw_asgi_request(
        app_module.app,
        path="/webhook/canonical",
        body=b"{}",
        headers=direct_headers(length=1025),
    )
    assert status == 413
    assert dict(headers).get(b"connection") == b"close"
    assert json.loads(response_body)["code"] == "request_too_large"
    assert database_counts(app_module)["observations"] == 0


def test_oversized_stream_without_content_length_is_rejected_and_not_persisted(client):
    _, app_module = client
    status, headers, response_body = raw_asgi_request(
        app_module.app,
        path="/webhook/canonical",
        body=b"",
        chunks=[b"{" + (b" " * 511), b" " * 513],
        headers=direct_headers(),
    )
    assert status == 413
    assert dict(headers).get(b"connection") == b"close"
    assert json.loads(response_body)["code"] == "request_too_large"
    assert database_counts(app_module)["observations"] == 0


def test_contract_errors_are_generic_and_not_persisted(client):
    test_client, app_module = client
    marker = "SECRET_REQUEST_MARKER"
    payload = canonical_payload(secret=marker, observation_id="client-chosen")
    response = test_client.post("/webhook/canonical", json=payload, headers=auth_headers())
    assert response.status_code == 422
    assert response.json() == {"status": "error", "code": "invalid_observation"}
    assert marker not in response.text
    assert "observation_id" not in response.text
    assert database_counts(app_module)["observations"] == 0


def test_narrative_words_cannot_create_a_detection_or_transition(client):
    test_client, app_module = client
    narrative_only = {
        "summary": "Drone detected in the restricted zone and then left the area",
        "description": "approaching exit detected",
    }
    response = test_client.post(
        "/webhook/canonical", json=narrative_only, headers=auth_headers()
    )
    assert response.status_code == 422
    assert response.json() == {"status": "error", "code": "invalid_observation"}
    assert database_counts(app_module) == {"observations": 0, "keys": 0, "conflicts": 0}


def test_future_observation_is_rejected_without_consuming_idempotency_key(client):
    test_client, app_module = client
    future = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    response = test_client.post(
        "/webhook/canonical",
        json=canonical_payload(observed_at=future),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_observation_time"
    assert database_counts(app_module) == {"observations": 0, "keys": 0, "conflicts": 0}


def test_exact_retry_conflict_and_scope_are_distinct(client):
    test_client, app_module = client
    payload = canonical_payload()
    accepted = test_client.post("/webhook/canonical", json=payload, headers=auth_headers())
    duplicate = test_client.post(
        "/webhook/canonical",
        content=json.dumps(payload, indent=2).encode("utf-8"),
        headers={**auth_headers(), "Content-Type": "application/json"},
    )
    conflict = test_client.post(
        "/webhook/canonical",
        json={**payload, "confidence": 0.92},
        headers=auth_headers(),
    )
    other_scope = test_client.post(
        "/webhook/canonical",
        json={**payload, "source_scope": "camera-south"},
        headers=auth_headers(),
    )
    assert accepted.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["observation_id"] == accepted.json()["observation_id"]
    assert conflict.status_code == 409
    assert conflict.json() == {"status": "error", "code": "delivery_conflict"}
    assert other_scope.status_code == 201
    assert database_counts(app_module) == {"observations": 2, "keys": 2, "conflicts": 1}


def test_concurrent_http_retries_create_one_observation(client):
    test_client, app_module = client
    payload = canonical_payload(source_event_id="evt-http-concurrent")

    def submit(_):
        return test_client.post("/webhook/canonical", json=payload, headers=auth_headers())

    with ThreadPoolExecutor(max_workers=12) as executor:
        responses = list(executor.map(submit, range(24)))
    assert sum(response.status_code == 201 for response in responses) == 1
    assert sum(response.status_code == 200 for response in responses) == 23
    assert len({response.json()["observation_id"] for response in responses}) == 1
    assert database_counts(app_module) == {"observations": 1, "keys": 1, "conflicts": 0}


def test_canonical_endpoint_reserves_viso_source_system(client):
    test_client, app_module = client
    response = test_client.post(
        "/webhook/canonical",
        json=canonical_payload(source_system="VISO"),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "reserved_source_system"
    assert database_counts(app_module)["observations"] == 0


def test_viso_route_authenticates_then_fails_closed_without_evidence(client):
    test_client, app_module = client
    assert test_client.post("/webhook/viso", json={"anything": "provider-shaped"}).status_code == 401
    response = test_client.post(
        "/webhook/viso",
        json={"anything": "provider-shaped"},
        headers=auth_headers(),
    )
    assert response.status_code == 503
    assert response.json() == {"status": "error", "code": "viso_adapter_unavailable"}
    assert database_counts(app_module) == {"observations": 0, "keys": 0, "conflicts": 0}


def test_lifecycle_status_uses_materialized_track_head_and_exit_closes(client):
    test_client, _ = client
    base = datetime.now(timezone.utc) - timedelta(seconds=10)

    def post(event_id, state, offset):
        observed_at = (base + timedelta(seconds=offset)).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        return test_client.post(
            "/webhook/canonical",
            json=canonical_payload(
                source_event_id=event_id,
                lifecycle_state=state,
                observed_at=observed_at,
            ),
            headers=auth_headers(),
        )

    assert post("evt-detected", "DETECTED", 0).status_code == 201
    assert test_client.get("/api/events").json()["status"] == "ALERT"
    assert post("evt-restricted", "RESTRICTED_ZONE", 1).status_code == 201
    restricted = test_client.get("/api/events").json()
    assert restricted["status"] == "CRITICAL"
    assert restricted["open_count"] == 1
    assert post("evt-exited", "EXITED", 2).status_code == 201
    exited = test_client.get("/api/events").json()
    assert exited["status"] == "SAFE"
    assert exited["open_count"] == 0
    assert exited["latest"]["state"] == "EXITED"


def test_negative_latest_event_does_not_close_existing_positive_track(client):
    test_client, _ = client
    assert test_client.post(
        "/webhook/canonical", json=canonical_payload(), headers=auth_headers()
    ).status_code == 201
    negative = canonical_payload(
        source_event_id="evt-negative",
        track_id="track-http-1",
        lifecycle_state="UNKNOWN",
        detection_result="NEGATIVE",
        classification="NOT_DRONE",
        confidence=0.25,
        frame_coordinates=None,
    )
    assert test_client.post(
        "/webhook/canonical", json=negative, headers=auth_headers()
    ).status_code == 201
    events = test_client.get("/api/events").json()
    assert events["latest"]["detection_result"] == "NEGATIVE"
    assert events["status"] == "ALERT"
    assert events["open_count"] == 1


def test_api_projection_does_not_leak_token_paths_or_internal_digests(client):
    test_client, app_module = client
    rejected_marker = "SECRET_REQUEST_MARKER_DO_NOT_STORE"
    rejected = canonical_payload(extra_secret=rejected_marker)
    assert test_client.post(
        "/webhook/canonical", json=rejected, headers=auth_headers()
    ).status_code == 422
    assert test_client.post(
        "/webhook/canonical", json=canonical_payload(), headers=auth_headers()
    ).status_code == 201
    response = test_client.get("/api/events")
    encoded = response.text
    for forbidden in (
        TOKEN,
        rejected_marker,
        str(app_module.DB_PATH),
        "request_digest",
        "content_digest",
        "frame_coordinates_json",
        "authorization",
    ):
        assert forbidden not in encoded
    assert response.json()["events"][0]["media_url"] is None


def test_logs_never_include_token_body_or_database_path(client, caplog):
    test_client, app_module = client
    marker = "BODY_SECRET_MARKER"
    caplog.set_level(logging.INFO, logger="dronewatch")
    response = test_client.post(
        "/webhook/canonical",
        json=canonical_payload(extra_secret=marker),
        headers=auth_headers(),
    )
    assert response.status_code == 422
    accepted = test_client.post(
        "/webhook/canonical", json=canonical_payload(), headers=auth_headers()
    )
    assert accepted.status_code == 201
    log_text = caplog.text
    assert "webhook.accepted" in log_text
    assert marker not in log_text
    assert TOKEN not in log_text
    assert str(app_module.DB_PATH) not in log_text


def test_legacy_route_is_authenticated_and_fully_quarantined(client):
    test_client, app_module = client
    marker = "LEGACY_SECRET_MARKER"
    with sqlite3.connect(app_module.DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO incidents (
                event_id, received_at, detection_type, drone_detected,
                confidence, state, severity, source, media_url,
                raw_payload, is_simulated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                marker,
                "2026-09-07T12:00:00Z",
                "drone",
                1,
                0.99,
                "RESTRICTED_ZONE",
                "HIGH",
                marker,
                f"https://{marker}.example/file",
                json.dumps({"secret": marker}),
                0,
            ),
        )
    unauthorized = test_client.get("/api/legacy/events")
    authorized = test_client.get("/api/legacy/events", headers=auth_headers())
    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.headers["cache-control"] == "no-store"
    assert authorized.json()["record_status"] == "LEGACY_UNVERIFIED"
    assert marker not in authorized.text
    event = authorized.json()["events"][0]
    assert event["source"] == "LEGACY_UNVERIFIED"
    assert event["drone_detected"] is False
    assert event["state"] == "UNKNOWN"
    assert event["raw_payload"] == {"legacy_unverified": True}
    assert test_client.get("/api/events").json()["legacy_unverified_count"] == 1


def test_weak_or_whitespace_webhook_tokens_are_rejected(client, monkeypatch):
    _, app_module = client
    for token in ("x" * 31, "x" * 31 + " ", "x" * 31 + "\n", "x" * 31 + "£"):
        monkeypatch.setenv("DRONEWATCH_WEBHOOK_TOKEN", token)
        with pytest.raises(RuntimeError, match="at least 32 visible ASCII"):
            app_module._configured_token()


def test_simulation_setting_has_an_explicit_closed_vocabulary(client, monkeypatch):
    _, app_module = client
    for enabled in ("1", "true", "TRUE", "on", "yes"):
        monkeypatch.setenv("DRONEWATCH_SIMULATION", enabled)
        assert app_module.load_settings().simulation_enabled is True
    for disabled in ("0", "false", "FALSE", "off", "no"):
        monkeypatch.setenv("DRONEWATCH_SIMULATION", disabled)
        assert app_module.load_settings().simulation_enabled is False
    monkeypatch.setenv("DRONEWATCH_SIMULATION", "sometimes")
    with pytest.raises(RuntimeError, match="DRONEWATCH_SIMULATION"):
        app_module.load_settings()


@pytest.mark.parametrize(
    "name,value",
    [
        ("DRONEWATCH_WEBHOOK_MAX_BYTES", "1023"),
        ("DRONEWATCH_WEBHOOK_MAX_BYTES", "1048577"),
        ("DRONEWATCH_WEBHOOK_MAX_BYTES", "many"),
        ("DRONEWATCH_MAX_FUTURE_SECONDS", "3601"),
    ],
)
def test_numeric_security_settings_are_bounded(client, monkeypatch, name, value):
    _, app_module = client
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        app_module.load_settings()
