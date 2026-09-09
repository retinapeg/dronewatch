"""DroneWatch V0.2 domain layer.

Pure types and invariants. No I/O, no framework, no wire formats. Everything
else depends inward on this package; this package depends on nothing.

Six concepts stay separate and must never collapse into one hostile flag:
identity, control evidence, threat assessment, engagement decision,
authorisation, and effector outcome.
"""
from .classification import ClassificationDistribution
from .clock import Clock, Instant, SimulatedClock, SystemClock, elapsed_seconds
from .engagement import (
    AuthorisationRecord,
    EngagementLifecycle,
    effective_authorisation,
)
from .enums import (
    AuthorityKind,
    AuthorisationScope,
    ClockKind,
    Decision,
    EngagementState,
    LatencyStage,
    Modality,
    ObjectClass,
    ThreatBand,
    TrackState,
)
from .groups import ThreatGroup
from .latency import LatencyLedger
from .motion import MotionEvidence
from .observation import (
    FramePosition,
    GeoPosition,
    QualitativePosition,
    QualityFlags,
    RangeBearing,
    SensorObservation,
    SignalFeature,
)
from .threat import Rationale, ThreatAssessment, band_for
from .track import FusedTrack, TrackLifecycle

__all__ = [
    "AuthorisationRecord",
    "AuthorisationScope",
    "AuthorityKind",
    "ClassificationDistribution",
    "Clock",
    "ClockKind",
    "Decision",
    "EngagementLifecycle",
    "EngagementState",
    "FramePosition",
    "FusedTrack",
    "GeoPosition",
    "Instant",
    "LatencyLedger",
    "LatencyStage",
    "Modality",
    "MotionEvidence",
    "ObjectClass",
    "QualitativePosition",
    "QualityFlags",
    "RangeBearing",
    "Rationale",
    "SensorObservation",
    "SignalFeature",
    "SimulatedClock",
    "SystemClock",
    "ThreatAssessment",
    "ThreatBand",
    "ThreatGroup",
    "TrackLifecycle",
    "TrackState",
    "band_for",
    "effective_authorisation",
    "elapsed_seconds",
]
