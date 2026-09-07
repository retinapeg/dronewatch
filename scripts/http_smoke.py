#!/usr/bin/env python3
"""Run the release-candidate HTTP checks against a real local Uvicorn process."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
TEST_TOKEN = "dronewatch-local-smoke-token-0000000000000000"
BODY_SENTINEL = "SMOKE_BODY_MUST_NOT_APPEAR_IN_LOGS"


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    authenticated: bool = False,
) -> tuple[int, dict[str, object]]:
    headers: dict[str, str] = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if authenticated:
        headers["Authorization"] = f"Bearer {TEST_TOKEN}"
    request = Request(base_url + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _json_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _observation(source_event_id: str, lifecycle_state: str, observed_at: str) -> dict[str, object]:
    return {
        "schema_version": "dronewatch.event.v1",
        "source_event_id": source_event_id,
        "source_system": "CONTRACT_TEST",
        "source_scope": "uvicorn-smoke",
        "track_id": "smoke-track-1",
        "observed_at": observed_at,
        "modality": "VISUAL",
        "provenance": "LIVE",
        "delivery_mode": "DIRECT",
        "simulation": False,
        "lifecycle_state": lifecycle_state,
        "detection_result": "POSITIVE",
        "classification": "DRONE",
        "confidence": 0.91,
    }


def main() -> int:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="dronewatch-http-smoke-") as temporary_directory:
        database_path = Path(temporary_directory) / "smoke.db"
        environment = os.environ.copy()
        environment.update(
            {
                "DRONEWATCH_DB_PATH": str(database_path),
                "DRONEWATCH_WEBHOOK_TOKEN": TEST_TOKEN,
                "DRONEWATCH_WEBHOOK_MAX_BYTES": "1024",
                "DRONEWATCH_SIMULATION": "0",
                "PYTHONUNBUFFERED": "1",
            }
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "info",
                "--no-access-log",
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log_output = ""
        try:
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Uvicorn exited before becoming ready")
                try:
                    health_status, health = _request(base_url, "GET", "/health")
                    if health_status == 200:
                        break
                except URLError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Uvicorn did not become ready")
                time.sleep(0.05)

            config_status, config = _request(base_url, "GET", "/api/config")
            assert config_status == 200
            assert config["webhook_auth_configured"] is True
            assert config["viso_adapter_configured"] is False
            assert "database_path" not in config

            observed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            )
            detected_body = _json_bytes(_observation("smoke-event-1", "DETECTED", observed_at))
            missing_status, missing = _request(
                base_url, "POST", "/webhook/canonical", body=detected_body
            )
            assert (missing_status, missing["code"]) == (401, "authentication_failed")

            accepted_status, accepted = _request(
                base_url,
                "POST",
                "/webhook/canonical",
                body=detected_body,
                authenticated=True,
            )
            assert (accepted_status, accepted["status"]) == (201, "accepted")

            duplicate_status, duplicate = _request(
                base_url,
                "POST",
                "/webhook/canonical",
                body=detected_body,
                authenticated=True,
            )
            assert (duplicate_status, duplicate["status"]) == (200, "duplicate")
            assert duplicate["observation_id"] == accepted["observation_id"]

            exited_body = _json_bytes(_observation("smoke-event-2", "EXITED", observed_at))
            exited_status, exited = _request(
                base_url,
                "POST",
                "/webhook/canonical",
                body=exited_body,
                authenticated=True,
            )
            assert (exited_status, exited["status"]) == (201, "accepted")

            events_status, events = _request(base_url, "GET", "/api/events?limit=1")
            assert events_status == 200
            assert events["open_count"] == 0
            assert events["status"] == "SAFE"
            assert len(events["events"]) == 1
            latest = events["latest"]
            assert isinstance(latest, dict)
            assert latest["state"] == "EXITED"
            compatibility = latest["raw_payload"]
            assert isinstance(compatibility, dict)
            assert len(_json_bytes(compatibility)) <= 4_096
            assert set(compatibility).issubset(
                {
                    "schema_version",
                    "source_event_id",
                    "source_scope",
                    "track_id",
                    "scenario_id",
                    "run_id",
                    "observed_at",
                    "modality",
                    "provenance",
                    "delivery_mode",
                    "classification",
                    "detection_result",
                    "position",
                    "coordinate_space",
                }
            )

            oversized_body = _json_bytes({"sentinel": BODY_SENTINEL, "padding": "x" * 2_000})
            oversized_status, oversized = _request(
                base_url,
                "POST",
                "/webhook/canonical",
                body=oversized_body,
                authenticated=True,
            )
            assert (oversized_status, oversized["code"]) == (413, "request_too_large")

            with sqlite3.connect(database_path) as connection:
                observations = int(
                    connection.execute("SELECT COUNT(*) FROM observations_v1").fetchone()[0]
                )
                delivery_keys = int(
                    connection.execute("SELECT COUNT(*) FROM delivery_keys").fetchone()[0]
                )
            assert observations == delivery_keys == 2
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                log_output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                log_output, _ = process.communicate(timeout=5)

        assert TEST_TOKEN not in log_output
        assert BODY_SENTINEL not in log_output
        assert str(database_path) not in log_output

    print("health/config: 200; auth configured; Viso adapter disabled; no database path exposed")
    print("missing auth: 401; accepted: 201; exact retry: 200 duplicate with same observation ID")
    print("matching EXITED: 201; persisted history: 2; delivery keys: 2; open tracks: 0")
    print("API projection: allowlisted and <=4096 bytes; oversized body: 413 with no write")
    print("captured logs: no credential, full-body sentinel, or database path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
