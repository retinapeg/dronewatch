"""Builds a replayable timeline of track states.

The server runs the tracker once over a scenario and emits snapshots at a fixed
rate. The browser replays those snapshots, so what an operator sees is exactly
what the tested Python tracker produced, and playback speed cannot change the
result.

Causality: at frame time `now`, only reports whose received_at <= now have
been fed to the tracker. A report delivered later is not used earlier, and a
report observed earlier but delivered late is handled by the tracker's bounded
late-data policy. Changing future reports cannot change earlier frames.

Only observations and sensor heartbeats reach this module. It has no access to
ground truth, and the M1 import guard enforces that.

Projection version 2 adds, per track: the position covariance, a model-based
95% ellipse, the last accepted positional measurement, the age of positional
information, freshness and lifecycle, contributing sources with their ages,
and association ambiguity. Per frame it adds source health.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ..domain.enums import Modality
from ..domain.observation import GeoPosition, SensorObservation
from . import kalman as K
from . import uncertainty as U
from .attention import PRIORITY_ORDER, AttentionModel
from .site import MonitoredSite
from .tracker import Freshness, Tracker, TrackerConfig

PROJECTION_VERSION = 2

#: Snapshot rate. Fine enough to look continuous, coarse enough to stay small.
FRAME_HZ = 5.0

#: The primary positional modality. Other sources are admitted only when
#: explicitly enabled by the caller (see `admit`).
TRACKING_MODALITY = Modality.RADAR
DEFAULT_ADMIT = ("radar-north",)

#: Nominal noise per sensor, for source-health degradation checks. Values
#: mirror the synthetic suite; a real deployment would take them from the
#: sensor's own declaration.
NOMINAL_SIGMA_M = {"radar-north": 10.0, "eo-south": 25.0, "ir-south": 40.0,
                   "acoustic-west": 200.0, "rf-east": 120.0}
CADENCE_S = {"radar-north": 0.5, "eo-south": 1.0, "ir-south": 1.0,
             "acoustic-west": 2.0, "rf-east": 2.0, "bearing-west": 1.0}


def _sim_seconds(moment: datetime, t_zero: datetime) -> float:
    return (moment - t_zero).total_seconds()


def _as_measurement(observation: SensorObservation, t_zero: datetime) -> Optional[Dict[str, Any]]:
    raw = observation.raw or {}
    base = {
        "observation_id": observation.observation_id,
        "t": _sim_seconds(observation.observed_at, t_zero),
        "received_t": _sim_seconds(observation.received_at, t_zero),
        "source_id": observation.sensor_id,
    }
    if raw.get("kind") == "bearing":
        base.update({"kind": "bearing", "bearing": float(raw["bearing_rad"]),
                     "sensor_xy": tuple(raw["sensor_xy"]), "sigma_rad": raw.get("sigma_rad")})
        return base
    position = observation.position
    if not isinstance(position, GeoPosition):
        return None
    # M2 stores local simulation metres in this container; see the preview API.
    base.update({"kind": "position", "x": position.latitude, "y": position.longitude,
                 "z": position.altitude_m, "sigma_m": raw.get("sigma_m")})
    return base


def _round_cov(p: K.Matrix) -> List[float]:
    return [round(p[0][0]), round(p[0][1]), round(p[1][1])]


def build_timeline(
    observations: Sequence[SensorObservation],
    *,
    t_zero: datetime,
    duration_s: float,
    site: Optional[MonitoredSite] = None,
    config: Optional[TrackerConfig] = None,
    frame_hz: float = FRAME_HZ,
    scans: Sequence[Any] = (),
    admit: Sequence[str] = DEFAULT_ADMIT,
) -> Dict[str, Any]:
    """Run the tracker over a scenario and snapshot it at a fixed rate.

    `admit` lists the sensor ids whose measurements reach the estimator.
    Everything else is ignored here (Diagnostics still shows it).
    """
    site = site or MonitoredSite()
    tracker = Tracker(config)
    attention = AttentionModel(site)
    evidence = tuple(a.split(":")[0] for a in admit if a.endswith(":evidence"))
    admitted = tuple(a.split(":")[0] for a in admit)
    for source_id in admitted:
        tracker.declare_source(source_id, CADENCE_S.get(source_id, 1.0), NOMINAL_SIGMA_M.get(source_id),
                               evidence_only=source_id in evidence)

    measurements = [
        m for m in (_as_measurement(o, t_zero) for o in observations if o.sensor_id in admitted)
        if m is not None
    ]
    # Delivery order, which is what a live system would see.
    measurements.sort(key=lambda m: (m["received_t"], m["observation_id"]))
    heartbeats = sorted(
        ((s.t, s.sensor_id, getattr(s, "noise_sigma_m", None)) for s in scans if s.sensor_id in admitted),
        key=lambda h: (h[0], h[1]),
    )

    frames: List[Dict[str, Any]] = []
    step = 1.0 / frame_hz
    cursor, hb_cursor = 0, 0
    frame_count = int(round(duration_s * frame_hz)) + 1

    for index in range(frame_count):
        now = round(index * step, 3)
        while hb_cursor < len(heartbeats) and heartbeats[hb_cursor][0] <= now:
            t, sid, sigma = heartbeats[hb_cursor]
            tracker.heartbeat(sid, t, sigma)
            hb_cursor += 1
        due = []
        while cursor < len(measurements) and measurements[cursor]["received_t"] <= now:
            due.append(measurements[cursor])
            cursor += 1

        tracker.process(due, now=now)

        snapshots = []
        for track in tracker.visible_tracks():
            rule = attention.update(track, now)
            distance = site.range_to(track.x, track.y)
            pos_age = now - (track.last_measurement.t if track.last_measurement else track.state_time)
            cov = track.display_cov
            pos_cov = [[cov[0][0], cov[0][1]], [cov[1][0], cov[1][1]]]
            ellipse = K.position_ellipse(pos_cov)
            est = track.display_state
            r95 = U.containment_radius(pos_cov, 0.95)
            cue = U.cue_feasibility(
                cov, distance, pos_age,
                growth_probe=(track.state, track.covariance, tracker.config.process_noise_w),
            )
            snapshots.append({
                "id": track.track_id,
                # Displayed position: predicted state, or the last measured
                # position once STALE. The estimate itself is under "est".
                "x": round(track.x, 1),
                "y": round(track.y, 1),
                "speed": round(track.speed_m_s, 1),
                "heading": round(track.heading_deg, 1),
                "status": track.status.value,
                "priority": rule.priority.value,
                "reason": rule.reason,
                "basis": rule.basis[0],                     # m / p / s
                "range_m": round(distance),
                "altitude_m": (round(track.last_altitude_m)
                               if track.last_altitude_m is not None else None),
                "age_s": round(pos_age, 1),
                # --- projection v2 ---
                "fresh": track.freshness.value[0],          # U / P / S
                # Velocity vector of the estimate, m/s, simulation frame.
                "vel": [round(est[2], 1), round(est[3], 1)],
                # 95% circular containment radius, metres (major semi-axis).
                "r95": round(r95),
                # Effector handover feasibility: decision support, not fire control.
                # Handover feasibility as a code: 'ok' | 'range' | 'unc'. The
                # basket and excess are derived client-side from r95, range_m
                # and the basket angle sent once below — not repeated 4,500x.
                "cue": "ok" if cue.feasible else ("range" if "range" in cue.reason else "unc"),
                **({"cue_window_s": cue.seconds_until_infeasible}
                   if cue.seconds_until_infeasible is not None else {}),
                # Predicted position is only carried separately when the
                # displayed marker is held at the last measured position.
                **({"est": [round(est[0], 1), round(est[1], 1)]}
                   if track.frozen_position else {}),
                "cov": _round_cov(cov),
                "ell": [round(ellipse.semi_major_m), round(ellipse.semi_minor_m),
                        round(math.degrees(ellipse.angle_rad))],
                "meas": ([round(track.last_measurement.x, 1), round(track.last_measurement.y, 1),
                          round(track.last_measurement.t, 1)]
                         if track.last_measurement else None),
                "src": {sid: round(now - t_last, 1) for sid, t_last in track.sources.items()},
                **({"amb": round(track.last_margin, 1)} if track.last_margin is not None else {}),
                **({"ambn": track.ambiguous_count} if track.ambiguous_count else {}),
            })

        snapshots.sort(key=lambda s: (PRIORITY_ORDER[_priority(s)], s["range_m"]))
        frames.append({
            "t": now, "tracks": snapshots, "obs": cursor,
            "sources": {sid: s.state.value for sid, s in tracker.sources.items()},
        })

    return {
        "version": PROJECTION_VERSION,
        "site": {"name": site.name, "x": site.x, "y": site.y, "radius_m": site.radius_m},
        "frame_hz": frame_hz,
        "duration_s": duration_s,
        "frames": frames,
        "measurement_count": len(measurements),
        "tracking_modality": TRACKING_MODALITY.value,
        "admitted_sources": list(admitted),
        "tracks_confirmed": tracker.created_count,
        "tracks_created": tracker.created_count,
        "tracks_spawned": tracker.spawn_count,
        "tracks_archived": len(tracker.archived),
        "duplicates_ignored": tracker.duplicate_count,
        "late_applied": tracker.late_applied_count,
        "late_rejected": tracker.late_rejected_count,
        "invalid_rejected": tracker.rejected_invalid_count,
        "unassigned_nonpositional": tracker.unassigned_nonpositional_count,
        "evidence_only_reports": dict(tracker.evidence_count),
        "ambiguous_associations": tracker.ambiguous_association_count,
        "estimator": {
            "model": "nearly-constant-velocity, continuous white acceleration",
            "process_noise_w_m2_s3": tracker.config.process_noise_w,
            "gate_chi2_2dof": tracker.config.gate_chi2,
            "reorder_window_s": tracker.config.reorder_window_s,
            "region": "95% planar ellipse, chi2(2)=5.991, model-based",
            "cue_basket_mrad": U.DEFAULT_ACQUISITION_BASKET_MRAD,
            "cue_max_range_m": U.DEFAULT_MAX_EFFECTIVE_RANGE_M,
        },
        "origin": "synthetic",
    }


def _priority(snapshot: Dict[str, Any]):
    from .attention import Priority

    return Priority(snapshot["priority"])
