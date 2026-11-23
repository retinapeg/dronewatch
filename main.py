from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / os.getenv("DRONEWATCH_DB_PATH", "dronewatch.db")
LOGGER = logging.getLogger("dronewatch")


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_db()
    yield


app = FastAPI(title="DroneWatch", lifespan=lifespan)
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402
app.add_middleware(GZipMiddleware, minimum_size=4096)

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
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_nodes(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from walk_nodes(item)


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
    except (TypeError, ValueError):
        return None

    if value > 1 and value <= 100:
        value = value / 100
    if not 0.0 <= value <= 1.0:
        # Out of range means the sender's scale is unknown. Reporting "unknown"
        # is safer than clamping, which would invent maximum confidence.
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
        text = float(value)
        if text > 1_000_000_000_000:  # millis
            text = text / 1000
        try:
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


def _clamp_to_now(value: str) -> str:
    """A sender cannot date an observation in the future."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return utcnow()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return now.isoformat() if parsed > now else value


def _extract_received(payload: Any) -> str:
    candidate = find_first(payload, ["timestamp", "event_time", "eventtime", "received_at", "receivedat", "created_at", "createdat", "time", "ts"])
    return _clamp_to_now(parse_timestamp(candidate))


def _normalize_state(raw_state: Optional[str], detection_type: Optional[str], drone_detected: bool) -> str:
    normalized = (raw_state or "").strip().lower()
    if normalized:
        normalized = re.sub(r"\s+", "_", normalized)
    if "restricted" in normalized:
        return "RESTRICTED_ZONE"
    if "exit" in normalized or "leave" in normalized or "left" in normalized:
        return "EXITED"
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


def _normalize_incident(payload: Dict[str, Any], source_default: str, simulated: bool = False) -> Dict[str, Any]:
    raw_payload = payload if isinstance(payload, dict) else {"value": payload}

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
        if detection_type and "drone" in detection_type.lower():
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
    state = _normalize_state(state_raw, detection_type, drone_detected)
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


@app.get("/")
@app.get("/preview")
def preview() -> FileResponse:
    """The operator view. /preview is kept so existing links keep working."""
    return FileResponse(BASE_DIR / "preview.html")


@app.get("/assets/drone-types.png")
def drone_reference_art() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "drone-types.png", media_type="image/png")


@app.get("/preview/diagnostics")
def preview_diagnostics() -> FileResponse:
    """The raw-observation research view, kept rather than deleted."""
    return FileResponse(BASE_DIR / "diagnostics.html")


@app.get("/health")
def health() -> Dict[str, Any]:
    from dronewatch.api.preview import viso_provider_summary

    return {
        "status": "ok",
        "received_at": utcnow(),
        "providers": {"viso": viso_provider_summary()},
    }


# --- V0.2 preview surface --------------------------------------------------
# Viso results arrive only through the authenticated POST /v2/webhook/viso.
from dronewatch.api.preview import router as _preview_router  # noqa: E402

app.include_router(_preview_router)

from dronewatch.api.camera import router as _camera_router  # noqa: E402

app.include_router(_camera_router)
