from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.requests import ClientDisconnect

from contracts import (
    Classification,
    DeliveryMode,
    DetectionResult,
    InboundObservationV1,
    LifecycleState,
    Provenance,
    build_canonical_observation,
    rfc3339,
    utcnow,
    validate_observation_time,
)
from storage import (
    RetentionPolicy,
    legacy_count,
    migrate_database,
    observation_count,
    query_events,
    query_legacy_events,
    query_open_tracks,
    store_observation,
)
from viso_adapter import VisoAdapterUnavailable, map_viso_delivery


BASE_DIR = Path(__file__).resolve().parent
LOGGER = logging.getLogger("dronewatch")
MAX_BODY_CONFIGURATION = 1_048_576
MAX_JSON_DEPTH = 20
MAX_JSON_NODES = 2_000
MAX_JSON_INTEGER_DIGITS = 128


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise RuntimeError(f"{name} is outside its supported range")
    return parsed


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "on", "yes"}:
        return True
    if normalized in {"0", "false", "off", "no"}:
        return False
    raise RuntimeError(f"{name} must be an explicit boolean value")


def _database_path() -> Path:
    configured = Path(os.getenv("DRONEWATCH_DB_PATH", "dronewatch.db")).expanduser()
    return configured if configured.is_absolute() else BASE_DIR / configured


def _configured_token() -> str | None:
    token = os.getenv("DRONEWATCH_WEBHOOK_TOKEN")
    if not token:
        return None
    if len(token) < 32 or any(not 33 <= ord(character) <= 126 for character in token):
        raise RuntimeError(
            "DRONEWATCH_WEBHOOK_TOKEN must contain at least 32 visible ASCII characters"
        )
    return token


@dataclass(frozen=True)
class Settings:
    database_path: Path
    webhook_token: str | None
    webhook_max_bytes: int
    max_future_seconds: int
    simulation_enabled: bool
    retention: RetentionPolicy


def load_settings() -> Settings:
    return Settings(
        database_path=_database_path(),
        webhook_token=_configured_token(),
        webhook_max_bytes=_env_int(
            "DRONEWATCH_WEBHOOK_MAX_BYTES",
            65_536,
            minimum=1_024,
            maximum=MAX_BODY_CONFIGURATION,
        ),
        max_future_seconds=_env_int(
            "DRONEWATCH_MAX_FUTURE_SECONDS",
            60,
            minimum=0,
            maximum=3_600,
        ),
        simulation_enabled=_env_bool("DRONEWATCH_SIMULATION"),
        retention=RetentionPolicy(
            observation_days=_env_int(
                "DRONEWATCH_OBSERVATION_RETENTION_DAYS", 30, minimum=1, maximum=3_650
            ),
            observation_max_count=_env_int(
                "DRONEWATCH_OBSERVATION_MAX_COUNT", 10_000, minimum=1, maximum=1_000_000
            ),
            conflict_days=_env_int(
                "DRONEWATCH_CONFLICT_RETENTION_DAYS", 7, minimum=1, maximum=365
            ),
            conflict_max_count=_env_int(
                "DRONEWATCH_CONFLICT_MAX_COUNT", 1_000, minimum=1, maximum=100_000
            ),
        ),
    )


SETTINGS = load_settings()
DB_PATH = SETTINGS.database_path
SIMULATION_ENABLED = SETTINGS.simulation_enabled


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate_database(SETTINGS.database_path)
    yield


app = FastAPI(title="DroneWatch", lifespan=lifespan)


@dataclass(frozen=True)
class RequestFailure(Exception):
    status_code: int
    code: str


class DuplicateJsonKey(ValueError):
    pass


class InvalidJsonConstant(ValueError):
    pass


def _failure_response(failure: RequestFailure) -> JSONResponse:
    headers: dict[str, str] = {}
    if failure.status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if failure.status_code == 413:
        headers["Connection"] = "close"
    return JSONResponse(
        status_code=failure.status_code,
        content={"status": "error", "code": failure.code},
        headers=headers,
    )


def _raw_header_values(request: Request, name: str) -> list[str]:
    target = name.lower().encode("ascii")
    return [
        value.decode("latin-1")
        for key, value in request.scope.get("headers", [])
        if key.lower() == target
    ]


def _authenticate(request: Request) -> None:
    expected = SETTINGS.webhook_token
    if expected is None:
        raise RequestFailure(503, "receiver_unavailable")
    headers = _raw_header_values(request, "authorization")
    if len(headers) != 1:
        raise RequestFailure(401, "authentication_failed")
    parts = headers[0].split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise RequestFailure(401, "authentication_failed")
    supplied_digest = hashlib.sha256(parts[1].encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    if not secrets.compare_digest(supplied_digest, expected_digest):
        raise RequestFailure(401, "authentication_failed")


def _validate_media_headers(request: Request) -> int | None:
    content_types = _raw_header_values(request, "content-type")
    if len(content_types) != 1:
        raise RequestFailure(415, "unsupported_media_type")
    components = [component.strip().lower() for component in content_types[0].split(";")]
    if components[0] != "application/json" or len(components) > 2:
        raise RequestFailure(415, "unsupported_media_type")
    if len(components) == 2 and components[1] != "charset=utf-8":
        raise RequestFailure(415, "unsupported_media_type")

    encodings = _raw_header_values(request, "content-encoding")
    if len(encodings) > 1 or (encodings and encodings[0].strip().lower() != "identity"):
        raise RequestFailure(415, "unsupported_media_type")

    lengths = _raw_header_values(request, "content-length")
    if len(lengths) > 1:
        raise RequestFailure(400, "invalid_content_length")
    if not lengths:
        return None
    if not lengths[0].isascii() or not lengths[0].isdigit():
        raise RequestFailure(400, "invalid_content_length")
    normalized_length = lengths[0].lstrip("0") or "0"
    if len(normalized_length) > len(str(MAX_BODY_CONFIGURATION)):
        raise RequestFailure(413, "request_too_large")
    declared = int(normalized_length)
    if declared > SETTINGS.webhook_max_bytes:
        raise RequestFailure(413, "request_too_large")
    return declared


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise InvalidJsonConstant


def _strict_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise InvalidJsonConstant
    return parsed


def _strict_json_int(value: str) -> int:
    if len(value.removeprefix("-")) > MAX_JSON_INTEGER_DIGITS:
        raise InvalidJsonConstant
    return int(value)


def _check_json_complexity(value: Any) -> None:
    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
            raise RequestFailure(400, "invalid_json")
        if isinstance(item, dict):
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)

    visit(value, 0)


async def _read_json_object(request: Request) -> tuple[dict[str, Any], str]:
    declared_length = _validate_media_headers(request)
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(chunk) > SETTINGS.webhook_max_bytes - len(body):
                raise RequestFailure(413, "request_too_large")
            body.extend(chunk)
    except ClientDisconnect as error:
        raise RequestFailure(400, "invalid_body") from error

    if declared_length is not None and declared_length != len(body):
        raise RequestFailure(400, "invalid_content_length")
    if not body or not bytes(body).strip():
        raise RequestFailure(400, "empty_body")

    try:
        decoded = bytes(body).decode("utf-8", errors="strict")
        payload = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_float=_strict_json_float,
            parse_int=_strict_json_int,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        DuplicateJsonKey,
        InvalidJsonConstant,
        RecursionError,
    ) as error:
        raise RequestFailure(400, "invalid_json") from error
    _check_json_complexity(payload)
    if not isinstance(payload, dict):
        raise RequestFailure(422, "invalid_observation")
    return payload, hashlib.sha256(bytes(body)).hexdigest()


def _validate_inbound(payload: dict[str, Any], *, reserve_viso: bool) -> InboundObservationV1:
    try:
        inbound = InboundObservationV1.model_validate(payload)
    except ValidationError as error:
        raise RequestFailure(422, "invalid_observation") from error
    if reserve_viso and inbound.source_system == "VISO":
        raise RequestFailure(422, "reserved_source_system")
    return inbound


def _store_inbound(
    inbound: InboundObservationV1,
    *,
    received_at: datetime,
    request_digest: str,
) -> JSONResponse:
    canonical = build_canonical_observation(inbound, received_at=received_at)
    try:
        validate_observation_time(canonical, max_future_seconds=SETTINGS.max_future_seconds)
    except ValueError as error:
        raise RequestFailure(422, "invalid_observation_time") from error
    try:
        result = store_observation(
            SETTINGS.database_path,
            canonical,
            request_digest=request_digest,
            retention=SETTINGS.retention,
        )
    except sqlite3.Error as error:
        LOGGER.error("webhook.storage_unavailable")
        raise RequestFailure(503, "storage_unavailable") from error

    if result.status == "conflict":
        LOGGER.warning("webhook.conflict")
        raise RequestFailure(409, "delivery_conflict")
    LOGGER.info("webhook.%s observation_id=%s", result.status, result.observation_id)
    return JSONResponse(
        status_code=201 if result.status == "accepted" else 200,
        content={
            "status": result.status,
            "observation_id": result.observation_id,
            "duplicate": result.status == "duplicate",
        },
    )


@app.get("/")
def root() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "received_at": rfc3339(utcnow())}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "simulation_enabled": SETTINGS.simulation_enabled,
        "webhook_auth_configured": SETTINGS.webhook_token is not None,
        "viso_adapter_configured": False,
        "webhook_max_bytes": SETTINGS.webhook_max_bytes,
        "observation_retention_days": SETTINGS.retention.observation_days,
        "observation_max_count": SETTINGS.retention.observation_max_count,
    }


@app.get("/api/events")
def api_events(limit: int = 20) -> JSONResponse:
    events = query_events(SETTINGS.database_path, limit=limit)
    open_incidents = query_open_tracks(SETTINGS.database_path)
    status = "SAFE"
    if any(event["state"] == "RESTRICTED_ZONE" for event in open_incidents):
        status = "CRITICAL"
    elif any(event["state"] == "APPROACHING" for event in open_incidents):
        status = "WARNING"
    elif any(event["state"] == "DETECTED" for event in open_incidents):
        status = "ALERT"
    return JSONResponse(
        content={
            "status": status,
            "latest": events[0] if events else None,
            "open_incidents": open_incidents,
            "open_count": len(open_incidents),
            "events": events,
            "legacy_unverified_count": legacy_count(SETTINGS.database_path),
            "received_at": rfc3339(utcnow()),
        },
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/legacy/events")
def api_legacy_events(request: Request, limit: int = 20) -> JSONResponse:
    try:
        _authenticate(request)
    except RequestFailure as failure:
        return _failure_response(failure)
    return JSONResponse(
        content={
            "record_status": "LEGACY_UNVERIFIED",
            "events": query_legacy_events(SETTINGS.database_path, limit=limit),
        },
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/webhook/canonical")
async def canonical_webhook(request: Request) -> JSONResponse:
    received_at = utcnow()
    try:
        _authenticate(request)
        payload, request_digest = await _read_json_object(request)
        inbound = _validate_inbound(payload, reserve_viso=True)
        return _store_inbound(inbound, received_at=received_at, request_digest=request_digest)
    except RequestFailure as failure:
        return _failure_response(failure)


@app.post("/webhook/viso")
async def viso_webhook(request: Request) -> JSONResponse:
    received_at = utcnow()
    try:
        _authenticate(request)
        payload, request_digest = await _read_json_object(request)
        try:
            inbound = map_viso_delivery(payload)
        except VisoAdapterUnavailable as error:
            raise RequestFailure(503, "viso_adapter_unavailable") from error
        if inbound.source_system != "VISO" or inbound.modality != "VISUAL":
            raise RequestFailure(422, "invalid_viso_mapping")
        return _store_inbound(inbound, received_at=received_at, request_digest=request_digest)
    except RequestFailure as failure:
        return _failure_response(failure)


class SimulatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str


SIMULATION_TEMPLATES = {
    "detected": LifecycleState.DETECTED,
    "restricted": LifecycleState.RESTRICTED_ZONE,
    "left": LifecycleState.EXITED,
}


@app.post("/dev/simulate")
async def simulate_event(request: Request) -> JSONResponse:
    if not SETTINGS.simulation_enabled:
        return JSONResponse(status_code=404, content={"detail": "Simulation endpoint unavailable"})
    try:
        _authenticate(request)
        raw_payload, request_digest = await _read_json_object(request)
        try:
            payload = SimulatePayload.model_validate(raw_payload)
        except ValidationError as error:
            raise RequestFailure(422, "invalid_simulation_request") from error
    except RequestFailure as failure:
        return _failure_response(failure)
    scenario = payload.scenario.strip().lower()
    if scenario not in SIMULATION_TEMPLATES:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "code": "unsupported_scenario"},
        )

    now = utcnow()
    data = {
        "schema_version": "dronewatch.event.v1",
        "source_event_id": f"sim-{uuid.uuid4()}",
        "source_system": "DRONEWATCH_SIMULATOR",
        "source_scope": "local-demo",
        "track_id": "simulated-track-1",
        "scenario_id": "local-demo",
        "run_id": "local-demo-run",
        "observed_at": rfc3339(now),
        "modality": "VISUAL",
        "provenance": Provenance.SYNTHETIC.value,
        "delivery_mode": DeliveryMode.LOCAL_SIMULATION.value,
        "simulation": True,
        "lifecycle_state": SIMULATION_TEMPLATES[scenario].value,
        "detection_result": DetectionResult.POSITIVE.value,
        "classification": Classification.DRONE.value,
        "confidence": 0.96 if scenario == "restricted" else 0.83,
    }
    inbound = InboundObservationV1.model_validate(data)
    try:
        return _store_inbound(inbound, received_at=now, request_digest=request_digest)
    except RequestFailure as failure:
        return _failure_response(failure)


def current_observation_count() -> int:
    """Narrow test/diagnostic helper; not an HTTP endpoint."""

    return observation_count(SETTINGS.database_path)
