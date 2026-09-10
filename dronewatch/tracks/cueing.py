"""Cue the visual sensor at the most dangerous lost contact.

A pan-tilt camera has one field of view. Deciding where to point it is a
tracker decision, not a sensor one: every second, among the contacts the
radar has lost, pick the highest priority (nearest on a tie), and cue the
camera at the centroid of that contact's behaviour-shaped region — where it
most probably IS now, not where it was last seen. Slew is rate-limited so a
real gimbal could actually do it.

Two-pass by necessity: the camera's detections depend on where it looks,
which depends on the tracker's picture without them. So run the tracker on
radar alone, plan the cues, then generate the camera's detections against
that schedule and run the tracker again with both. That circularity is real
in any cued-sensor system; here it is simply made explicit.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

PRIORITY_RANK = {"HIGH PRIORITY": 0, "WATCH": 1, "LOW PRIORITY": 2}


def plan_camera_cues(
    frames: Sequence[Dict[str, Any]],
    camera_xy: Tuple[float, float],
    *,
    rest_deg: float,
    slew_deg_s: float = 40.0,
    step_s: float = 1.0,
) -> List[Dict[str, Any]]:
    """Return [{t, centre_deg, target, reason}] at `step_s` resolution.

    When nothing is lost the camera returns to its rest bearing at the same
    slew rate, so the demonstration shows it coming back as well as going.
    """
    cx, cy = camera_xy
    out: List[Dict[str, Any]] = []
    centre = rest_deg
    last_t = 0.0
    # Sensor management: dwell on a target long enough to acquire it (a few
    # frames of detections), then move to the next lost contact, and do not
    # come back to one just served while others are waiting. Without this the
    # camera would sit on the top-priority contact for the whole outage and
    # the others would never get a look.
    DWELL_S, REVISIT_S = 4.0, 10.0
    current, since, served = None, 0.0, {}
    for f in frames:
        t = f["t"]
        if t - last_t < step_s - 1e-9 and out:
            continue
        lost = [tr for tr in f["tracks"] if tr.get("fresh", "U") != "U"]
        if lost:
            lost.sort(key=lambda tr: (PRIORITY_RANK.get(tr["priority"], 9), tr["range_m"]))
            ids = [tr["id"] for tr in lost]
            if current in ids and t - since < DWELL_S:
                tgt = next(tr for tr in lost if tr["id"] == current)
            else:
                if current in ids:
                    served[current] = t
                fresh_choices = [tr for tr in lost if t - served.get(tr["id"], -1e9) >= REVISIT_S]
                tgt = (fresh_choices or lost)[0]
                if tgt["id"] != current:
                    current, since = tgt["id"], t
            px, py = tgt.get("hc") or tgt.get("est") or [tgt["x"], tgt["y"]]
            want = math.degrees(math.atan2(py - cy, px - cx))
            target, reason = tgt["id"], f"{tgt['priority'].split()[0]} · lost {tgt['age_s']:.0f}s · dwell {t - since:.0f}s"
        else:
            want, target, reason = rest_deg, None, "rest"
            current = None
        # Rate-limited slew toward the wanted bearing.
        diff = (want - centre + 180.0) % 360.0 - 180.0
        max_step = slew_deg_s * (t - last_t if out else step_s)
        centre = (centre + max(-max_step, min(max_step, diff)) + 360.0) % 360.0
        out.append({"t": round(t, 2), "centre_deg": round(centre, 1),
                    "target": target, "reason": reason})
        last_t = t
    return out
