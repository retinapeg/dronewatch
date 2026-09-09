"""Latency ledger.

Built in M1 rather than late, because retrofitting stage timestamps across a
finished pipeline costs far more than stamping as you go. Sensor-to-defeat
latency is the product, not a report bolted on afterwards.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from .clock import Instant, elapsed_seconds
from .enums import STAGE_ORDER, ClockKind, LatencyStage

# Derived metric name -> (start stage, end stage)
DERIVED_METRICS: Dict[str, Tuple[LatencyStage, LatencyStage]] = {
    "detection_latency": (
        LatencyStage.FIRST_SENSOR_OBSERVATION,
        LatencyStage.DETECTION_CREATED,
    ),
    "track_latency": (LatencyStage.DETECTION_CREATED, LatencyStage.TRACK_ESTABLISHED),
    "identification_latency": (
        LatencyStage.TRACK_ESTABLISHED,
        LatencyStage.CLASSIFICATION_AVAILABLE,
    ),
    "assessment_latency": (
        LatencyStage.CLASSIFICATION_AVAILABLE,
        LatencyStage.THREAT_ASSESSED,
    ),
    "decision_latency": (LatencyStage.THREAT_ASSESSED, LatencyStage.DECISION_RECOMMENDED),
    "human_latency": (LatencyStage.DECISION_RECOMMENDED, LatencyStage.AUTHORISATION),
    "handoff_latency": (LatencyStage.AUTHORISATION, LatencyStage.EFFECTOR_ASSIGNMENT),
    "simulated_engagement_latency": (
        LatencyStage.EFFECTOR_ASSIGNMENT,
        LatencyStage.SIMULATED_ENGAGEMENT,
    ),
    "total_sensor_to_defeat_latency": (
        LatencyStage.FIRST_SENSOR_OBSERVATION,
        LatencyStage.SIMULATED_DEFEAT_ASSESSMENT,
    ),
}


class LatencyLedger:
    """Records one instant per stage and derives stage latencies.

    Invariants enforced here:
      * every stamp comes from the same clock kind
      * a stage is stamped at most once
      * stamps respect canonical stage order, so no duration can be negative
    """

    def __init__(self, clock_kind: ClockKind) -> None:
        self._clock_kind = clock_kind
        self._stamps: Dict[LatencyStage, Instant] = {}

    @property
    def clock_kind(self) -> ClockKind:
        return self._clock_kind

    @property
    def stamps(self) -> Dict[LatencyStage, Instant]:
        return dict(self._stamps)

    def stamp(self, stage: LatencyStage, at: Instant) -> None:
        if at.kind is not self._clock_kind:
            raise ValueError(
                f"ledger uses {self._clock_kind.value} time; got a {at.kind.value} instant"
            )
        if stage in self._stamps:
            raise ValueError(f"stage {stage.value} has already been stamped")

        index = STAGE_ORDER.index(stage)
        for other, instant in self._stamps.items():
            other_index = STAGE_ORDER.index(other)
            if other_index < index and instant.monotonic_s > at.monotonic_s:
                raise ValueError(
                    f"{stage.value} cannot precede earlier stage {other.value}"
                )
            if other_index > index and instant.monotonic_s < at.monotonic_s:
                raise ValueError(
                    f"{stage.value} cannot follow later stage {other.value}"
                )
        self._stamps[stage] = at

    def has(self, stage: LatencyStage) -> bool:
        return stage in self._stamps

    def duration(self, start: LatencyStage, end: LatencyStage) -> Optional[float]:
        """Seconds between two stages, or None if either has not been stamped."""
        first, last = self._stamps.get(start), self._stamps.get(end)
        if first is None or last is None:
            return None
        return elapsed_seconds(first, last)

    def derived(self) -> Dict[str, Optional[float]]:
        return {
            name: self.duration(start, end)
            for name, (start, end) in DERIVED_METRICS.items()
        }
