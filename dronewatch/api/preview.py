"""V0.2 preview API.

Additive only. Every V0.1 route in main.py is untouched, and nothing here writes
to the incidents database except a genuine, authenticated, mapped Viso delivery.

Ground-truth isolation
----------------------
This module imports `observations_only`, never `generate_scenario`. Entity
identities, true classes, control modes and observation provenance are discarded
inside the generator before anything reaches here, and a response-level test
asserts that no preview response body contains them.

Coordinate honesty
------------------
The M2 generator stores simulation metres inside a `GeoPosition` container, which
the M2 report flagged as the wrong type. That is corrected at this boundary: the
API emits an explicit `LOCAL_SIM_METRES` frame with x/y/z and never emits
`latitude`, `longitude` or `altitude_m`. These are not geographic coordinates and
not measured radar range.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ..domain.observation import GeoPosition, SensorObservation
from ..ingest.viso import MappingOutcome, adapt, redact
from ..synthetic.generator import (
    DEFAULT_DURATION_S,
    DEFAULT_TICK_HZ,
    T_ZERO,
    observations_only,
)
from ..synthetic.scenarios import SCENARIO_NAMES
from ..tracks.frames import build_timeline
from ..tracks.site import MonitoredSite

router = APIRouter()

#: Bounds. The preview is a demonstration, not a load test.
MAX_SWARM_COUNT = 20
MAX_DURATION_S = 300.0
MAX_OBSERVATIONS = 20000

#: Scenarios surfaced in the preview, in the order the UI shows them.
#: The operator demo is bounded to a legible size.
OPERATOR_SCENARIOS = ("operator_demo", "operator_demo_signal_loss")
OPERATOR_DEMO_DURATION_S = 90.0
MIN_CONTACTS, MAX_CONTACTS = 3, 10
CONTACT_CHOICES = (3, 6, 10)

_TRACK_CACHE: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()

FEATURED_SCENARIOS = (
    "mixed_threat_decoy",
    "sensor_disagreement",
    "sensor_dropout",
    "delayed_out_of_order",
    "single_threat",
    "small_swarm",
)

_CACHE: "OrderedDict[tuple, List[Dict[str, Any]]]" = OrderedDict()
MAX_CACHED_SCENARIOS = 16

_TOKEN_IN_QUERY = re.compile(r"(token=)[^&\s]+", re.IGNORECASE)


class _RedactToken(logging.Filter):
    """Keep a URL-supplied webhook token out of the access log.

    Uvicorn logs the full request line including the query string, so a token
    passed as `?token=...` would otherwise be written to disk in clear text.
    The query lives in `record.args`, so the formatted message is rebuilt.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = _TOKEN_IN_QUERY.sub(r"\1REDACTED", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


# Attached at import time. Uvicorn configures its loggers before the
# application is imported, and dictConfig does not clear existing filters.
logging.getLogger("uvicorn.access").addFilter(_RedactToken())

WEBHOOK_SECRET_ENV = "DRONEWATCH_WEBHOOK_SECRET"
WEBHOOK_HEADER_ENV = "DRONEWATCH_WEBHOOK_HEADER"
DEFAULT_WEBHOOK_HEADER = "X-DroneWatch-Token"
MAX_BODY_BYTES = int(os.getenv("DRONEWATCH_MAX_BODY_BYTES", "1048576"))


# --------------------------------------------------------------------------
# Synthetic preview
# --------------------------------------------------------------------------

def _position_payload(observation: SensorObservation) -> Optional[Dict[str, Any]]:
    """Re-emit a synthetic position in an explicitly local simulation frame.

    Returns None when the sensor supplied no position. Nothing is fabricated to
    fill the gap; such observations belong in the non-spatial evidence list.
    """
    position = observation.position
    if position is None:
        return None
    if isinstance(position, GeoPosition):
        # M2 stores simulation metres in this container. Rename at the boundary
        # and drop the geographic key names entirely.
        return {
            "frame": "LOCAL_SIM_METRES",
            "x": position.latitude,
            "y": position.longitude,
            "z": position.altitude_m,
        }
    return None


def _observation_payload(observation: SensorObservation) -> Dict[str, Any]:
    simulation_time = (observation.observed_at - T_ZERO).total_seconds()
    return {
        "observation_id": observation.observation_id,
        "sensor_id": observation.sensor_id,
        "modality": observation.modality.value,
        "observed_at": observation.observed_at.isoformat(),
        "received_at": observation.received_at.isoformat(),
        "sim_time_s": round(simulation_time, 3),
        "transport_delay_s": round(observation.transport_delay_s, 3),
        "position": _position_payload(observation),
        "classification": {
            object_class.value: round(probability, 4)
            for object_class, probability in observation.classification.entries
        },
        "confidence": observation.confidence,
        "signals": [
            {
                "centre_frequency_hz": signal.centre_frequency_hz,
                "amplitude": signal.amplitude,
                "bandwidth_hz": signal.bandwidth_hz,
            }
            for signal in observation.signals
        ],
    }


@router.get("/api/preview/scenarios")
def list_scenarios() -> Dict[str, Any]:
    return {
        "featured": [name for name in FEATURED_SCENARIOS if name in SCENARIO_NAMES],
        "all": list(SCENARIO_NAMES),
        "default": {"scenario": "mixed_threat_decoy", "seed": 42},
        "limits": {
            "max_swarm_count": MAX_SWARM_COUNT,
            "max_duration_s": MAX_DURATION_S,
        },
    }


@router.get("/api/preview/scenario")
def get_scenario(
    name: str = Query("mixed_threat_decoy"),
    seed: int = Query(42, ge=0, le=999_999),
    count: Optional[int] = Query(None, ge=1, le=MAX_SWARM_COUNT),
    duration_s: float = Query(DEFAULT_DURATION_S, gt=0, le=MAX_DURATION_S),
) -> Dict[str, Any]:
    if name not in SCENARIO_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown scenario {name!r}")

    key = (name, seed, count, duration_s)
    if key in _CACHE:
        _CACHE.move_to_end(key)
    else:
        observations = observations_only(
            name, seed=seed, duration_s=duration_s,
            tick_hz=DEFAULT_TICK_HZ, count=count,
        )
        # Replay in simulated delivery order, with a stable tie-break so the
        # same scenario always plays back in exactly the same sequence.
        ordered = sorted(
            observations, key=lambda o: (o.received_at, o.observation_id)
        )
        if len(ordered) > MAX_OBSERVATIONS:
            raise HTTPException(status_code=413, detail="scenario too large to preview")
        _CACHE[key] = [_observation_payload(o) for o in ordered]
        while len(_CACHE) > MAX_CACHED_SCENARIOS:
            _CACHE.popitem(last=False)

    payload = _CACHE[key]
    modalities = sorted({item["modality"] for item in payload})
    spatial = sum(1 for item in payload if item["position"] is not None)
    return {
        "scenario": name,
        "seed": seed,
        "count": count,
        "duration_s": duration_s,
        "synthetic": True,
        "frame": "LOCAL_SIM_METRES",
        "t_zero": T_ZERO.isoformat(),
        "observation_count": len(payload),
        "spatial_observation_count": spatial,
        "non_spatial_observation_count": len(payload) - spatial,
        "modalities": modalities,
        "observations": payload,
    }


# --------------------------------------------------------------------------
# Viso connection
# --------------------------------------------------------------------------

class VisoStatus:
    """In-memory connection state.

    Deliberately not persisted and deliberately not touched by synthetic
    playback or by the legacy V0.1 webhook, so nothing except a genuine
    authenticated delivery can make Viso appear connected.
    """

    NOT_CONFIGURED = "NOT CONFIGURED"
    WAITING = "WAITING FOR DELIVERY"
    VALID = "VALID DELIVERY RECEIVED"
    UNMAPPED = "UNMAPPED PAYLOAD"
    ERROR = "ERROR"

    def __init__(self) -> None:
        self.last_receipt_at: Optional[str] = None
        self.last_outcome: Optional[str] = None
        self.last_reason: Optional[str] = None
        self.last_shape: Optional[Dict[str, Any]] = None
        self.delivery_count = 0
        self.mapped_count = 0
        self.unmapped_count = 0
        self.last_error: Optional[str] = None

    def reset(self) -> None:
        self.__init__()

    def record(self, outcome: str, reason: str, shape: Dict[str, Any]) -> None:
        self.last_receipt_at = datetime.now(timezone.utc).isoformat()
        self.last_outcome = outcome
        self.last_reason = reason
        self.last_shape = shape
        self.delivery_count += 1
        if outcome == MappingOutcome.MAPPED.value:
            self.mapped_count += 1
        else:
            self.unmapped_count += 1

    def record_error(self, message: str) -> None:
        self.last_receipt_at = datetime.now(timezone.utc).isoformat()
        self.last_error = message
        self.delivery_count += 1

    @property
    def state(self) -> str:
        if not is_ingestion_configured():
            return self.NOT_CONFIGURED
        if self.last_error:
            return self.ERROR
        if self.delivery_count == 0:
            return self.WAITING
        if self.last_outcome == MappingOutcome.MAPPED.value:
            return self.VALID
        return self.UNMAPPED


STATUS = VisoStatus()

#: Quarantine for unrecognised deliveries. Bounded, shape only, never raw values.
QUARANTINE: List[Dict[str, Any]] = []
MAX_QUARANTINE = 20


def is_ingestion_configured() -> bool:
    return bool(os.getenv(WEBHOOK_SECRET_ENV, "").strip())


def _header_name() -> str:
    return os.getenv(WEBHOOK_HEADER_ENV, DEFAULT_WEBHOOK_HEADER)


def _authorise(request: Request) -> None:
    secret = os.getenv(WEBHOOK_SECRET_ENV, "").strip()
    if not secret:
        # No configuration means external ingestion is off. The local synthetic
        # preview is unaffected.
        raise HTTPException(
            status_code=503,
            detail=(
                f"External ingestion disabled. Set {WEBHOOK_SECRET_ENV} to enable "
                "the protected webhook."
            ),
        )
    presented = request.headers.get(_header_name()) or request.query_params.get("token")
    if not presented:
        raise HTTPException(status_code=401, detail="Invalid or missing webhook token")
    # Encode first: compare_digest raises TypeError on non-ASCII str input.
    if not hmac.compare_digest(
        str(presented).encode("utf-8"), secret.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook token")


async def _read_bounded_body(request: Request) -> bytes:
    """Stream the body with a hard byte ceiling.

    Content-Length is not trusted; the counter is what enforces the limit.
    """
    chunks: List[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Payload too large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/v2/webhook/viso")
async def protected_viso_webhook(request: Request) -> Dict[str, Any]:
    """Authenticated Viso ingestion.

    Separate from the V0.1 `/webhook/viso` route, which keeps its original
    unauthenticated behaviour so existing deployments and tests are unaffected.
    """
    _authorise(request)
    body = await _read_bounded_body(request)

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        STATUS.record_error("Body was not decodable JSON")
        raise HTTPException(status_code=400, detail="Body was not decodable JSON")

    if not isinstance(payload, dict):
        payload = {"value": payload}

    delivery_id = f"{STATUS.delivery_count + 1:06d}"
    delivery = adapt(payload, received_at=datetime.now(timezone.utc), delivery_id=delivery_id)
    shape = redact(payload)
    STATUS.last_error = None
    STATUS.record(delivery.outcome.value, delivery.reason, shape)

    if delivery.outcome is MappingOutcome.UNMAPPED:
        QUARANTINE.insert(0, {
            "received_at": STATUS.last_receipt_at,
            "reason": delivery.reason,
            "shape": shape,
        })
        del QUARANTINE[MAX_QUARANTINE:]
        # Quarantined, not stored, and explicitly not a detection.
        return {"status": "quarantined", "outcome": delivery.outcome.value}

    # A genuine, recognised delivery reaches the V0.1 store so the existing
    # dashboard sees it, exactly as a V0.1 Viso delivery would have.
    import main as v1

    incident = v1._normalize_incident(payload, "VISO", simulated=False)
    v1._write_incident(incident)
    return {"status": "ok", "outcome": delivery.outcome.value}


@router.get("/api/preview/viso/status")
def viso_status() -> Dict[str, Any]:
    """Connection state for the panel. Never returns raw payloads or the secret."""
    return {
        "state": STATUS.state,
        "configured": is_ingestion_configured(),
        "header_name": _header_name(),
        "webhook_path": "/v2/webhook/viso",
        "last_receipt_at": STATUS.last_receipt_at,
        "last_outcome": STATUS.last_outcome,
        "last_reason": STATUS.last_reason,
        "last_payload_shape": STATUS.last_shape,
        "delivery_count": STATUS.delivery_count,
        "mapped_count": STATUS.mapped_count,
        "unmapped_count": STATUS.unmapped_count,
        "last_error": STATUS.last_error,
        "max_body_bytes": MAX_BODY_BYTES,
        "quarantine": QUARANTINE[:5],
        "note": (
            "Receipt of a webhook proves receipt of a recorded-file result. "
            "It does not prove live video or continuous sensor coverage."
        ),
    }


# --------------------------------------------------------------------------
# Track timeline for the operator view
# --------------------------------------------------------------------------

@router.get("/api/preview/tracks")
def get_tracks(
    name: str = Query("operator_demo"),
    seed: int = Query(42, ge=0, le=999_999),
    count: int = Query(6, ge=MIN_CONTACTS, le=MAX_CONTACTS),
    duration_s: float = Query(OPERATOR_DEMO_DURATION_S, gt=0, le=MAX_DURATION_S),
) -> Dict[str, Any]:
    """Estimated tracks over time, for replay by the operator view.

    The tracker runs here, once, over observations only. The browser replays the
    result, so playback speed cannot change what is estimated and the display
    shows exactly what the tested Python tracker produced.
    """
    if name not in OPERATOR_SCENARIOS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown operator scenario {name!r}; known: {list(OPERATOR_SCENARIOS)}",
        )

    key = (name, seed, count, duration_s)
    if key in _TRACK_CACHE:
        _TRACK_CACHE.move_to_end(key)
        return _TRACK_CACHE[key]

    observations = observations_only(
        name, seed=seed, duration_s=duration_s, count=count
    )
    timeline = build_timeline(
        observations, t_zero=T_ZERO, duration_s=duration_s, site=MonitoredSite()
    )
    timeline.update({
        "scenario": name,
        "seed": seed,
        "configured_entities": count,
        "observation_count": len(observations),
        "synthetic": True,
        "frame": "LOCAL_SIM_METRES",
        "contact_choices": list(CONTACT_CHOICES),
        "scenarios": list(OPERATOR_SCENARIOS),
    })
    _TRACK_CACHE[key] = timeline
    while len(_TRACK_CACHE) > MAX_CACHED_SCENARIOS:
        _TRACK_CACHE.popitem(last=False)
    return timeline
