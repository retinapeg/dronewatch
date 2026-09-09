"""Threat assessment.

Separate from identity and separate from control evidence. An assessment always
carries its reasons; a score without a rationale is not auditable, and PANOPTES
is explicitly about operator trust under load.

There is deliberately no function here that turns MotionEvidence into a
ThreatAssessment. Manoeuvre evidence must not force a threat conclusion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Tuple

from .enums import ThreatBand


@dataclass(frozen=True)
class Rationale:
    reason: str
    evidence: str
    weight: float = 0.0

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("rationale reason cannot be empty")
        if not self.evidence.strip():
            raise ValueError("rationale evidence cannot be empty")


@dataclass(frozen=True)
class ThreatAssessment:
    score: float
    band: ThreatBand
    assessed_at: datetime
    rationale: Tuple[Rationale, ...]
    consumed_features: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"threat score must lie in 0..1, got {self.score}")
        if self.assessed_at.tzinfo is None:
            raise ValueError("assessed_at must be timezone-aware")
        if not self.rationale:
            raise ValueError("a threat assessment must state its reasons")


def band_for(score: float) -> ThreatBand:
    """A deliberately crude banding. The real policy lands in M5."""
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"threat score must lie in 0..1, got {score}")
    if score >= 0.75:
        return ThreatBand.HIGH
    if score >= 0.4:
        return ThreatBand.MODERATE
    return ThreatBand.LOW
