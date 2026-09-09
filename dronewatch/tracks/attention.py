"""Explainable attention levels.

These are scenario-awareness rules applied to estimated geometry. They are not
evidence of hostile intent. Nothing here infers a weapon, an attacker, a decoy
or a control mode, and no calibrated confidence is produced.

Every level comes with the reason that produced it, so an operator can see why
a contact is highlighted rather than trusting a number.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

from .site import MonitoredSite
from .tracker import Freshness, Track, TrackState


class Priority(str, Enum):
    HIGH = "HIGH PRIORITY"
    WATCH = "WATCH"
    LOW = "LOW PRIORITY"


# Demonstration thresholds. Chosen to make the scenario legible, not derived
# from any operational standard.
CLOSING_SPEED_M_S = 2.0          # above this a contact counts as approaching
APPROACH_WINDOW_S = 45.0         # time-to-boundary that raises a contact
NEAR_BOUNDARY_FACTOR = 1.4       # within 1.4x the radius counts as near
#: A displayed level must be justified for this long before it changes, so that
#: modest measurement noise cannot make the list reorder continuously.
DWELL_S = 3.0


@dataclass(frozen=True)
class AttentionRule:
    priority: Priority
    reason: str
    #: What the judgement rests on: "measured" (fresh positional data),
    #: "predicted" (propagated without a measurement) or "stale" (too old to
    #: keep re-evaluating; the last measured band is held and flagged).
    basis: str = "measured"


def evaluate_priority(track: Track, site: MonitoredSite) -> AttentionRule:
    """The instantaneous rule, before any dwell is applied."""
    distance = site.range_to(track.x, track.y)
    closing = site.closing_speed(track.x, track.y, track.vx, track.vy)

    if site.is_inside(track.x, track.y):
        return AttentionRule(Priority.HIGH, "Inside monitored area")

    if closing > CLOSING_SPEED_M_S:
        seconds_to_boundary = (distance - site.radius_m) / closing
        if seconds_to_boundary <= APPROACH_WINDOW_S:
            return AttentionRule(Priority.HIGH, "Approaching boundary")
        if distance <= site.radius_m * NEAR_BOUNDARY_FACTOR:
            return AttentionRule(Priority.WATCH, "Near boundary")
        return AttentionRule(Priority.WATCH, "Approaching area")

    if closing < -CLOSING_SPEED_M_S:
        return AttentionRule(Priority.LOW, "Moving away")

    return AttentionRule(Priority.LOW, "Passing outside area")


class AttentionModel:
    """Applies dwell so displayed levels do not flicker on sensor noise.

    A candidate level must hold continuously for DWELL_S before it is shown.
    Tracking quality is kept separate: a stale contact keeps its priority band
    and gains an explanatory reason, because losing contact is not the same as
    the contact becoming unimportant.
    """

    def __init__(self, site: MonitoredSite, dwell_s: float = DWELL_S) -> None:
        self.site = site
        self.dwell_s = dwell_s
        self._shown: Dict[str, AttentionRule] = {}
        self._candidate: Dict[str, Tuple[AttentionRule, float]] = {}

    def _update_fresh(self, track: Track, now: float) -> AttentionRule:
        instantaneous = evaluate_priority(track, self.site)
        shown = self._shown.get(track.track_id)

        if shown is None:
            self._shown[track.track_id] = instantaneous
            self._candidate.pop(track.track_id, None)
            return self._decorate(track, instantaneous)

        if instantaneous.priority is shown.priority:
            # Same band: adopt the newer reason immediately, no dwell needed.
            self._shown[track.track_id] = instantaneous
            self._candidate.pop(track.track_id, None)
            return self._decorate(track, instantaneous)

        candidate = self._candidate.get(track.track_id)
        if candidate is None or candidate[0].priority is not instantaneous.priority:
            self._candidate[track.track_id] = (instantaneous, now)
            return self._decorate(track, shown)

        if now - candidate[1] >= self.dwell_s:
            self._shown[track.track_id] = instantaneous
            self._candidate.pop(track.track_id, None)
            return self._decorate(track, instantaneous)

        return self._decorate(track, shown)

    def update(self, track: Track, now: float) -> AttentionRule:  # noqa: F811
        if track.freshness is Freshness.STALE:
            # Old geometry must not keep producing confident new labels. Hold
            # the last band that was justified by fresh or predicted data, and
            # say so; do not re-evaluate closing speed from a frozen position.
            held = self._shown.get(track.track_id)
            band = held.priority if held else Priority.WATCH
            return AttentionRule(band, "Position update overdue", "stale")
        rule = self._update_fresh(track, now)
        basis = "predicted" if track.freshness is Freshness.PREDICTED else "measured"
        return AttentionRule(rule.priority, rule.reason, basis)

    def _decorate(self, track: Track, rule: AttentionRule) -> AttentionRule:
        return rule

    def forget(self, track_id: str) -> None:
        self._shown.pop(track_id, None)
        self._candidate.pop(track_id, None)


PRIORITY_ORDER = {Priority.HIGH: 0, Priority.WATCH: 1, Priority.LOW: 2}
