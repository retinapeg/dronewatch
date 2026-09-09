"""Track lifecycle and the fused track.

The track lifecycle is independent of the engagement lifecycle. A track can be
lost and reacquired while an engagement is pending, and an engagement can fail
while the track continues. One combined enum cannot express that without
representing illegal states.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Set, Tuple

from .classification import ClassificationDistribution
from .engagement import EngagementLifecycle
from .enums import ClockKind, TrackState
from .latency import LatencyLedger
from .motion import MotionEvidence
from .observation import Position, SensorObservation
from .threat import ThreatAssessment

_ALLOWED: dict = {
    TrackState.TENTATIVE: {TrackState.CONFIRMED, TrackState.LOST, TrackState.CLOSED},
    TrackState.CONFIRMED: {TrackState.CLASSIFIED, TrackState.LOST, TrackState.CLOSED},
    TrackState.CLASSIFIED: {TrackState.ASSESSED, TrackState.LOST, TrackState.CLOSED},
    TrackState.ASSESSED: {TrackState.LOST, TrackState.CLOSED, TrackState.CLASSIFIED},
    TrackState.LOST: {TrackState.REACQUIRED, TrackState.CLOSED},
    TrackState.REACQUIRED: {
        TrackState.CONFIRMED,
        TrackState.CLASSIFIED,
        TrackState.ASSESSED,
        TrackState.LOST,
        TrackState.CLOSED,
    },
    TrackState.CLOSED: set(),
}


class TrackLifecycle:
    def __init__(self) -> None:
        self._state = TrackState.TENTATIVE
        self._history: List[Tuple[TrackState, Optional[datetime]]] = [
            (TrackState.TENTATIVE, None)
        ]

    @property
    def state(self) -> TrackState:
        return self._state

    @property
    def history(self) -> Tuple[Tuple[TrackState, Optional[datetime]], ...]:
        return tuple(self._history)

    def advance(self, to: TrackState, at: Optional[datetime] = None) -> None:
        if to not in _ALLOWED[self._state]:
            raise ValueError(f"illegal track transition {self._state.value} -> {to.value}")
        self._state = to
        self._history.append((to, at))


@dataclass
class FusedTrack:
    """Many observations, one persistent identity.

    Identity, control evidence, threat assessment and engagement are separate
    fields on purpose. None of them is derived from another implicitly.
    """

    track_id: str
    first_seen: datetime
    last_seen: datetime
    clock_kind: ClockKind = ClockKind.SYSTEM
    observations: List[SensorObservation] = field(default_factory=list)
    contributing_sensors: Set[str] = field(default_factory=set)
    classification: ClassificationDistribution = field(
        default_factory=ClassificationDistribution.unknown
    )
    motion: MotionEvidence = field(default_factory=MotionEvidence.insufficient)
    threat: Optional[ThreatAssessment] = None
    group_id: Optional[str] = None
    history: List[Position] = field(default_factory=list)
    lifecycle: TrackLifecycle = field(default_factory=TrackLifecycle)
    engagement: Optional[EngagementLifecycle] = None
    latency: Optional[LatencyLedger] = None

    def __post_init__(self) -> None:
        if self.engagement is None:
            self.engagement = EngagementLifecycle(self.track_id)
        if self.latency is None:
            self.latency = LatencyLedger(self.clock_kind)

    def add_observation(self, observation: SensorObservation) -> None:
        """Record an observation. No fusion logic here; association lands in M4."""
        self.observations.append(observation)
        self.contributing_sensors.add(observation.sensor_id)
        if observation.position is not None:
            self.history.append(observation.position)
        if observation.received_at > self.last_seen:
            self.last_seen = observation.received_at
