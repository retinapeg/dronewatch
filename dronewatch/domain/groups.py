"""Threat groups.

Grouping is additive. Every track always keeps its own assessment, engagement
state, authorisation history and audit trail. A group is a way for an operator
to reason about many tracks at once, not a replacement for per-track state.

Group authorisation is not assumed to be better than per-track authorisation.
The benchmark exists to measure that trade, not to confirm a preference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Set

from .engagement import AuthorisationRecord
from .enums import AuthorisationScope


@dataclass
class ThreatGroup:
    group_id: str
    created_at: datetime
    member_track_ids: Set[str] = field(default_factory=set)
    reason: str = ""
    authorisation: Optional[AuthorisationRecord] = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")

    def add(self, track_id: str) -> None:
        self.member_track_ids.add(track_id)

    def remove(self, track_id: str) -> None:
        self.member_track_ids.discard(track_id)

    def attach_authorisation(self, record: AuthorisationRecord) -> None:
        """Attach a group decision.

        Coverage is whatever the record says, not current membership. Membership
        can change after a decision was taken, and the audit trail must reflect
        what was actually decided at the time.
        """
        if record.scope is not AuthorisationScope.GROUP:
            raise ValueError("a group requires a GROUP-scoped authorisation")
        self.authorisation = record
