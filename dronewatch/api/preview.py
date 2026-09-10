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
    pipeline_input,
    FaultSpec,
)
from ..synthetic.scenarios import SCENARIO_NAMES
from ..tracks.frames import build_timeline
from ..tracks import uncertainty as _unc
import math as _math
from ..synthetic import generator as _gen
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


@router.get("/api/preview/paths")
def get_paths(
    name: str = Query("operator_demo"),
    seed: int = Query(42, ge=0, le=999_999),
    count: int = Query(6, ge=MIN_CONTACTS, le=MAX_CONTACTS),
    duration_s: float = Query(OPERATOR_DEMO_DURATION_S, gt=0, le=MAX_DURATION_S),
    mode: str = Query("normal"),
    track: str = Query(...),
    t: float = Query(..., ge=0),
    paths: int = Query(160, ge=8, le=600),
    horizon_s: float = Query(20.0, gt=0, le=120),
    max_speed: float = Query(45.0, gt=0, le=200),
) -> Dict[str, Any]:
    """Monte Carlo realisations of where a contact may be, from its last
    accepted state.

    Runs the tracker's own Itô SDE (nearly-constant velocity, white
    acceleration) forward from the estimate at frame time `t`, with the
    initial state drawn from the filter's posterior. The analytic 95% radius
    is returned beside the empirical one so the two can be compared on screen.
    """
    timeline = get_tracks(name=name, seed=seed, count=count, duration_s=duration_s, mode=mode)
    frames = timeline["frames"]
    idx = min(len(frames) - 1, max(0, int(round(t * timeline["frame_hz"]))))
    frame = frames[idx]
    snap = next((s for s in frame["tracks"] if s["id"] == track), None)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"{track} is not reported at t={frame['t']}")

    # Reconstruct the 4x4 covariance from what the projection carries: the
    # position block, plus velocity variance grown from the positional age.
    c = snap["cov"]
    age = snap["age_s"]
    w = timeline["estimator"]["process_noise_w_m2_s3"]
    v_var = 30.0 ** 2 * 0.05 + w * max(age, 0.0)   # a conservative velocity prior
    x0 = [snap.get("est", [snap["x"], snap["y"]])[0], snap.get("est", [snap["x"], snap["y"]])[1],
          snap["vel"][0], snap["vel"][1]]
    p0 = [[c[0], c[1], 0.0, 0.0], [c[1], c[2], 0.0, 0.0],
          [0.0, 0.0, v_var, 0.0], [0.0, 0.0, 0.0, v_var]]

    # Recent behaviour: the contact's positions over the frames before it was
    # lost, taken from the timeline itself. This is what shapes the region.
    hz = timeline["frame_hz"]
    history = []
    # The last accepted measurement was `age` seconds ago; look 14 s before THAT.
    lost_idx = idx - int(round(age * hz))
    for j in range(max(0, lost_idx - int(14 * hz)), idx + 1):
        s = next((q for q in frames[j]["tracks"] if q["id"] == track), None)
        if s and s["fresh"] == "U":
            history.append((frames[j]["t"], s["x"], s["y"]))
    # Thin to roughly the radar cadence so the estimator sees real motion, not
    # frame-rate jitter.
    history = history[::2] if len(history) > 8 else history

    # The loss instant, so paths start from the last accepted state and run
    # for (age + horizon): where it may be NOW and where it may be going.
    ens = _unc.sample_paths_adaptive(
        x0, p0, age + horizon_s, history, n_paths=paths, steps=24,
        seed=seed * 7919 + idx, max_speed_m_s=max_speed, w_cv_reference=w,
    )
    # Plain CV ensemble as the reference the adaptive one is compared against.
    cv = _unc.sample_paths(x0, p0, age + horizon_s, w, n_paths=1500, steps=16, seed=seed + 1)
    b = ens.behaviour
    return {
        "track": track, "t": frame["t"], "status": snap["status"], "fresh": snap["fresh"],
        "age_s": age, "horizon_s": horizon_s, "process_noise_w": w,
        "origin": [round(x0[0], 1), round(x0[1], 1)],
        "vel": snap["vel"],
        "times": ens.times,
        "paths": [[[round(x, 1), round(y, 1)] for x, y in path] for path in ens.paths],
        "regimes": ens.regimes,
        "regime_weights": ens.regime_weights,
        "behaviour": {
            "speed_m_s": round(b.speed_m_s, 1),
            "heading_deg": round((90.0 - _math.degrees(b.heading_rad)) % 360.0, 1),
            "turn_rate_deg_s": round(_math.degrees(b.turn_rate_rad_s), 2),
            "manoeuvre_sigma": round(b.manoeuvre_sigma, 2),
            "history_points": b.n_points, "fit": b.fit_quality,
        },
        # The morphed region: convex hull of the innermost 95% of endpoints.
        "hull95": ens.hull95,
        "n_paths": ens.n_paths, "rejected_by_speed_bound": ens.rejected,
        "analytic_r95_now_m": snap["r95"],
        "cv_r95_at_horizon_m": ens.cv_radius_m,
        "adaptive_r95_at_horizon_m": ens.empirical_radius_m,
        "cv_empirical_containment": cv.empirical_containment,
        "model": ("behaviour-weighted mixture of coordinated-turn regimes with white "
                  "acceleration; Monte Carlo (no closed form for the mixture). "
                  "CV Ito SDE ensemble reported alongside as the reference."),
        "cue": snap["cue"],
        "cue_window_s": snap.get("cue_window_s"),
        "synthetic": True,
    }


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

#: Sensor-loss demonstration modes. Each is a fault specification applied to
#: the generated observation stream plus the set of sources the estimator is
#: allowed to use. The browser cannot alter these; it only picks one.
SENSOR_LOSS_MODES: Dict[str, Dict[str, Any]] = {
    "normal": {"label": "Normal operation", "faults": "", "admit": ["radar-north"]},
    "radar_off": {"label": "Radar off 40-55 s", "faults": "radar:40-55", "admit": ["radar-north"]},
    "all_off": {"label": "All positional inputs off 40-55 s", "faults": "all:40-55",
                "admit": ["radar-north", "eo-south"]},
    "radar_off_bearing": {"label": "Radar off 40-55 s, bearing-only backup",
                          "faults": "radar:40-55;backup:bearing",
                          "admit": ["radar-north", "bearing-west"]},
    "radar_off_eo": {"label": "Radar off 40-55 s, EO position backup (25 m)",
                     "faults": "radar:40-55;backup:position",
                     "admit": ["radar-north", "eo-south"]},
    "radar_degraded": {"label": "Radar noise x4, 40-55 s", "faults": "degrade:40-55x4",
                       "admit": ["radar-north"]},
    "single_loss": {"label": "One contact unobserved 40-55 s", "faults": "loss:2@40-55",
                    "admit": ["radar-north"]},
    # 30 s: longer than the default 25 s retention, so this mode keeps tracks
    # for 45 s. That is a display policy and is stated as such.
    "radar_off_30s": {"label": "Radar off 30 s (40-70) — stochastic containment",
                      "faults": "radar:40-70", "admit": ["radar-north"], "retain_s": 45.0},
    "radar_off_30s_viso": {"label": "Radar off 30 s + Viso camera cued to lost contacts",
                           "faults": "radar:40-70;backup:viso",
                           "admit": ["radar-north", "viso-eo"], "retain_s": 45.0},
}


@router.get("/api/preview/tracks")
def get_tracks(
    name: str = Query("operator_demo"),
    seed: int = Query(42, ge=0, le=999_999),
    count: int = Query(6, ge=MIN_CONTACTS, le=MAX_CONTACTS),
    duration_s: float = Query(OPERATOR_DEMO_DURATION_S, gt=0, le=MAX_DURATION_S),
    mode: str = Query("normal"),
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

    if mode not in SENSOR_LOSS_MODES:
        raise HTTPException(status_code=404, detail=f"unknown mode {mode!r}; known: {list(SENSOR_LOSS_MODES)}")
    key = (name, seed, count, duration_s, mode)
    if key in _TRACK_CACHE:
        _TRACK_CACHE.move_to_end(key)
        return _TRACK_CACHE[key]

    spec = SENSOR_LOSS_MODES[mode]
    faults = FaultSpec.parse(spec["faults"])
    from ..tracks.tracker import TrackerConfig
    config = TrackerConfig(drop_after_s=spec["retain_s"]) if spec.get("retain_s") else None

    cues: List[Dict[str, Any]] = []
    if faults.backup == "viso":
        # PASS 1: the tracker's picture on radar alone decides where the camera
        # should look. PASS 2 generates the camera's detections against that
        # schedule. The camera only ever sees what it was pointed at.
        from dataclasses import replace as _replace
        from ..tracks.cueing import plan_camera_cues
        radar_only = _replace(faults, backup=None)
        obs1, scans1 = pipeline_input(name, seed=seed, duration_s=duration_s, count=count,
                                      faults=radar_only)
        pass1 = build_timeline(obs1, t_zero=T_ZERO, duration_s=duration_s,
                               site=MonitoredSite(), scans=scans1,
                               admit=[a for a in spec["admit"] if a != "viso-eo"], config=config)
        cues = plan_camera_cues(pass1["frames"], _gen.VISO_SENSOR_LOCATION,
                                rest_deg=_gen.VISO_FOV_CENTRE_DEG)
        faults = _replace(faults, viso_cues=tuple((c["t"], c["centre_deg"]) for c in cues))

    observations, scans = pipeline_input(
        name, seed=seed, duration_s=duration_s, count=count, faults=faults
    )
    timeline = build_timeline(
        observations, t_zero=T_ZERO, duration_s=duration_s, site=MonitoredSite(),
        scans=scans, admit=spec["admit"], config=config,
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
        "mode": mode,
        "mode_label": spec["label"],
        "sensors": ([{"id": "viso-eo", "kind": "eo-camera", "x": _gen.VISO_SENSOR_LOCATION[0],
                      "y": _gen.VISO_SENSOR_LOCATION[1], "fov_centre_deg": _gen.VISO_FOV_CENTRE_DEG,
                      "fov_half_deg": _gen.VISO_FOV_HALF_DEG, "max_range_m": _gen.VISO_MAX_RANGE_M,
                      "pan_tilt": True, "slew_deg_s": 40.0,
                      # The cue schedule the tracker produced: what the camera was
                      # pointed at, when, and why.
                      "cues": cues}]
                    if "viso-eo" in spec["admit"] else []),
        "faults": faults.label(),
        "modes": [{"id": k, "label": v["label"]} for k, v in SENSOR_LOSS_MODES.items()],
    })
    _TRACK_CACHE[key] = timeline
    while len(_TRACK_CACHE) > MAX_CACHED_SCENARIOS:
        _TRACK_CACHE.popitem(last=False)
    return timeline
