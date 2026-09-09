"""Enumerations for the DroneWatch V0.2 domain.

Six concepts are kept deliberately separate and must never collapse into a
single "hostile" flag: object identity, control evidence, threat assessment,
engagement decision, authorisation, and effector outcome.
"""
from __future__ import annotations

from enum import Enum


class Modality(str, Enum):
    RADAR = "RADAR"
    RF = "RF"
    EO = "EO"
    IR = "IR"
    ACOUSTIC = "ACOUSTIC"
    VISUAL_FILE = "VISUAL_FILE"
    OTHER = "OTHER"


class ObjectClass(str, Enum):
    """What a track APPEARS TO BE. This is identity, not threat assessment.

    `THREAT` means "appears to be a threat-type object". Whether it actually
    presents a defensive threat is decided by ThreatAssessment, which is a
    separate stage and may disagree.
    """

    THREAT = "THREAT"
    DECOY = "DECOY"
    BENIGN = "BENIGN"
    FRIENDLY = "FRIENDLY"
    UNKNOWN = "UNKNOWN"


class TrackState(str, Enum):
    """Track lifecycle. Independent of the engagement lifecycle."""

    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    CLASSIFIED = "CLASSIFIED"
    ASSESSED = "ASSESSED"
    LOST = "LOST"
    REACQUIRED = "REACQUIRED"
    CLOSED = "CLOSED"


class EngagementState(str, Enum):
    """Simulated engagement lifecycle. Independent of the track lifecycle."""

    NONE = "NONE"
    RECOMMENDED = "RECOMMENDED"
    DECISION_PENDING = "DECISION_PENDING"
    AUTHORISED = "AUTHORISED"
    REJECTED = "REJECTED"
    EFFECTOR_ASSIGNED = "EFFECTOR_ASSIGNED"
    ENGAGEMENT_PENDING = "ENGAGEMENT_PENDING"
    SIMULATED_ENGAGEMENT = "SIMULATED_ENGAGEMENT"
    DEFEAT_CONFIRMED = "DEFEAT_CONFIRMED"
    DEFEAT_UNCONFIRMED = "DEFEAT_UNCONFIRMED"
    RE_ENGAGEMENT_REQUIRED = "RE_ENGAGEMENT_REQUIRED"
    CLOSED = "CLOSED"


class ThreatBand(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ClockKind(str, Enum):
    """Simulated and real time must never be compared with each other."""

    SYSTEM = "SYSTEM"
    SIMULATED = "SIMULATED"


class AuthorityKind(str, Enum):
    OPERATOR = "OPERATOR"
    POLICY = "POLICY"


class Decision(str, Enum):
    AUTHORISED = "AUTHORISED"
    REJECTED = "REJECTED"


class AuthorisationScope(str, Enum):
    TRACK = "TRACK"
    GROUP = "GROUP"


class LatencyStage(str, Enum):
    """Canonical order matters: durations are only computed forward."""

    FIRST_SENSOR_OBSERVATION = "first_sensor_observation"
    DETECTION_CREATED = "detection_created"
    TRACK_ESTABLISHED = "track_established"
    CLASSIFICATION_AVAILABLE = "classification_available"
    THREAT_ASSESSED = "threat_assessed"
    DECISION_RECOMMENDED = "decision_recommended"
    AUTHORISATION = "authorisation"
    EFFECTOR_ASSIGNMENT = "effector_assignment"
    SIMULATED_ENGAGEMENT = "simulated_engagement"
    SIMULATED_DEFEAT_ASSESSMENT = "simulated_defeat_assessment"


STAGE_ORDER = tuple(LatencyStage)
