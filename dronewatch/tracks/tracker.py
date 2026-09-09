"""Multi-contact tracker: association, lifecycle and loss semantics.

The estimation mathematics lives in kalman.py. This module decides which
measurement belongs to which track, what a track is allowed to claim when no
measurement arrives, and how late or duplicate reports are treated. Those are
policies, and each is stated in TrackerConfig with its units and origin.

Three things are kept deliberately separate for every track, because they
answer different questions:

  lifecycle   TENTATIVE / CONFIRMED / ARCHIVED
              "Do we believe this is a real contact, and are we still
              retaining it?"  A retention timeout is a display policy, not a
              probability that the contact ceased to exist.
  freshness   UPDATED / PREDICTED / STALE
              "How old is the positional information behind the estimate?"
              PREDICTED means the state has been propagated without a
              measurement; the covariance says by how much that matters.
  source health   per sensor: REPORTING / DEGRADED / UNAVAILABLE / UNKNOWN
              "Is the sensor itself alive?"  Derived from heartbeats (scan
              records), never from the absence of detections: an empty sky
              and a dead radar look identical in the detection stream.

The display-facing TrackState (TENTATIVE / TRACKING / COASTING / STALE) is
derived from lifecycle and freshness and kept for the existing operator view.

Event-time semantics
  observed_at (t)   when the sensor made the measurement
  received_at       when it was delivered; process() is called in delivery
                    order with `now` = delivery time, so the estimator is
                    causal by construction
  state_time        the time the stored posterior refers to; always the time
                    of the last accepted positional measurement
  display time      whatever `now` advance_to() was last given; the displayed
                    position is the posterior predicted to that time, except
                    that a STALE track is displayed at its last measured
                    position (and its covariance keeps growing regardless)

Late data
  A measurement older than a track's state_time is handled by rolling that
  track back to the checkpoint taken before the first newer measurement,
  applying the late measurement in order, and replaying the newer ones. The
  result is exactly the posterior that in-order delivery would have produced.
  The window is bounded (reorder_window_s); older reports are rejected with a
  reason and never applied as if they were current.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from . import kalman as K


class TrackState(str, Enum):
    TENTATIVE = "TENTATIVE"   # seen, not yet confirmed
    TRACKING = "TRACKING"     # confirmed, positional information is fresh
    COASTING = "COASTING"     # confirmed, prediction only for a short while
    STALE = "STALE"           # confirmed, prediction only for too long to trust


class Lifecycle(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    ARCHIVED = "ARCHIVED"


class Freshness(str, Enum):
    UPDATED = "UPDATED"
    PREDICTED = "PREDICTED"
    STALE = "STALE"


class SourceState(str, Enum):
    REPORTING = "REPORTING"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TrackerConfig:
    #: Continuous white-acceleration PSD w, m^2/s^3, isotropic. Origin: chosen so
    #: that velocity uncertainty grows by sqrt(w t) ~ 6 m/s over 10 s, which
    #: tolerates the demonstration's gentle turns; checked by the exactness sweep
    #: in tests/test_tracking.py and by NEES in experiments (Layer A is matched).
    process_noise_w: float = 4.0
    #: Default radar position noise, one sigma, metres. Used when a measurement
    #: does not carry its own covariance.
    measurement_sigma_m: float = 10.0
    #: Default bearing noise, one sigma, radians (2 degrees).
    bearing_sigma_rad: float = math.radians(2.0)
    #: Gate on the normalised innovation squared, position measurements
    #: (2 dof). 25 is beyond the 99.99% point of chi2(2); it admits a
    #: constant-velocity filter's lag through a gentle turn while staying far
    #: tighter than the spacing between contacts in the demonstration.
    gate_chi2: float = 25.0
    #: Gate for 1-dof (bearing) measurements. 13.0 ~ 99.97% of chi2(1).
    gate_chi2_1dof: float = 13.0
    #: Two candidates whose -2 ln likelihood differ by less than this are
    #: recorded as an ambiguous association (likelihood ratio < e).
    ambiguity_margin: float = 2.0
    #: Late measurements older than this relative to a track's state are
    #: rejected. Must exceed the transport delay spread (0.2 s here) with
    #: margin; larger windows cost more replay work per late report.
    reorder_window_s: float = 1.5
    #: Hits required before a tentative track is confirmed.
    confirm_hits: int = 3
    #: A tentative track is discarded if it is not confirmed this quickly.
    tentative_timeout_s: float = 4.0
    #: Freshness thresholds, seconds since the last accepted positional
    #: measurement. Radar runs at 2 Hz: 2.5 s ~ five consecutive misses.
    coast_after_s: float = 2.5
    stale_after_s: float = 8.0
    #: Retention: a confirmed track is archived after this long without a
    #: positional measurement. This is a display policy.
    drop_after_s: float = 25.0
    #: Initial velocity uncertainty, m/s, for a track started from one
    #: position measurement (velocity prior centred on zero).
    initial_velocity_sigma: float = 30.0
    #: A source is UNAVAILABLE when its heartbeat is older than this many of
    #: its own scan intervals.
    heartbeat_tolerance_scans: float = 2.5


@dataclass
class Measured:
    x: float
    y: float
    t: float
    source_id: str


@dataclass
class Checkpoint:
    """State before a measurement was applied, and the measurement itself."""
    t_before: float
    x_before: List[float]
    p_before: K.Matrix
    measurement: dict


@dataclass
class Track:
    track_id: str
    #: Posterior [x, y, vx, vy] at state_time, simulation metres and m/s.
    state: List[float]
    covariance: K.Matrix
    created_at: float = 0.0
    state_time: float = 0.0
    hits: int = 1
    misses: int = 0
    lifecycle: Lifecycle = Lifecycle.TENTATIVE
    freshness: Freshness = Freshness.UPDATED
    history: List[Tuple[float, float, float]] = field(default_factory=list)
    last_altitude_m: Optional[float] = None
    last_measurement: Optional[Measured] = None
    #: Last time each source contributed an accepted measurement.
    sources: Dict[str, float] = field(default_factory=dict)
    #: (-2 ln L) margin between best and second-best candidate at the last
    #: association; None when there was no competitor. Small means ambiguous.
    last_margin: Optional[float] = None
    ambiguous_count: int = 0
    checkpoints: Deque[Checkpoint] = field(default_factory=deque)
    #: Display-time cache, set by advance_to().
    display_time: float = 0.0
    display_state: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    display_cov: K.Matrix = field(default_factory=lambda: K.identity(4))
    frozen_position: Optional[Tuple[float, float]] = None

    def __post_init__(self) -> None:
        # A freshly built track displays its own posterior until advance_to()
        # supplies a display time.
        if self.display_state == [0.0, 0.0, 0.0, 0.0] and self.state != [0.0, 0.0, 0.0, 0.0]:
            self.display_state = list(self.state)
            self.display_cov = [row[:] for row in self.covariance]
        self.display_time = self.state_time

    # -- compatibility surface used by frames.py, attention.py and tests -------

    @property
    def last_update_at(self) -> float:
        return self.state_time

    @last_update_at.setter
    def last_update_at(self, value: float) -> None:
        self.state_time = value

    @property
    def status(self) -> TrackState:
        if self.lifecycle is Lifecycle.TENTATIVE:
            return TrackState.TENTATIVE
        if self.freshness is Freshness.UPDATED:
            return TrackState.TRACKING
        if self.freshness is Freshness.PREDICTED:
            return TrackState.COASTING
        return TrackState.STALE

    @status.setter
    def status(self, value: TrackState) -> None:
        """Set lifecycle and freshness from a display state (compatibility)."""
        if value is TrackState.TENTATIVE:
            self.lifecycle = Lifecycle.TENTATIVE
            return
        self.lifecycle = Lifecycle.CONFIRMED
        self.freshness = {TrackState.TRACKING: Freshness.UPDATED,
                          TrackState.COASTING: Freshness.PREDICTED,
                          TrackState.STALE: Freshness.STALE}[value]
        if value is TrackState.STALE and self.frozen_position is None:
            src = self.last_measurement
            self.frozen_position = (src.x, src.y) if src else (self.display_state[0], self.display_state[1])
        if value is not TrackState.STALE:
            self.frozen_position = None

    @property
    def x(self) -> float:
        return self.frozen_position[0] if self.frozen_position else self.display_state[0]

    @property
    def y(self) -> float:
        return self.frozen_position[1] if self.frozen_position else self.display_state[1]

    @property
    def vx(self) -> float:
        return self.display_state[2]

    @property
    def vy(self) -> float:
        return self.display_state[3]

    @property
    def speed_m_s(self) -> float:
        return math.hypot(self.vx, self.vy)

    @property
    def heading_deg(self) -> float:
        return (math.degrees(math.atan2(self.vy, self.vx)) + 360.0) % 360.0

    @property
    def is_visible(self) -> bool:
        """Tentative tracks are not shown as contacts."""
        return self.lifecycle is Lifecycle.CONFIRMED

    def predicted_at(self, t: float, w: float) -> Tuple[List[float], K.Matrix]:
        """Posterior propagated to time t >= state_time. No measurement, no
        pseudo-measurement: just F and Q."""
        return K.predict(self.state, self.covariance, max(0.0, t - self.state_time), w)


_track_dataclass_init = Track.__init__


def _track_init(self, *args, last_update_at: Optional[float] = None, **kwargs) -> None:
    """Accept the older keyword `last_update_at` as an alias of state_time."""
    if last_update_at is not None:
        kwargs.setdefault("state_time", last_update_at)
    _track_dataclass_init(self, *args, **kwargs)


Track.__init__ = _track_init  # type: ignore[assignment]


@dataclass
class Source:
    source_id: str
    interval_s: float
    nominal_sigma_m: Optional[float] = None
    last_scan_t: Optional[float] = None
    last_detection_t: Optional[float] = None
    reported_sigma_m: Optional[float] = None
    state: SourceState = SourceState.UNKNOWN


class Tracker:
    """Processes observations in delivery order and maintains tracks."""

    def __init__(self, config: Optional[TrackerConfig] = None) -> None:
        self.config = config or TrackerConfig()
        self.tracks: Dict[str, Track] = {}
        self.archived: List[str] = []
        self.sources: Dict[str, Source] = {}
        self._next_id = 1
        self._seen_observation_ids: set = set()
        self._confirmed_ever: set = set()
        self.duplicate_count = 0
        self.late_applied_count = 0
        self.late_rejected_count = 0
        self.rejected_invalid_count = 0
        self.unassigned_nonpositional_count = 0
        self.spawn_count = 0
        self.ambiguous_association_count = 0
        #: Accepted-update innovation diagnostics: (t, nis, dof, track_id).
        #: These are gated, nearest-neighbour-selected residuals, so they are
        #: not an unbiased sample of the innovation distribution.
        self.nis_log: List[Tuple[float, float, int, str]] = []
        #: Sources that carry evidence but no geometry (RF activity, class
        #: labels). Their reports are counted, never used to move a state.
        self.evidence_sources: set = set()
        self.evidence_count: Dict[str, int] = {}

    @property
    def created_count(self) -> int:
        """Tracks that were ever confirmed (not the number of spawns)."""
        return len(self._confirmed_ever)

    @property
    def late_count(self) -> int:
        return self.late_applied_count + self.late_rejected_count

    # -- sources ------------------------------------------------------------

    def declare_source(self, source_id: str, interval_s: float,
                       nominal_sigma_m: Optional[float] = None,
                       evidence_only: bool = False) -> None:
        self.sources.setdefault(source_id, Source(source_id, interval_s, nominal_sigma_m))
        if evidence_only:
            self.evidence_sources.add(source_id)

    def heartbeat(self, source_id: str, t: float, reported_sigma_m: Optional[float] = None) -> None:
        """A scan record: the sensor ran at time t, whether or not it detected."""
        src = self.sources.get(source_id)
        if src is None:
            src = Source(source_id, interval_s=1.0)
            self.sources[source_id] = src
        if src.last_scan_t is None or t >= src.last_scan_t:
            src.last_scan_t = t
            src.reported_sigma_m = reported_sigma_m

    def _refresh_sources(self, now: float) -> None:
        for src in self.sources.values():
            if src.last_scan_t is None:
                src.state = SourceState.UNKNOWN
                continue
            if now - src.last_scan_t > self.config.heartbeat_tolerance_scans * src.interval_s:
                src.state = SourceState.UNAVAILABLE
            elif (src.reported_sigma_m is not None and src.nominal_sigma_m
                  and src.reported_sigma_m > 1.5 * src.nominal_sigma_m):
                src.state = SourceState.DEGRADED
            else:
                src.state = SourceState.REPORTING

    # -- lifecycle ------------------------------------------------------------

    def _new_id(self) -> str:
        display_id = f"DW-{self._next_id:03d}"
        self._next_id += 1
        self.spawn_count += 1
        return display_id

    def _spawn(self, m: dict, r: K.Matrix) -> Track:
        """Start a tentative track from one position measurement.

        Velocity prior is zero with initial_velocity_sigma; a two-point
        initialisation would be sharper but is not needed at 2 Hz.
        """
        v2 = self.config.initial_velocity_sigma ** 2
        cov = [
            [r[0][0], r[0][1], 0.0, 0.0],
            [r[1][0], r[1][1], 0.0, 0.0],
            [0.0, 0.0, v2, 0.0],
            [0.0, 0.0, 0.0, v2],
        ]
        track = Track(
            track_id=self._new_id(), state=[m["x"], m["y"], 0.0, 0.0], covariance=cov,
            state_time=m["t"], created_at=m["t"], history=[(m["t"], m["x"], m["y"])],
            last_altitude_m=m.get("z"),
            last_measurement=Measured(m["x"], m["y"], m["t"], m.get("source_id", "radar")),
        )
        track.sources[track.last_measurement.source_id] = m["t"]
        track.display_time = m["t"]
        track.display_state = list(track.state)
        track.display_cov = [row[:] for row in cov]
        self.tracks[track.track_id] = track
        return track

    # -- measurement models -------------------------------------------------

    def _model_and_r(self, m: dict):
        kind = m.get("kind", "position")
        if kind == "position":
            if "r" in m and m["r"] is not None:
                r = m["r"]
            else:
                s2 = (m.get("sigma_m") or self.config.measurement_sigma_m) ** 2
                r = [[s2, 0.0], [0.0, s2]]
            return K.position_model(), r, [m["x"], m["y"]], self.config.gate_chi2, True
        if kind == "bearing":
            sx, sy = m["sensor_xy"]
            s2 = (m.get("sigma_rad") or self.config.bearing_sigma_rad) ** 2
            return K.bearing_model(sx, sy), [[s2]], [m["bearing"]], self.config.gate_chi2_1dof, False
        raise K.MeasurementRejected(f"unknown measurement kind {kind!r}")

    # -- late data ------------------------------------------------------------

    def _reference_state(self, track: Track, t: float):
        """(x, P, checkpoint_index) for gating a measurement at time t.

        In-order: the posterior predicted to t. Late but inside the window:
        the checkpoint before the first newer measurement, predicted to t.
        Older than the window: None.
        """
        if t >= track.state_time:
            x, p = track.predicted_at(t, self.config.process_noise_w)
            return x, p, None
        if track.state_time - t > self.config.reorder_window_s:
            return None
        idx = None
        for i, cp in enumerate(track.checkpoints):
            if cp.measurement["t"] > t:
                idx = i
                break
        if idx is None:
            return None
        cp = track.checkpoints[idx]
        if t < cp.t_before:
            return None
        x, p = K.predict(cp.x_before, cp.p_before, t - cp.t_before, self.config.process_noise_w)
        return x, p, idx

    def _apply(self, track: Track, m: dict, model, r, z, inn: Optional[K.Innovation]) -> None:
        dt = m["t"] - track.state_time
        x_minus, p_minus = K.predict(track.state, track.covariance, dt, self.config.process_noise_w)
        x_plus, p_plus, _ = K.update(x_minus, p_minus, z, r, model, precomputed=inn)
        track.checkpoints.append(Checkpoint(track.state_time, list(track.state),
                                            [row[:] for row in track.covariance], m))
        track.state, track.covariance, track.state_time = x_plus, p_plus, m["t"]

    def _apply_late(self, track: Track, idx: int, m: dict) -> None:
        """Roll back to the checkpoint at idx, apply m, replay the rest."""
        cp = track.checkpoints[idx]
        later = [track.checkpoints[i].measurement for i in range(idx, len(track.checkpoints))]
        for _ in range(len(track.checkpoints) - idx):
            track.checkpoints.pop()
        track.state, track.covariance, track.state_time = list(cp.x_before), [row[:] for row in cp.p_before], cp.t_before
        for item in sorted(later + [m], key=lambda q: (q["t"], q["observation_id"])):
            model, r, z, _, _ = self._model_and_r(item)
            self._apply(track, item, model, r, z, None)

    def _trim_checkpoints(self, track: Track) -> None:
        limit = track.state_time - self.config.reorder_window_s
        while track.checkpoints and track.checkpoints[0].measurement["t"] < limit:
            track.checkpoints.popleft()

    # -- public API ------------------------------------------------------------

    def process(self, observations: Sequence[dict], now: float) -> None:
        """Feed observations already ordered by delivery time, up to `now`.

        Each item needs `observation_id`, `t` (simulation seconds the sensor
        made the measurement) and, for kind "position" (default), `x`, `y`,
        optional `z`, optional `sigma_m` or `r`. For kind "bearing": `bearing`
        (radians, mathematical convention), `sensor_xy`, optional `sigma_rad`.
        Optional `source_id` on all.
        """
        w = self.config.process_noise_w
        for m in observations:
            identifier = m["observation_id"]
            if identifier in self._seen_observation_ids:
                # A retry is evidence already used. Counting it again would
                # shrink covariance twice and confirm on one report.
                self.duplicate_count += 1
                continue
            self._seen_observation_ids.add(identifier)
            source_id = m.get("source_id", "radar")
            if source_id in self.evidence_sources or m.get("kind") == "evidence":
                # Non-positional evidence: it says something happened, not where.
                # Without geometry it cannot be attributed to a track, so it is
                # preserved as a source-level count and never tightens anything.
                self.evidence_count[source_id] = self.evidence_count.get(source_id, 0) + 1
                src = self.sources.get(source_id)
                if src is not None:
                    src.last_detection_t = max(src.last_detection_t or -math.inf, m["t"])
                continue

            try:
                model, r, z, gate, positional = self._model_and_r(m)
                if positional and not (math.isfinite(m["x"]) and math.isfinite(m["y"])):
                    raise K.MeasurementRejected("measurement not finite")
                K.validate_covariance(r, len(z))
            except (K.MeasurementRejected, KeyError, TypeError) as exc:
                self.rejected_invalid_count += 1
                continue

            t = m["t"]
            candidates = []          # (score, track_id, checkpoint_idx, innovation)
            any_too_old = False
            for track in self.tracks.values():
                if track.freshness is Freshness.STALE and not positional:
                    continue
                ref = self._reference_state(track, t)
                if ref is None:
                    if t < track.state_time:
                        any_too_old = True
                    continue
                x_ref, p_ref, idx = ref
                try:
                    inn = K.innovation(x_ref, p_ref, z, r, model)
                except K.MeasurementRejected:
                    continue
                if inn.nis > gate:
                    continue
                # -2 ln likelihood up to a constant: distance plus log-volume,
                # so an enormous covariance cannot make everything a good match.
                l = K.cholesky(inn.covariance)
                log_det = 2.0 * sum(math.log(l[i][i]) for i in range(len(l)))
                candidates.append((inn.nis + log_det, track.track_id, idx, inn))

            if not candidates:
                if any_too_old:
                    self.late_rejected_count += 1
                    continue
                if positional:
                    self._spawn(m, r)
                else:
                    # A bearing alone does not fix a position; it cannot start a
                    # track. Kept as a count, not silently dropped.
                    self.unassigned_nonpositional_count += 1
                continue

            candidates.sort(key=lambda c: c[0])
            score, best_id, idx, inn = candidates[0]
            track = self.tracks[best_id]
            if len(candidates) > 1:
                margin = candidates[1][0] - score
                track.last_margin = margin
                if margin < self.config.ambiguity_margin:
                    track.ambiguous_count += 1
                    self.ambiguous_association_count += 1
            else:
                track.last_margin = None

            self.nis_log.append((t, inn.nis, len(z), best_id))
            if idx is None:
                self._apply(track, m, model, r, z, inn)
            else:
                self.late_applied_count += 1
                self._apply_late(track, idx, m)
            self._trim_checkpoints(track)

            track.hits += 1
            track.misses = 0
            track.sources[source_id] = max(track.sources.get(source_id, -math.inf), t)
            if positional:
                if track.last_measurement is None or t >= track.last_measurement.t:
                    track.last_measurement = Measured(m["x"], m["y"], t, source_id)
                if m.get("z") is not None:
                    track.last_altitude_m = m["z"]
                src = self.sources.get(source_id)
                if src is not None:
                    src.last_detection_t = max(src.last_detection_t or -math.inf, t)
            if track.lifecycle is Lifecycle.TENTATIVE and track.hits >= self.config.confirm_hits:
                track.lifecycle = Lifecycle.CONFIRMED
                self._confirmed_ever.add(track.track_id)
            track.history.append((t, track.state[0], track.state[1]))
            del track.history[:-40]

        self.advance_to(now)

    def advance_to(self, now: float) -> None:
        """Age tracks to `now`: freshness, retention and the display state.

        Prediction here is display only; the stored posterior is untouched.
        """
        cfg, w = self.config, self.config.process_noise_w
        self._refresh_sources(now)
        for track_id in list(self.tracks):
            track = self.tracks[track_id]
            # Age of positional information, not of any measurement.
            pos_t = track.last_measurement.t if track.last_measurement else track.state_time
            age = now - pos_t

            if track.lifecycle is Lifecycle.TENTATIVE:
                if age > cfg.tentative_timeout_s:
                    del self.tracks[track_id]
                    continue
            elif age > cfg.drop_after_s:
                track.lifecycle = Lifecycle.ARCHIVED
                self.archived.append(track_id)
                del self.tracks[track_id]
                continue

            if age > cfg.stale_after_s:
                track.freshness = Freshness.STALE
            elif age > cfg.coast_after_s:
                track.freshness = Freshness.PREDICTED
            else:
                track.freshness = Freshness.UPDATED

            # Display state: always the honest prediction; covariance keeps
            # growing through a blackout even though a STALE marker is held at
            # the last measured position.
            x_now, p_now = track.predicted_at(now, w)
            track.display_time = now
            track.display_state = x_now
            track.display_cov = p_now
            if track.freshness is Freshness.STALE:
                if track.frozen_position is None and track.last_measurement is not None:
                    track.frozen_position = (track.last_measurement.x, track.last_measurement.y)
            else:
                track.frozen_position = None

    def visible_tracks(self) -> List[Track]:
        return [track for track in self.tracks.values() if track.is_visible]
