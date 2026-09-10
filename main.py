from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import math
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from target_schema import targets_from_events

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / os.getenv("DRONEWATCH_DB_PATH", "dronewatch.db")
SIMULATION_ENABLED = os.getenv("DRONEWATCH_SIMULATION", "0") not in {"0", "false", "off", "no"}
LOGGER = logging.getLogger("dronewatch")
MAX_WEBHOOK_BYTES = 256 * 1024
MAX_JSON_DEPTH = 32
TARGET_QUERY_LIMIT = 200


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_db()
    yield


class OptionalStaticFiles(StaticFiles):
    async def check_config(self) -> None:
        if self.directory and not Path(self.directory).exists():
            return
        await super().check_config()


app = FastAPI(title="DroneWatch", lifespan=lifespan)
app.mount("/assets", OptionalStaticFiles(directory=BASE_DIR / "assets", check_dir=False), name="assets")

KNOWN_STATES = {"DETECTED", "APPROACHING", "RESTRICTED_ZONE", "EXITED", "UNKNOWN"}
KNOWN_SEVERITY = {"INFO", "WARNING", "HIGH"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                received_at TEXT NOT NULL,
                detection_type TEXT,
                drone_detected INTEGER NOT NULL DEFAULT 0,
                confidence REAL,
                state TEXT NOT NULL DEFAULT 'UNKNOWN',
                severity TEXT NOT NULL DEFAULT 'INFO',
                source TEXT,
                media_url TEXT,
                raw_payload TEXT NOT NULL,
                is_simulated INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def walk_nodes(value: Any) -> Iterable[Any]:
    pending = [value]
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, dict):
            pending.extend(node.values())
        elif isinstance(node, (list, tuple)):
            pending.extend(node)


def find_first(payload: Any, candidate_keys: Iterable[str]) -> Any:
    def compact(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    normalized_candidates = {compact(candidate) for candidate in candidate_keys}
    lower_candidates = {candidate.lower() for candidate in candidate_keys}
    for node in walk_nodes(payload):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if not isinstance(key, str):
                continue
            key_compact = compact(key)
            key_tokens = {part for part in re.split(r"[^a-z0-9]+", key.lower()) if part}
            token_compact = {compact(token) for token in key_tokens}
            if key_compact in normalized_candidates or key.lower() in lower_candidates:
                if value is None:
                    continue
                if isinstance(value, str) and value.strip() == "":
                    continue
                return value
            if token_compact & normalized_candidates:
                if value is None:
                    continue
                if isinstance(value, str) and value.strip() == "":
                    continue
                return value
    return None


def coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            stripped = value.strip().replace("%", "")
            if stripped == "":
                return None
            value = float(stripped)
        elif isinstance(value, (int, float)):
            value = float(value)
        else:
            value = float(str(value))
    except (TypeError, ValueError, OverflowError):
        return None

    if not math.isfinite(value):
        return None
    if value > 1 and value <= 100:
        value = value / 100
    if not 0 <= value <= 1:
        return None
    return round(value, 4)


def coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in {0, 1}:
            return bool(int(value))
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return None


def coerce_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    if isinstance(value, (bool, dict, list, tuple, set)):
        return None
    return str(value)


def parse_timestamp(value: Any) -> str:
    if value is None:
        return utcnow()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return utcnow()
        if text.endswith("Z"):
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.isoformat()
            except ValueError:
                pass
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat()
        except ValueError:
            return utcnow()
    if isinstance(value, (int, float)):
        try:
            text = float(value)
            if not math.isfinite(text):
                return utcnow()
            if text > 1_000_000_000_000:  # millis
                text = text / 1000
            return datetime.fromtimestamp(text, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return utcnow()
    return utcnow()


def _extract_detection_type(payload: Any) -> Optional[str]:
    return coerce_str(find_first(payload, ["label", "object", "detection", "detected", "type", "class", "category"]))


def _extract_confidence(payload: Any) -> Optional[float]:
    return coerce_float(find_first(payload, ["confidence", "score", "probability", "prob" ]))


def _extract_media_url(payload: Any) -> Optional[str]:
    return coerce_str(find_first(payload, ["media_url", "mediaurl", "snapshot", "image_url", "video_url", "url"]))


def _extract_received(payload: Any) -> str:
    candidate = find_first(payload, ["timestamp", "event_time", "eventtime", "received_at", "receivedat", "created_at", "createdat", "time", "ts"])
    return parse_timestamp(candidate)


def _is_negated_observation(value: Optional[str]) -> bool:
    if not value:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    tokens = normalized.split("_")
    return any(token in {"no", "not", "false", "negative", "absent"} for token in tokens)


def _normalize_state(
    raw_state: Optional[str],
    detection_type: Optional[str],
    drone_detected: bool,
    explicit_drone_detected: Optional[bool] = None,
) -> str:
    normalized = (raw_state or "").strip().lower()
    if normalized:
        normalized = re.sub(r"\s+", "_", normalized)
    if _is_negated_observation(raw_state) or _is_negated_observation(detection_type):
        return "UNKNOWN"
    if "exit" in normalized or "leave" in normalized or "left" in normalized:
        return "EXITED"
    if explicit_drone_detected is False:
        return "UNKNOWN"
    if "restricted" in normalized:
        return "RESTRICTED_ZONE"
    if "approach" in normalized or "approaching" in normalized:
        return "APPROACHING"
    if "detect" in normalized or "drone" in normalized:
        return "DETECTED"

    if detection_type and "drone" in detection_type.lower():
        return "DETECTED"
    if drone_detected:
        return "DETECTED"
    return "UNKNOWN"


def _normalize_severity(state: str, confidence: Optional[float], drone_detected: bool) -> str:
    if state == "RESTRICTED_ZONE":
        return "HIGH"
    if state == "APPROACHING":
        return "WARNING"
    if state == "DETECTED" and (confidence is None):
        return "INFO"
    if confidence is not None and confidence >= 0.85 and (drone_detected or state != "UNKNOWN"):
        return "WARNING"
    return "INFO"


def _normalize_incident(payload: Any, source_default: str, simulated: bool = False) -> Dict[str, Any]:
    raw_payload = payload

    event_id = coerce_str(
        find_first(
            raw_payload,
            ["event_id", "eventid", "event-id", "id", "uuid", "uuid4", "tracking_id", "trackingid", "trace_id", "traceid"],
        )
    ) or f"evt-{uuid.uuid4()}"

    detection_type = _extract_detection_type(raw_payload)

    explicit_drone_detected = coerce_bool(
        find_first(
            raw_payload,
            ["drone_detected", "drone", "isdetected", "detected", "is_drone", "has_drone"],
        )
    )

    if explicit_drone_detected is None:
        if detection_type and "drone" in detection_type.lower() and not _is_negated_observation(detection_type):
            drone_detected = True
        else:
            drone_detected = False
    else:
        drone_detected = explicit_drone_detected

    state_raw = coerce_str(
        find_first(
            raw_payload,
            ["state", "status", "zone_state", "event-state", "event_type", "incident_type", "condition"],
        )
    )
    if _is_negated_observation(state_raw):
        drone_detected = False
    state = _normalize_state(state_raw, detection_type, drone_detected, explicit_drone_detected)
    if state not in KNOWN_STATES:
        state = "UNKNOWN"

    confidence = _extract_confidence(raw_payload)
    severity = _normalize_severity(state, confidence, drone_detected)
    if severity not in KNOWN_SEVERITY:
        severity = "INFO"

    received_at = _extract_received(raw_payload)
    source = coerce_str(find_first(raw_payload, ["source", "camera", "station"]))
    if source is None:
        source = "SIMULATED" if simulated else source_default

    return {
        "event_id": event_id,
        "received_at": received_at,
        "detection_type": detection_type,
        "drone_detected": bool(drone_detected),
        "confidence": confidence,
        "state": state,
        "severity": severity,
        "source": source,
        "media_url": _extract_media_url(raw_payload),
        "raw_payload": raw_payload,
        "is_simulated": bool(simulated),
    }


def _write_incident(incident: Dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO incidents (
                event_id,
                received_at,
                detection_type,
                drone_detected,
                confidence,
                state,
                severity,
                source,
                media_url,
                raw_payload,
                is_simulated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident["event_id"],
                incident["received_at"],
                incident.get("detection_type"),
                int(bool(incident["drone_detected"])),
                incident.get("confidence"),
                incident["state"],
                incident["severity"],
                incident.get("source"),
                incident.get("media_url"),
                json.dumps(incident["raw_payload"], ensure_ascii=False),
                int(bool(incident["is_simulated"])),
            ),
        )
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "received_at": row["received_at"],
        "detection_type": row["detection_type"],
        "drone_detected": bool(row["drone_detected"]),
        "confidence": row["confidence"],
        "state": row["state"],
        "severity": row["severity"],
        "source": row["source"],
        "media_url": row["media_url"],
        "raw_payload": json.loads(row["raw_payload"]),
        "is_simulated": bool(row["is_simulated"]),
    }


def _query_events(limit: int = 20):
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT * FROM incidents
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]


class SimulatePayload(BaseModel):
    scenario: str


@app.get("/")
def root() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/legacy")
def legacy() -> FileResponse:
    legacy_path = BASE_DIR / "legacy.html"
    if not legacy_path.is_file():
        raise HTTPException(status_code=404, detail="Legacy interface unavailable")
    return FileResponse(legacy_path)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "received_at": utcnow(),
    }


@app.get("/api/config")
def config() -> Dict[str, bool]:
    return {"simulation_enabled": SIMULATION_ENABLED}


@app.get("/api/events")
def api_events(limit: int = 20) -> Dict[str, Any]:
    events = _query_events(limit=limit)
    latest = events[0] if events else None
    open_incidents = [evt for evt in events if evt["state"] != "EXITED"]
    status = "SAFE"
    if any(evt["state"] == "RESTRICTED_ZONE" for evt in open_incidents):
        status = "CRITICAL"
    elif any(evt["state"] == "APPROACHING" for evt in open_incidents):
        status = "WARNING"
    elif any(evt["state"] == "DETECTED" for evt in open_incidents):
        status = "ALERT"

    return {
        "status": status,
        "latest": latest,
        "open_incidents": open_incidents,
        "open_count": len(open_incidents),
        "events": events,
        "received_at": utcnow(),
    }


@app.get("/api/targets")
def api_targets() -> Dict[str, Any]:
    events = _query_events(limit=TARGET_QUERY_LIMIT)
    return {
        "schema_version": 1,
        "targets": targets_from_events(events),
        "received_at": utcnow(),
    }


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def _parse_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _validate_json_depth(payload: Any) -> None:
    pending = [(payload, 1)]
    while pending:
        node, depth = pending.pop()
        if isinstance(node, (dict, list)):
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting depth exceeded")
            children = node.values() if isinstance(node, dict) else node
            pending.extend((child, depth + 1) for child in children)


async def _read_bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_WEBHOOK_BYTES:
                raise HTTPException(status_code=413, detail="Webhook payload exceeds 256 KiB")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Webhook payload exceeds 256 KiB")
        body.extend(chunk)
    return bytes(body)


@app.post("/webhook/viso")
async def viso_webhook(request: Request):
    body_bytes = await _read_bounded_body(request)
    try:
        if not body_bytes:
            payload = {}
        else:
            payload = json.loads(
                body_bytes.decode("utf-8"),
                parse_constant=_reject_non_finite,
                parse_float=_parse_finite_float,
            )
        _validate_json_depth(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be valid, finite JSON") from exc

    incident = _normalize_incident(payload, "VISO", simulated=False)
    _write_incident(incident)
    LOGGER.info(
        "Webhook event stored event_id=%s state=%s simulated=%s",
        incident["event_id"],
        incident["state"],
        incident["is_simulated"],
    )
    return {"status": "ok"}


SIMULATION_TEMPLATES = {
    "detected": {
        "label": "drone",
        "confidence": 0.83,
        "state": "DETECTED",
        "media_url": "https://example.com/simulations/drone_detected.mp4",
        "source": "SIMULATED",
    },
    "restricted": {
        "label": "drone",
        "confidence": 0.96,
        "state": "RESTRICTED_ZONE",
        "media_url": "https://example.com/simulations/drone_restricted_zone.mp4",
        "source": "SIMULATED",
    },
    "left": {
        "label": "drone",
        "confidence": 0.79,
        "state": "EXITED",
        "media_url": "https://example.com/simulations/drone_left_zone.mp4",
        "source": "SIMULATED",
    },
}


@app.post("/dev/simulate")
def simulate_event(payload: SimulatePayload):
    if not SIMULATION_ENABLED:
        raise HTTPException(status_code=404, detail="Simulation endpoint unavailable")

    scenario = (payload.scenario or "").strip().lower()
    if scenario not in SIMULATION_TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported scenario '{scenario}'. Use detected, restricted, or left.",
        )

    template = dict(SIMULATION_TEMPLATES[scenario])
    template["timestamp"] = utcnow()
    template["event_id"] = f"sim-{uuid.uuid4()}"
    template["source"] = "SIMULATED"
    template["SIMULATED"] = True

    incident = _normalize_incident(template, source_default="SIMULATED", simulated=True)
    _write_incident(incident)
    return incident
