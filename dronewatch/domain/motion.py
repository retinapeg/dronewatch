"""Active-control and manoeuvre evidence.

This is deliberately NOT a class label and NOT a threat assessment.

    ACTIVE MANOEUVRE  !=  THREAT
    STRAIGHT FLIGHT   !=  DECOY

Threat assessment may consume these features. Nothing in this module may
produce an ObjectClass or a ThreatAssessment, and a test enforces that.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MIN_OBSERVATIONS_FOR_CONTROL_EVIDENCE = 5


def _check_unit(name: str, value: Optional[float]) -> None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must lie in 0..1, got {value}")


@dataclass(frozen=True)
class MotionEvidence:
    """Evidence about whether motion suggests controlled behaviour.

    Every field is optional. Absent means "not yet determinable", which is
    different from zero. Manoeuvre detection needs trajectory history, so early
    in a track's life the honest answer is that there is no evidence yet.
    """

    active_control_probability: Optional[float] = None
    manoeuvre_score: Optional[float] = None
    motion_model_residual: Optional[float] = None
    trajectory_confidence: Optional[float] = None
    supporting_observations: int = 0

    def __post_init__(self) -> None:
        _check_unit("active_control_probability", self.active_control_probability)
        _check_unit("manoeuvre_score", self.manoeuvre_score)
        _check_unit("trajectory_confidence", self.trajectory_confidence)
        if self.motion_model_residual is not None and self.motion_model_residual < 0:
            raise ValueError("motion_model_residual cannot be negative")
        if self.supporting_observations < 0:
            raise ValueError("supporting_observations cannot be negative")

    @classmethod
    def insufficient(cls) -> "MotionEvidence":
        """No usable evidence yet. Not the same as evidence of no control."""
        return cls()

    @property
    def is_sufficient(self) -> bool:
        return (
            self.supporting_observations >= MIN_OBSERVATIONS_FOR_CONTROL_EVIDENCE
            and self.active_control_probability is not None
        )
