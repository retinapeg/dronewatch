"""Constant-velocity tracker with gated association.

Scope, stated plainly: one positional sensor, a four-state constant-velocity
Kalman filter, nearest-neighbour association inside a chi-squared gate, and a
simple confirm/coast/stale lifecycle. That is all. It is a baseline that makes
the preview legible, not a validated tracking system.

Assumptions are explicit in TrackerConfig so they can be argued with.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple


class TrackState(str, Enum):
    TENTATIVE = "TENTATIVE"   # seen, not yet confirmed
    TRACKING = "TRACKING"     # confirmed and being updated
    COASTING = "COASTING"     # no recent update; still predicting
    STALE = "STALE"           # update overdue; last known position held


@dataclass(frozen=True)
class TrackerConfig:
    #: Assumed sensor position noise, one standard deviation, in metres.
    measurement_sigma_m: float = 10.0
    #: Process noise as an acceleration standard deviation, m/s^2.
    process_accel_sigma: float = 2.2
    #: Chi-squared gate on 2 degrees of freedom. 9.21 is the 99% point;
    #: 16.0 is deliberately looser so a manoeuvre does not split a track.
    # chi-squared, 2 dof. 25 admits a constant-velocity filter's lag through a
    # gentle turn while staying far tighter than the spacing between contacts.
    gate_chi2: float = 25.0
    #: Hits required before a tentative track is confirmed.
    confirm_hits: int = 3
    #: A tentative track is discarded if it is not confirmed this quickly.
    tentative_timeout_s: float = 4.0
    #: Radar runs at 2 Hz, so ~5 consecutive misses.
    coast_after_s: float = 2.5
    #: Beyond this the estimate is not trustworthy; hold the last position.
    stale_after_s: float = 8.0
    #: Give up entirely.
    drop_after_s: float = 25.0
    #: Initial velocity uncertainty, m/s.
    initial_velocity_sigma: float = 30.0


# --- small matrix helpers (4x4 at most; numpy is not a dependency) ----------

Matrix = List[List[float]]


def _identity(n: int) -> Matrix:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def _matmul(a: Matrix, b: Matrix) -> Matrix:
    rows, inner, cols = len(a), len(b), len(b[0])
    return [
        [sum(a[i][k] * b[k][j] for k in range(inner)) for j in range(cols)]
        for i in range(rows)
    ]


def _transpose(a: Matrix) -> Matrix:
    return [list(row) for row in zip(*a)]


def _add(a: Matrix, b: Matrix) -> Matrix:
    return [[a[i][j] + b[i][j] for j in range(len(a[0]))] for i in range(len(a))]


def _invert2(m: Matrix) -> Optional[Matrix]:
    determinant = m[0][0] * m[1][1] - m[0][1] * m[1][0]
    if abs(determinant) < 1e-12:
        return None
    return [[m[1][1] / determinant, -m[0][1] / determinant],
            [-m[1][0] / determinant, m[0][0] / determinant]]


@dataclass
class Track:
    track_id: str
    #: State vector [x, y, vx, vy] in simulation metres and metres/second.
    state: List[float]
    covariance: Matrix
    created_at: float
    last_update_at: float
    hits: int = 1
    misses: int = 0
    status: TrackState = TrackState.TENTATIVE
    history: List[Tuple[float, float, float]] = field(default_factory=list)
    last_altitude_m: Optional[float] = None
    #: Position frozen when the track went stale, so a stale contact does not
    #: keep drifting across the display on the strength of an old estimate.
    frozen_position: Optional[Tuple[float, float]] = None

    @property
    def x(self) -> float:
        return self.frozen_position[0] if self.frozen_position else self.state[0]

    @property
    def y(self) -> float:
        return self.frozen_position[1] if self.frozen_position else self.state[1]

    @property
    def vx(self) -> float:
        return 0.0 if self.frozen_position else self.state[2]

    @property
    def vy(self) -> float:
        return 0.0 if self.frozen_position else self.state[3]

    @property
    def speed_m_s(self) -> float:
        return math.hypot(self.vx, self.vy)

    @property
    def heading_deg(self) -> float:
        return (math.degrees(math.atan2(self.vy, self.vx)) + 360.0) % 360.0

    @property
    def is_visible(self) -> bool:
        """Tentative tracks are not shown as contacts."""
        return self.status is not TrackState.TENTATIVE


class Tracker:
    """Processes observations in delivery order and maintains tracks."""

    def __init__(self, config: Optional[TrackerConfig] = None) -> None:
        self.config = config or TrackerConfig()
        self.tracks: Dict[str, Track] = {}
        self._next_id = 1
        self._seen_observation_ids: set = set()
        self._confirmed_ever: set = set()
        self.duplicate_count = 0
        self.late_count = 0
        self.spawn_count = 0

    @property
    def created_count(self) -> int:
        """Tracks that were ever confirmed.

        Deliberately not the number of tracks spawned. A late, unassociated
        report briefly spawns a tentative track that is dropped in the same
        pass, so counting spawns would overstate fragmentation in any scenario
        with delayed delivery.
        """
        return len(self._confirmed_ever)

    # -- lifecycle ---------------------------------------------------------

    def _new_id(self) -> str:
        display_id = f"DW-{self._next_id:03d}"
        self._next_id += 1
        self.spawn_count += 1
        return display_id

    def _spawn(self, x: float, y: float, t: float, altitude: Optional[float]) -> Track:
        sigma = self.config.measurement_sigma_m
        velocity_variance = self.config.initial_velocity_sigma ** 2
        covariance = [
            [sigma ** 2, 0.0, 0.0, 0.0],
            [0.0, sigma ** 2, 0.0, 0.0],
            [0.0, 0.0, velocity_variance, 0.0],
            [0.0, 0.0, 0.0, velocity_variance],
        ]
        track = Track(
            track_id=self._new_id(), state=[x, y, 0.0, 0.0], covariance=covariance,
            created_at=t, last_update_at=t, history=[(t, x, y)],
            last_altitude_m=altitude,
        )
        self.tracks[track.track_id] = track
        return track

    # -- filter ------------------------------------------------------------

    def _predict(self, track: Track, dt: float) -> None:
        if dt <= 0:
            return
        transition = [
            [1.0, 0.0, dt, 0.0],
            [0.0, 1.0, 0.0, dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        state = track.state
        track.state = [
            state[0] + state[2] * dt,
            state[1] + state[3] * dt,
            state[2],
            state[3],
        ]
        q = self.config.process_accel_sigma ** 2
        dt2, dt3, dt4 = dt * dt, dt ** 3, dt ** 4
        process = [
            [dt4 / 4 * q, 0.0, dt3 / 2 * q, 0.0],
            [0.0, dt4 / 4 * q, 0.0, dt3 / 2 * q],
            [dt3 / 2 * q, 0.0, dt2 * q, 0.0],
            [0.0, dt3 / 2 * q, 0.0, dt2 * q],
        ]
        track.covariance = _add(
            _matmul(_matmul(transition, track.covariance), _transpose(transition)),
            process,
        )

    def _innovation(self, track: Track, x: float, y: float):
        """Returns (residual, innovation covariance) for a position measurement."""
        sigma2 = self.config.measurement_sigma_m ** 2
        p = track.covariance
        s = [[p[0][0] + sigma2, p[0][1]], [p[1][0], p[1][1] + sigma2]]
        return [x - track.state[0], y - track.state[1]], s

    def _mahalanobis(self, track: Track, x: float, y: float) -> Optional[float]:
        residual, s = self._innovation(track, x, y)
        inverse = _invert2(s)
        if inverse is None:
            return None
        return (
            residual[0] * (inverse[0][0] * residual[0] + inverse[0][1] * residual[1])
            + residual[1] * (inverse[1][0] * residual[0] + inverse[1][1] * residual[1])
        )

    def _update(self, track: Track, x: float, y: float, t: float,
                altitude: Optional[float]) -> None:
        residual, s = self._innovation(track, x, y)
        inverse = _invert2(s)
        if inverse is None:
            return
        p = track.covariance
        # K = P H^T S^-1, with H selecting position.
        ph = [[p[i][0], p[i][1]] for i in range(4)]
        gain = _matmul(ph, inverse)
        track.state = [
            track.state[i] + gain[i][0] * residual[0] + gain[i][1] * residual[1]
            for i in range(4)
        ]
        kh = [[gain[i][0] if j == 0 else gain[i][1] if j == 1 else 0.0
               for j in range(4)] for i in range(4)]
        factor = [[_identity(4)[i][j] - kh[i][j] for j in range(4)] for i in range(4)]
        track.covariance = _matmul(factor, p)

        track.last_update_at = t
        track.hits += 1
        track.misses = 0
        track.frozen_position = None
        if altitude is not None:
            track.last_altitude_m = altitude
        if track.status is TrackState.TENTATIVE and track.hits >= self.config.confirm_hits:
            track.status = TrackState.TRACKING
            self._confirmed_ever.add(track.track_id)
        elif track.status in (TrackState.COASTING, TrackState.STALE):
            track.status = TrackState.TRACKING
        track.history.append((t, track.state[0], track.state[1]))
        del track.history[:-40]

    # -- public API --------------------------------------------------------

    def process(self, observations: Sequence[dict], now: float) -> None:
        """Feed observations already ordered by delivery time.

        Each item needs `observation_id`, `t` (simulation seconds the sensor
        made the measurement), `x`, `y`, and optionally `z`.
        """
        for observation in observations:
            identifier = observation["observation_id"]
            if identifier in self._seen_observation_ids:
                # A duplicate delivery is evidence we already used. Counting it
                # again would let one report create or strengthen two contacts.
                self.duplicate_count += 1
                continue
            self._seen_observation_ids.add(identifier)

            t = observation["t"]
            x, y = observation["x"], observation["y"]
            altitude = observation.get("z")

            best_id, best_distance = None, None
            for track in self.tracks.values():
                if track.status is TrackState.STALE:
                    continue
                dt = t - track.last_update_at
                if dt < 0:
                    # Late report, older than this track's estimate. Using it
                    # would rewind the displayed position, so it is discarded.
                    continue
                candidate = Track(
                    track_id=track.track_id, state=list(track.state),
                    covariance=[row[:] for row in track.covariance],
                    created_at=track.created_at, last_update_at=track.last_update_at,
                )
                self._predict(candidate, dt)
                distance = self._mahalanobis(candidate, x, y)
                if distance is None or distance > self.config.gate_chi2:
                    continue
                if best_distance is None or distance < best_distance:
                    best_id, best_distance = track.track_id, distance

            if best_id is None:
                if any(t < track.last_update_at for track in self.tracks.values()):
                    self.late_count += 1
                self._spawn(x, y, t, altitude)
                continue

            track = self.tracks[best_id]
            self._predict(track, t - track.last_update_at)
            self._update(track, x, y, t, altitude)

        self.advance_to(now)

    def advance_to(self, now: float) -> None:
        """Age tracks to `now` and update lifecycle states."""
        config = self.config
        for track_id in list(self.tracks):
            track = self.tracks[track_id]
            age = now - track.last_update_at

            if track.status is TrackState.TENTATIVE:
                # An unconfirmed candidate either gets confirmed by later hits or
                # expires. It must never age into COASTING, which would put a
                # never-confirmed contact on the operator's screen.
                if age > config.tentative_timeout_s:
                    del self.tracks[track_id]
                continue
            if age > config.drop_after_s:
                del self.tracks[track_id]
                continue

            if age > config.stale_after_s:
                if track.frozen_position is None:
                    # Freeze at the last believable estimate. Continuing to
                    # extrapolate would invent a position for a contact we have
                    # not heard from.
                    track.frozen_position = (track.state[0], track.state[1])
                track.status = TrackState.STALE
            elif age > config.coast_after_s:
                track.status = TrackState.COASTING
            elif track.status in (TrackState.COASTING, TrackState.STALE):
                track.status = TrackState.TRACKING

    def visible_tracks(self) -> List[Track]:
        return [track for track in self.tracks.values() if track.is_visible]
