"""Authorisation and the simulated engagement lifecycle.

Everything here is abstract simulation. There are no weapon-control interfaces,
no firing commands, no guidance, and no real-world coordinates.

The single hard boundary: no engagement state at or beyond AUTHORISED can be
reached without an AuthorisationRecord that actually covers the track.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import FrozenSet, List, Optional, Tuple

from .enums import (
    AuthorityKind,
    AuthorisationScope,
    Decision,
    EngagementState,
)


@dataclass(frozen=True)
class AuthorisationRecord:
    """A decision, and exactly which tracks it covers.

    Coverage is frozen at decision time and enumerated explicitly. It is never
    re-derived from group membership at read time, because membership can change
    after the decision was taken.
    """

    authorisation_id: str
    decision: Decision
    scope: AuthorisationScope
    authority_kind: AuthorityKind
    authority_id: str
    decided_at: datetime
    covered_track_ids: FrozenSet[str]
    excluded_track_ids: FrozenSet[str] = frozenset()
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.decided_at.tzinfo is None:
            raise ValueError("decided_at must be timezone-aware")
        if not self.covered_track_ids:
            raise ValueError("an authorisation must cover at least one track")
        if not self.excluded_track_ids <= self.covered_track_ids:
            raise ValueError("excluded tracks must be a subset of covered tracks")
        if self.scope is AuthorisationScope.TRACK:
            if len(self.covered_track_ids) != 1:
                raise ValueError("a track-scoped authorisation covers exactly one track")
            if self.excluded_track_ids:
                raise ValueError("a track-scoped authorisation cannot exclude tracks")

    def covers(self, track_id: str) -> bool:
        return track_id in self.covered_track_ids and track_id not in self.excluded_track_ids

    @property
    def authorises(self) -> bool:
        return self.decision is Decision.AUTHORISED


def effective_authorisation(
    track_id: str,
    track_authorisation: Optional[AuthorisationRecord] = None,
    group_authorisation: Optional[AuthorisationRecord] = None,
) -> Optional[AuthorisationRecord]:
    """Resolve modes A to D.

    A per-track decision always wins over a group decision covering the same
    track. That ordering is what makes a per-track override meaningful.
    """
    if track_authorisation is not None and track_authorisation.covers(track_id):
        return track_authorisation
    if group_authorisation is not None and group_authorisation.covers(track_id):
        return group_authorisation
    return None


# States that may only be entered once a covering authorisation exists.
AUTHORISATION_REQUIRED_STATES: FrozenSet[EngagementState] = frozenset(
    {
        EngagementState.AUTHORISED,
        EngagementState.EFFECTOR_ASSIGNED,
        EngagementState.ENGAGEMENT_PENDING,
        EngagementState.SIMULATED_ENGAGEMENT,
        EngagementState.DEFEAT_CONFIRMED,
        EngagementState.DEFEAT_UNCONFIRMED,
        EngagementState.RE_ENGAGEMENT_REQUIRED,
    }
)

_ALLOWED: dict = {
    EngagementState.NONE: {EngagementState.RECOMMENDED, EngagementState.CLOSED},
    EngagementState.RECOMMENDED: {
        EngagementState.DECISION_PENDING,
        EngagementState.CLOSED,
    },
    EngagementState.DECISION_PENDING: {
        EngagementState.AUTHORISED,
        EngagementState.REJECTED,
        EngagementState.CLOSED,
    },
    EngagementState.AUTHORISED: {
        EngagementState.EFFECTOR_ASSIGNED,
        EngagementState.CLOSED,
    },
    EngagementState.REJECTED: {EngagementState.CLOSED},
    EngagementState.EFFECTOR_ASSIGNED: {
        EngagementState.ENGAGEMENT_PENDING,
        EngagementState.CLOSED,
    },
    EngagementState.ENGAGEMENT_PENDING: {
        EngagementState.SIMULATED_ENGAGEMENT,
        EngagementState.CLOSED,
    },
    EngagementState.SIMULATED_ENGAGEMENT: {
        EngagementState.DEFEAT_CONFIRMED,
        EngagementState.DEFEAT_UNCONFIRMED,
    },
    EngagementState.DEFEAT_UNCONFIRMED: {
        EngagementState.RE_ENGAGEMENT_REQUIRED,
        EngagementState.CLOSED,
    },
    EngagementState.DEFEAT_CONFIRMED: {EngagementState.CLOSED},
    EngagementState.RE_ENGAGEMENT_REQUIRED: {
        EngagementState.EFFECTOR_ASSIGNED,
        EngagementState.CLOSED,
    },
    EngagementState.CLOSED: set(),
}


class EngagementLifecycle:
    """Simulated engagement state for ONE track. Independent of TrackLifecycle."""

    def __init__(self, track_id: str) -> None:
        self.track_id = track_id
        self._state = EngagementState.NONE
        self._authorisation: Optional[AuthorisationRecord] = None
        self._history: List[Tuple[EngagementState, Optional[datetime]]] = [
            (EngagementState.NONE, None)
        ]

    @property
    def state(self) -> EngagementState:
        return self._state

    @property
    def authorisation(self) -> Optional[AuthorisationRecord]:
        return self._authorisation

    @property
    def history(self) -> Tuple[Tuple[EngagementState, Optional[datetime]], ...]:
        return tuple(self._history)

    def record_authorisation(self, record: AuthorisationRecord) -> None:
        if not record.covers(self.track_id):
            raise ValueError(
                f"authorisation {record.authorisation_id} does not cover track {self.track_id}"
            )
        self._authorisation = record

    def advance(self, to: EngagementState, at: Optional[datetime] = None) -> None:
        if to not in _ALLOWED[self._state]:
            raise ValueError(f"illegal engagement transition {self._state.value} -> {to.value}")
        if to in AUTHORISATION_REQUIRED_STATES:
            record = self._authorisation
            if record is None or not record.covers(self.track_id):
                raise PermissionError(
                    f"{to.value} requires an authorisation record covering track {self.track_id}"
                )
            if not record.authorises:
                raise PermissionError(
                    f"{to.value} requires an AUTHORISED decision, not {record.decision.value}"
                )
        self._state = to
        self._history.append((to, at))
