"""Cue the visual sensor at the lost contacts it can cover in one look.

A pan-tilt camera has one field of view. Deciding where to point it is a
tracker decision, not a sensor one. The camera's view is narrow and reaches a
long way, so at range several contacts fit in it at once: the plan groups the
contacts the radar has lost into looks, each look being the widest set whose
predicted bearings fit inside the field of view, and visits the looks in turn.
Within a look the camera is centred on the group, at where each contact most
probably IS now (the centroid of its behaviour-shaped region), not where it
was last seen. Slew is rate-limited so a real gimbal could actually do it, and
every cue says whether the camera has arrived (`settled`) or is still turning.

Two-pass by necessity: the camera's detections depend on where it looks,
which depends on the tracker's picture without them. So run the tracker on
radar alone, plan the cues, then generate the camera's detections against
that schedule and run the tracker again with both. That circularity is real
in any cued-sensor system; here it is simply made explicit.

The plan says what the camera was sent to look for. What it found is a
different question, answered from the second pass by `confirm_looks`: a look
is credited only with the contacts the camera really picked up while it held
that look.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

PRIORITY_RANK = {"HIGH PRIORITY": 0, "WATCH": 1, "LOW PRIORITY": 2}

#: The field of view and reach the plan assumes. The synthetic camera is built
#: with the same numbers (see dronewatch.synthetic.generator); a test holds the
#: two together.
FOV_HALF_DEG = 12.0
MAX_RANGE_M = 3000.0
#: Contacts are kept this far inside the edge of the view when a look is planned.
EDGE_MARGIN_DEG = 1.5
#: How long the camera stays on a look, and how long before a contact that has
#: just had a look is due another while others are waiting.
DWELL_S, REVISIT_S = 6.0, 10.0
SETTLED_WITHIN_DEG = 0.5


def _wrap(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def _look_for(members: Sequence[Dict[str, Any]]) -> Tuple[float, float]:
    """Centre and angular width of the smallest view holding every member."""
    anchor = members[0]["bearing"]
    offsets = [_wrap(m["bearing"] - anchor) for m in members]
    low, high = min(offsets), max(offsets)
    return (anchor + (low + high) / 2.0) % 360.0, high - low


def _best_look(lost: Sequence[Dict[str, Any]], served: Dict[str, float], t: float,
               usable_deg: float) -> List[Dict[str, Any]]:
    """The group of lost contacts to look at next.

    Every contact is tried as the clockwise edge of a view; the view takes in
    all contacts within `usable_deg` anticlockwise of it. A group with contacts
    that are due a look wins over one without; then the group holding the
    highest-priority contact, then the one covering more due contacts, then
    the one left alone the longest, then the nearer.
    """
    best, best_key = None, None
    for edge in lost:
        members = [c for c in lost if 0.0 <= (c["bearing"] - edge["bearing"]) % 360.0 <= usable_deg]
        due = [c for c in members if t - served.get(c["id"], -1e9) >= REVISIT_S]
        ranked = due or members
        alone = min(t - served.get(c["id"], -1e9) for c in members)
        key = (bool(due), -min(c["rank"] for c in ranked), len(due), min(alone, 1e6),
               len(members), -min(c["range"] for c in members))
        if best_key is None or key > best_key:
            best, best_key = members, key
    return best or []


def plan_camera_cues(
    frames: Sequence[Dict[str, Any]],
    camera_xy: Tuple[float, float],
    *,
    rest_deg: float,
    slew_deg_s: float = 40.0,
    step_s: float = 0.2,
    fov_half_deg: float = FOV_HALF_DEG,
    max_range_m: Optional[float] = MAX_RANGE_M,
) -> List[Dict[str, Any]]:
    """Return [{t, centre_deg, target, targets, settled, reason}] every `step_s`.

    `targets` are the lost contacts the look is for, left to right as the
    camera sees them; `target` is the most urgent of them. `settled` is false
    while the camera is still turning towards the look. When nothing is lost
    (or nothing lost is within reach) the camera returns to its rest bearing at
    the same slew rate, so the demonstration shows it coming back as well as
    going.
    """
    cx, cy = camera_xy
    usable = max(1.0, 2.0 * (fov_half_deg - EDGE_MARGIN_DEG))
    out: List[Dict[str, Any]] = []
    centre = rest_deg
    last_t = 0.0
    # Sensor management: stay on a look long enough to acquire what is in it,
    # then move to the next group, and do not come back to contacts just
    # served while others are waiting. Without this the camera would sit on
    # the most urgent group for the whole outage and the rest would never get
    # a look.
    current: List[str] = []
    since = 0.0
    served: Dict[str, float] = {}
    for f in frames:
        t = f["t"]
        if t - last_t < step_s - 1e-9 and out:
            continue
        lost = []
        for tr in f["tracks"]:
            if tr.get("fresh", "U") == "U":
                continue
            px, py = tr.get("hc") or tr.get("est") or [tr["x"], tr["y"]]
            distance = math.hypot(px - cx, py - cy)
            if max_range_m is not None and distance > max_range_m:
                continue                      # out of reach: a look would see nothing
            lost.append({"id": tr["id"], "bearing": math.degrees(math.atan2(py - cy, px - cx)),
                         "range": distance, "rank": PRIORITY_RANK.get(tr["priority"], 9),
                         "priority": tr["priority"], "age_s": tr["age_s"]})
        if lost:
            by_id = {c["id"]: c for c in lost}
            held = [by_id[i] for i in current if i in by_id]
            if held and t - since < DWELL_S and _look_for(held)[1] <= 2.0 * fov_half_deg:
                # Contacts are not all lost in the same instant. One that is lost a moment
                # later and fits the view being held joins that look instead of waiting.
                members = list(held)
                middle = _look_for(members)[0]
                for c in sorted(lost, key=lambda c: abs(_wrap(c["bearing"] - middle))):
                    if c["id"] not in current and _look_for(members + [c])[1] <= usable:
                        members.append(c)
                current = [c["id"] for c in members]
            else:
                for i in current:
                    served[i] = t
                members = _best_look(lost, served, t, usable)
                ids = [c["id"] for c in members]
                if set(ids) != set(current):
                    since = t
                elif t - since >= DWELL_S:
                    since = t                 # the only look there is: start its dwell again
                current = ids
            want, _ = _look_for(members)
            lead = min(members, key=lambda c: (c["rank"], c["range"]))
            # Left to right in the camera's image is anticlockwise to clockwise.
            anchor = members[0]["bearing"]
            ordered = sorted(members, key=lambda c: -_wrap(c["bearing"] - anchor))
            target: Optional[str] = lead["id"]
            targets = [c["id"] for c in ordered]
            reason = (f"{len(members)} lost in view · " if len(members) > 1 else "") + \
                f"{lead['priority'].split()[0]} · lost {lead['age_s']:.0f}s · dwell {t - since:.0f}s"
        else:
            if current:
                for i in current:
                    served[i] = t
            want, target, targets, reason = rest_deg, None, [], "rest"
            current = []
        # Rate-limited slew toward the wanted bearing.
        diff = _wrap(want - centre)
        max_step = slew_deg_s * (t - last_t if out else step_s)
        centre = (centre + max(-max_step, min(max_step, diff)) + 360.0) % 360.0
        out.append({"t": round(t, 2), "centre_deg": round(centre, 1), "target": target,
                    "targets": targets, "settled": abs(_wrap(want - centre)) <= SETTLED_WITHIN_DEG,
                    "reason": reason})
        last_t = t
    return out


#: A contact the camera has picked up counts as still in view this far past the edge:
#: its drawn position carries the camera's own measurement noise.
IN_VIEW_SLACK_DEG = 1.0


def confirm_looks(cues: Sequence[Dict[str, Any]], frames: Sequence[Dict[str, Any]],
                  sensor_id: str, camera_xy: Tuple[float, float], *,
                  fov_half_deg: float = FOV_HALF_DEG) -> List[Dict[str, Any]]:
    """Credit each look with the contacts the camera picked up in the replay that is shown.

    The plan is drawn up from the radar-only picture, so its `targets` are the
    contacts the camera was sent to look for. The replay that is shown also
    holds the camera's own detections, and the camera sees only what is truly
    inside its view: by late in an outage a look can pick up fewer contacts
    than it was sent for, or one more that happened to be in view. Showing the
    plan as if it were the result would put the camera "on" a contact it never
    saw.

    A look is every unbroken spell of the camera being settled away from rest.
    A contact is picked up in a look once a track in `frames` has an update
    from `sensor_id` made since the camera arrived. Each cue comes back with:

      planned  what the camera was sent for at that moment (the plan's targets)
      targets  while settled, every contact picked up at some point in this
               look, left to right as the camera sees them; empty when it
               found none. While turning, the planned contacts.
      seen     the contacts of this look that have been picked up by now and
               are drawn inside the view at this moment; empty while turning
      target   the most urgent of `targets`

    The pointing (`t`, `centre_deg`, `settled`) is not changed.
    """
    cx, cy = camera_xy
    by_time = {round(f["t"], 2): f for f in frames}
    out = [{**cue, "planned": list(cue.get("targets") or []), "seen": []} for cue in cues]
    index = 0
    while index < len(out):
        if not (out[index]["settled"] and out[index]["planned"]):
            index += 1
            continue
        end = index
        while end < len(out) and out[end]["settled"] and out[end]["planned"]:
            end += 1
        arrived = out[index]["t"]
        first: Dict[str, Dict[str, Any]] = {}          # contact -> what it looked like when picked up
        seen_at: List[List[str]] = []
        for cue in out[index:end]:
            frame = by_time.get(round(cue["t"], 2))
            inside = set()
            for track in (frame["tracks"] if frame else []):
                offset = _wrap(math.degrees(math.atan2(track["y"] - cy, track["x"] - cx)) - cue["centre_deg"])
                if abs(offset) <= fov_half_deg + IN_VIEW_SLACK_DEG:
                    inside.add(track["id"])
                age = (track.get("src") or {}).get(sensor_id)
                if age is None or cue["t"] - age < arrived - 1e-6 or track["id"] in first:
                    continue
                first[track["id"]] = {"offset": offset, "rank": PRIORITY_RANK.get(track.get("priority"), 9),
                                      "range": math.hypot(track["x"] - cx, track["y"] - cy)}
            seen_at.append([i for i in first if i in inside])
        # Left to right in the camera's image is anticlockwise to clockwise.
        ordered = sorted(first, key=lambda i: -first[i]["offset"])
        for cue, seen in zip(out[index:end], seen_at):
            lead = cue.get("target") if cue.get("target") in first else (
                min(ordered, key=lambda i: (first[i]["rank"], first[i]["range"])) if ordered else None)
            cue.update({"targets": list(ordered), "seen": [i for i in ordered if i in seen], "target": lead})
        index = end
    return out
