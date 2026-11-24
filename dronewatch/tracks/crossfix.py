"""Turn bearings from several fixed cameras into position fixes.

One camera gives a direction to what it sees, and nothing useful about how
far away it is. Two cameras that see the same object at the same moment give
two directions, and where those cross is the object's position. This module
does that crossing, and the bookkeeping that keeps it honest:

* With several objects in view, the wrong pairs of directions cross as well
  ("ghosts"). Each camera also reports how high above the horizon the object
  is, and only a true pair agrees about the object's height at the crossing,
  so a pair is accepted only when the two heights agree. The rough range each
  camera gets from apparent size is used as a second, weak, check.
* A sighting that agrees with a track already held is given to that track
  first. Only sightings no track explains are paired with each other, so most
  pairing happens one new object at a time.
* A fix is as good as the geometry that made it: its covariance comes from the
  bearing error of each camera at its own distance, so two nearly parallel
  directions give a long thin region and two crossing squarely give a small one.
* A new object is only ever made from sightings that no held track is anywhere
  near. Two sightings that each lie close to some track already held, but to
  different tracks, are two known objects seen from two places; where those
  directions cross is a ghost, and it is not believed.
* A pair that makes a new object is checked against every other camera that
  ought to see the same spot. If one of them has that spot well inside its
  view and reports nothing there, the pair is not believed.
* A sighting that cannot be paired stays a bearing. It can tighten a track
  that already exists and is already well placed; it never starts one and it
  is never allowed to steer a track that has been lost.

Cameras are assumed to report at the same instants. Real cameras do not, and a
deployment would have to bring sightings to a common time first.

    position from N bearings (weighted least squares):
        minimise  sum_i ((p - c_i) . n_i)^2 / (d_i sigma_i)^2
        J = sum_i n_i n_i^T / (d_i sigma_i)^2,   p = J^-1 sum_i n_i n_i^T c_i / (d_i sigma_i)^2
        covariance = J^-1
    where c_i is camera i, n_i the unit normal to its bearing, d_i its distance
    to p and sigma_i its bearing error in radians.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Two directions closer to parallel than this do not make a fix.
MIN_CROSSING_DEG = 12.0
#: Gates, in standard deviations, for agreeing about height and about rough range.
HEIGHT_GATE_SIGMA = 3.0
RANGE_GATE_SIGMA = 3.0
#: Floors that stand in for what the error model leaves out (camera position
#: survey, timing): metres across a bearing, and metres of height.
CROSS_FLOOR_M = 1.5
HEIGHT_FLOOR_M = 2.0
#: Leaving a sighting unpaired costs this much; a pair must beat it to be made.
UNPAIRED_COST = 8.0
#: A sighting is given to an existing track when it is within this many
#: standard deviations of it and no other track is nearly as close.
TRACK_GATE_SIGMA = 3.5
#: How long sightings of one instant are held so every camera's report can arrive.
HOLD_S = 0.6
#: Nearer than this a bearing swings too fast to be trusted against a predicted position.
MIN_DISTANCE_M = 150.0
#: A lone bearing is given to a track only when the track is already known this
#: well across the line of sight, metres (one sigma). A track that has drifted
#: further than that is lost, and a bearing must not be allowed to steer it.
SINGLE_MAX_ACROSS_M = 80.0
#: "Ought to see it": inside this share of a camera's reach, half-view and picture height.
EXPECT_REACH, EXPECT_VIEW, EXPECT_ELEVATION = 0.9, 0.8, 0.85
#: A camera's stated reach is a soft edge; allow this much beyond it.
REACH_SLACK = 1.05
#: The name under which fixes reach the tracker.
FIX_SOURCE = "cameras"


@dataclass(frozen=True)
class Sighting:
    """One camera's report of one object at one instant."""
    observation_id: str
    camera_id: str
    t: float
    x: float
    y: float
    z: float
    bearing: float
    sigma_bearing: float
    elevation: Optional[float] = None
    sigma_elevation: Optional[float] = None
    range_hint: Optional[float] = None
    range_log_sigma: Optional[float] = None
    #: The furthest this camera's optics let it see anything, metres.
    reach: Optional[float] = None

    @classmethod
    def from_measurement(cls, m: Dict[str, Any]) -> "Sighting":
        return cls(m["observation_id"], m["source_id"], m["t"], m["sensor_xy"][0], m["sensor_xy"][1],
                   m.get("sensor_z") or 0.0, m["bearing"], m.get("sigma_rad") or math.radians(0.1),
                   m.get("elevation"), m.get("sigma_el"), m.get("range_m"), m.get("range_log_sigma"),
                   m.get("reach_m"))

    def within_reach(self, distance: float) -> bool:
        return self.reach is None or distance <= self.reach * REACH_SLACK

    def height_at(self, distance: float) -> Optional[float]:
        return None if self.elevation is None else self.z + distance * math.tan(self.elevation)


@dataclass(frozen=True)
class Fix:
    """A position made from two or more sightings."""
    x: float
    y: float
    z: Optional[float]
    covariance: Tuple[Tuple[float, float], Tuple[float, float]]
    sightings: Tuple[Sighting, ...]

    @property
    def cameras(self) -> Tuple[str, ...]:
        return tuple(s.camera_id for s in self.sightings)


def cross(a: Sighting, b: Sighting) -> Optional[Tuple[float, float, float, float]]:
    """Where two bearings cross: (x, y, distance from a, distance from b).

    None when they are nearly parallel or cross behind either camera.
    """
    ux, uy = math.cos(a.bearing), math.sin(a.bearing)
    vx, vy = math.cos(b.bearing), math.sin(b.bearing)
    det = ux * vy - uy * vx                       # sine of the angle between them
    if abs(det) < math.sin(math.radians(MIN_CROSSING_DEG)):
        return None
    dx, dy = b.x - a.x, b.y - a.y
    along_a = (dx * vy - dy * vx) / det
    along_b = (dx * uy - dy * ux) / det
    if along_a <= 0.0 or along_b <= 0.0:
        return None
    return a.x + along_a * ux, a.y + along_a * uy, along_a, along_b


def pair_cost(a: Sighting, b: Sighting) -> Optional[float]:
    """How badly two sightings disagree about being one object; None if they cannot be.

    The sum of the squared, normalised disagreements about height at the
    crossing and (at half weight, being weak evidence) about each camera's
    rough range. A true pair scores about 1; a ghost usually fails outright.
    """
    if a.camera_id == b.camera_id or (a.x, a.y) == (b.x, b.y):
        return None                                 # two lenses on one pole share a viewpoint
    hit = cross(a, b)
    if hit is None:
        return None
    _, _, along_a, along_b = hit
    if not (a.within_reach(along_a) and b.within_reach(along_b)):
        return None                                 # a crossing neither camera could have seen
    cost = 0.0
    for sighting, distance in ((a, along_a), (b, along_b)):
        if sighting.range_hint and sighting.range_log_sigma:
            off = math.log(distance / sighting.range_hint) / sighting.range_log_sigma
            if abs(off) > RANGE_GATE_SIGMA:
                return None
            cost += 0.5 * off * off
    height_a, height_b = a.height_at(along_a), b.height_at(along_b)
    if height_a is not None and height_b is not None:
        # Height error: each camera's elevation error at its distance, and the error in
        # each distance itself (the other camera's bearing error, through the crossing angle).
        sine = abs(math.sin(a.bearing - b.bearing))
        var = HEIGHT_FLOOR_M ** 2
        for sighting, distance, other, other_distance in ((a, along_a, b, along_b), (b, along_b, a, along_a)):
            var += (distance * sighting.sigma_elevation / math.cos(sighting.elevation) ** 2) ** 2
            var += (math.tan(sighting.elevation) * other_distance * other.sigma_bearing / sine) ** 2
        off2 = (height_a - height_b) ** 2 / var
        if off2 > HEIGHT_GATE_SIGMA ** 2:
            return None
        cost += off2
    return cost


def fit(sightings: Sequence[Sighting]) -> Optional[Fix]:
    """The position that best agrees with every bearing, and how well it is known."""
    if len(sightings) < 2:
        return None
    start = None
    for a, b in combinations(sightings, 2):
        start = cross(a, b)
        if start is not None:
            break
    if start is None:
        return None
    px, py = start[0], start[1]
    j = [[0.0, 0.0], [0.0, 0.0]]
    for _ in range(3):
        j = [[0.0, 0.0], [0.0, 0.0]]
        rhs = [0.0, 0.0]
        for s in sightings:
            nx, ny = -math.sin(s.bearing), math.cos(s.bearing)
            distance = max(1.0, math.hypot(px - s.x, py - s.y))
            weight = 1.0 / ((distance * s.sigma_bearing) ** 2 + CROSS_FLOOR_M ** 2)
            offset = nx * s.x + ny * s.y
            j[0][0] += weight * nx * nx; j[0][1] += weight * nx * ny
            j[1][0] += weight * ny * nx; j[1][1] += weight * ny * ny
            rhs[0] += weight * nx * offset; rhs[1] += weight * ny * offset
        det = j[0][0] * j[1][1] - j[0][1] * j[1][0]
        if det <= 0.0:
            return None
        px = (j[1][1] * rhs[0] - j[0][1] * rhs[1]) / det
        py = (j[0][0] * rhs[1] - j[1][0] * rhs[0]) / det
    det = j[0][0] * j[1][1] - j[0][1] * j[1][0]
    covariance = ((j[1][1] / det, -j[0][1] / det), (-j[1][0] / det, j[0][0] / det))
    heights, weights = [], []
    for s in sightings:
        distance = math.hypot(px - s.x, py - s.y)
        height = s.height_at(distance)
        if height is not None:
            heights.append(height)
            weights.append(1.0 / ((distance * s.sigma_elevation) ** 2 + HEIGHT_FLOOR_M ** 2))
    z = sum(h * w for h, w in zip(heights, weights)) / sum(weights) if heights else None
    return Fix(px, py, z, covariance, tuple(sightings))


def _best_pairing(left: Sequence[Sighting], right: Sequence[Sighting]) -> List[Tuple[Sighting, Sighting]]:
    """The pairing between two cameras' sightings with the least total disagreement.

    Every sighting left unpaired costs UNPAIRED_COST, so a doubtful pair is
    not made merely to use up sightings. Exhaustive, which is fine for the
    handful of objects two cameras share.
    """
    costs = {(i, k): pair_cost(a, b) for i, a in enumerate(left) for k, b in enumerate(right)}
    best: Tuple[float, List[Tuple[int, int]]] = (math.inf, [])

    def search(i: int, used: frozenset, total: float, chosen: List[Tuple[int, int]]) -> None:
        nonlocal best
        if total >= best[0]:
            return
        if i == len(left):
            total += UNPAIRED_COST * (len(right) - len(used))
            if total < best[0]:
                best = (total, list(chosen))
            return
        search(i + 1, used, total + UNPAIRED_COST, chosen)
        for k in range(len(right)):
            cost = costs[(i, k)]
            if k in used or cost is None:
                continue
            chosen.append((i, k))
            search(i + 1, used | {k}, total + cost, chosen)
            chosen.pop()

    search(0, frozenset(), 0.0, [])
    return [(left[i], right[k]) for i, k in best[1]]


def pair_new(sightings: Sequence[Sighting]) -> Tuple[List[Fix], List[Sighting]]:
    """Fixes made from sightings no track explains, and the sightings left over."""
    by_camera: Dict[str, List[Sighting]] = {}
    for s in sightings:
        by_camera.setdefault(s.camera_id, []).append(s)
    used: set = set()
    groups: List[List[Sighting]] = []
    # Camera pairs with the cleanest agreement first, so a good pair is not broken up by a poor one.
    order = []
    for first, second in combinations(sorted(by_camera), 2):
        costs = [c for a in by_camera[first] for b in by_camera[second] if (c := pair_cost(a, b)) is not None]
        if costs:
            order.append((min(costs), first, second))
    for _, first, second in sorted(order):
        left = [s for s in by_camera[first] if s.observation_id not in used]
        right = [s for s in by_camera[second] if s.observation_id not in used]
        for a, b in _best_pairing(left, right):
            used.update((a.observation_id, b.observation_id))
            groups.append([a, b])
    # A further camera that agrees with every member of exactly one pair joins it.
    def agrees(s: Sighting, group: List[Sighting]) -> bool:
        return all((m.x, m.y) != (s.x, s.y) and pair_cost(s, m) is not None for m in group)

    for s in sightings:
        if s.observation_id in used:
            continue
        fitting = [g for g in groups if agrees(s, g)]
        if len(fitting) == 1:
            fitting[0].append(s)
            used.add(s.observation_id)
    fixes = [f for f in (fit(g) for g in groups) if f is not None]
    made = {s.observation_id for f in fixes for s in f.sightings}
    return fixes, [s for s in sightings if s.observation_id not in made]


def _track_offset(sighting: Sighting, x: float, y: float, cov: Sequence[Sequence[float]],
                  altitude: Optional[float]) -> Optional[Tuple[float, float]]:
    """How far a sighting is from a track's predicted position, in standard deviations,
    and how well the track is known across the line of sight, in metres."""
    dx, dy = x - sighting.x, y - sighting.y
    distance = math.hypot(dx, dy)
    if distance < MIN_DISTANCE_M or not sighting.within_reach(distance / 1.1):
        return None
    nx, ny = -dy / distance, dx / distance
    across = nx * (cov[0][0] * nx + cov[0][1] * ny) + ny * (cov[1][0] * nx + cov[1][1] * ny)
    sigma = math.sqrt(sighting.sigma_bearing ** 2 + max(0.0, across) / distance ** 2)
    off = abs((sighting.bearing - math.atan2(dy, dx) + math.pi) % (2.0 * math.pi) - math.pi) / sigma
    if sighting.range_hint and sighting.range_log_sigma:
        if abs(math.log(distance / sighting.range_hint)) > RANGE_GATE_SIGMA * sighting.range_log_sigma + 0.3:
            return None
    if altitude is not None and sighting.elevation is not None:
        along = dx / distance * (cov[0][0] * dx / distance + cov[0][1] * dy / distance) \
            + dy / distance * (cov[1][0] * dx / distance + cov[1][1] * dy / distance)
        expected = math.atan2(altitude - sighting.z, distance)
        sigma_el = math.sqrt(sighting.sigma_elevation ** 2 + (HEIGHT_FLOOR_M * 4 / distance) ** 2
                             + (math.tan(expected) / distance) ** 2 * max(0.0, along))
        off = max(off, abs(sighting.elevation - expected) / sigma_el)
    return off, math.sqrt(max(0.0, across))


@dataclass(frozen=True)
class View:
    """What a fixed camera can see: where it stands, where it looks, how far and how high."""
    x: float
    y: float
    z: float
    heading_deg: float
    hfov_deg: float
    reach_m: float
    max_elevation_deg: float

    def expects(self, x: float, y: float, z: Optional[float]) -> Optional[float]:
        """The bearing at which this camera should see a point comfortably inside its view, else None."""
        dx, dy = x - self.x, y - self.y
        distance = math.hypot(dx, dy)
        if not MIN_DISTANCE_M <= distance <= self.reach_m * EXPECT_REACH:
            return None
        bearing = math.atan2(dy, dx)
        off = abs((math.degrees(bearing) - self.heading_deg + 180.0) % 360.0 - 180.0)
        if off > EXPECT_VIEW * self.hfov_deg / 2.0:
            return None
        if z is None:
            return None                               # without a height there is no telling if it is in the picture
        elevation = math.degrees(math.atan2(z - self.z, distance))
        if not 0.15 * self.max_elevation_deg <= elevation <= EXPECT_ELEVATION * self.max_elevation_deg:
            return None
        return bearing


class CrossFixer:
    """Holds camera sightings until an instant is complete, then resolves it.

    `feed` takes whatever measurements have arrived and returns what should go
    to the tracker now: everything that is not a camera sighting unchanged,
    and for each completed instant its fixes (as position measurements with
    their own covariance) and its unpaired sightings (as bearings).
    """

    def __init__(self, cameras: Any) -> None:
        #: `cameras` is either the camera ids, or a mapping from id to what each can see
        #: (a View, or the same fields as a dict). With views, a new fix is also checked
        #: against the cameras that ought to see it.
        self.views: Dict[str, View] = {}
        if isinstance(cameras, dict):
            for camera_id, view in cameras.items():
                if view is not None:
                    self.views[camera_id] = view if isinstance(view, View) else View(**view)
        self.camera_ids = frozenset(cameras)
        self._pending: Dict[float, Dict[str, Sighting]] = {}
        self._seen: set = set()
        self._serial = 0
        #: Counts kept for the record: fixes made, and how many sightings were paired.
        self.fix_count = 0
        self.paired_sightings = 0
        self.single_sightings = 0
        self.vetoed_fixes = 0
        self.ghost_fixes = 0

    def feed(self, measurements: Sequence[Dict[str, Any]], now: float, tracker: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for m in measurements:
            if m.get("source_id") not in self.camera_ids or m.get("kind") != "bearing":
                out.append(m)
                continue
            if m["observation_id"] in self._seen:
                continue                             # a retried report is evidence already held
            self._seen.add(m["observation_id"])
            self._pending.setdefault(round(m["t"], 3), {})[m["observation_id"]] = Sighting.from_measurement(m)
        for instant in sorted(t for t in self._pending if t + HOLD_S <= now + 1e-9):
            out.extend(self._resolve(list(self._pending.pop(instant).values()), instant, now, tracker))
        return out

    def _resolve(self, sightings: List[Sighting], t: float, now: float, tracker: Any) -> List[Dict[str, Any]]:
        # 1. Sightings a held track explains go to that track.
        by_track: Dict[str, List[Sighting]] = {}
        unexplained: List[Sighting] = []
        states = []
        for track in tracker.tracks.values():
            ref = tracker._reference_state(track, t)
            if ref is not None:
                states.append((track.track_id, ref[0], ref[1], track.last_altitude_m))
        across: Dict[str, float] = {}             # observation -> how well its track is placed across the sight line
        near: Dict[str, Dict[str, float]] = {}    # observation -> the tracks it lies close to, and how close
        for s in sightings:
            offsets = sorted((found[0], track_id, found[1]) for track_id, x, p, altitude in states
                             if (found := _track_offset(s, x[0], x[1], p, altitude)) is not None
                             and found[0] <= TRACK_GATE_SIGMA)
            near[s.observation_id] = {track_id: off for off, track_id, _ in offsets}
            if offsets and (len(offsets) == 1 or offsets[1][0] > 2.0 * offsets[0][0] + 1.0):
                by_track.setdefault(offsets[0][1], []).append(s)
                across[s.observation_id] = offsets[0][2]
            else:
                unexplained.append(s)
        fixes: List[Tuple[Fix, Optional[str]]] = []   # (fix, the one track it may update; None = any, "" = a new object)
        singles: List[Tuple[Sighting, Optional[str]]] = []
        for track_id, group in by_track.items():
            # One sighting per viewpoint: two lenses on one pole cannot fix a position between them.
            distinct: Dict[Tuple[float, float], Sighting] = {}
            for s in group:
                distinct.setdefault((s.x, s.y), s)
            made = fit(list(distinct.values())) if len(distinct) >= 2 else None
            if made is not None:
                fixes.append((made, track_id))
                group = [s for s in group if s not in made.sightings]
            # A lone bearing may refine a track that is already well placed; it may not steer a lost one.
            singles.extend((s, track_id if across[s.observation_id] <= SINGLE_MAX_ACROSS_M else None) for s in group)
        # 2. What no track explains is paired with itself: new objects.
        new_fixes, leftover = pair_new(unexplained)
        for made in new_fixes:
            candidates = [near[s.observation_id] for s in made.sightings]
            if not any(candidates):
                # Nothing held is anywhere near any of these sightings: a new object.
                if self._contradicted(made, sightings):
                    self.vetoed_fixes += 1
                    leftover.extend(made.sightings)
                else:
                    fixes.append((made, ""))
                continue
            # Each sighting lies close to something already held. If one track is close to
            # all of them, this is that track seen again; otherwise it is two known objects
            # seen from two places, and the crossing is a ghost.
            shared = set(candidates[0]).intersection(*candidates[1:])
            if shared:
                fixes.append((made, min(shared, key=lambda track_id: sum(c[track_id] for c in candidates))))
            else:
                self.ghost_fixes += 1
                leftover.extend(made.sightings)
        singles.extend((s, None) for s in leftover)

        out: List[Dict[str, Any]] = []
        for made, owner in fixes:
            self._serial += 1
            self.fix_count += 1
            self.paired_sightings += len(made.sightings)
            out.append({
                "observation_id": f"fix-{self._serial:06d}", "t": t, "received_t": now, "source_id": FIX_SOURCE,
                "kind": "position", "x": made.x, "y": made.y, "z": made.z,
                "r": [list(made.covariance[0]), list(made.covariance[1])], "cameras": list(made.cameras),
                # Either a new object ("spawn"), or the one track this fix may update.
                **({"spawn": True} if owner == "" else {"track": owner}),
            })
        for s, track_id in singles:
            self.single_sightings += 1
            out.append({
                "observation_id": s.observation_id, "t": t, "received_t": now, "source_id": s.camera_id,
                "kind": "bearing", "bearing": s.bearing, "sensor_xy": (s.x, s.y), "sigma_rad": s.sigma_bearing,
                "range_m": s.range_hint, "camera": True, "track": track_id,
            })
        return out

    def _contradicted(self, made: Fix, sightings: Sequence[Sighting]) -> bool:
        """True when a camera that ought to see this fix reports nothing in its direction."""
        used = set(made.cameras)
        for camera_id, view in self.views.items():
            if camera_id in used:
                continue
            bearing = view.expects(made.x, made.y, made.z)
            if bearing is None:
                continue
            seen = any(abs((s.bearing - bearing + math.pi) % (2.0 * math.pi) - math.pi) <= 3.0 * s.sigma_bearing + math.radians(0.3)
                       for s in sightings if s.camera_id == camera_id)
            if not seen:
                return True
        return False
