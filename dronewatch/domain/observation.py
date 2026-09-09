"""SensorObservation: one sensor's statement about something it saw.

Two properties are carried over from V0.1.1 deliberately:
  * `received_at` is ours, never sender-controlled
  * confidence is either a real 0..1 value or absent; there is no invented middle
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Tuple, Union

from .classification import ClassificationDistribution
from .enums import Modality


@dataclass(frozen=True)
class FramePosition:
    """Normalised position within a sensor frame."""

    x: float
    y: float

    def __post_init__(self) -> None:
        for name, value in (("x", self.x), ("y", self.y)):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"frame {name} must lie in 0..1, got {value}")


@dataclass(frozen=True)
class RangeBearing:
    range_m: float
    bearing_deg: float
    elevation_deg: Optional[float] = None

    def __post_init__(self) -> None:
        if self.range_m < 0:
            raise ValueError("range_m cannot be negative")
        if not 0.0 <= self.bearing_deg < 360.0:
            raise ValueError("bearing_deg must lie in [0, 360)")


@dataclass(frozen=True)
class GeoPosition:
    latitude: float
    longitude: float
    altitude_m: Optional[float] = None


@dataclass(frozen=True)
class QualitativePosition:
    """Free text such as "center-right to right". Retained verbatim, never converted."""

    described_as: str


Position = Union[FramePosition, RangeBearing, GeoPosition, QualitativePosition]


@dataclass(frozen=True)
class SignalFeature:
    """RF characteristics, shaped to match what SAPIENT detection reports carry."""

    centre_frequency_hz: float
    amplitude: Optional[float] = None
    bandwidth_hz: Optional[float] = None


@dataclass(frozen=True)
class QualityFlags:
    noisy: bool = False
    duplicate: bool = False
    delayed: bool = False
    out_of_order: bool = False


@dataclass(frozen=True)
class SensorObservation:
    observation_id: str
    sensor_id: str
    modality: Modality
    observed_at: datetime
    received_at: datetime
    position: Optional[Position] = None
    classification: ClassificationDistribution = field(
        default_factory=ClassificationDistribution.unknown
    )
    confidence: Optional[float] = None
    signals: Tuple[SignalFeature, ...] = ()
    associated_ids: Tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)
    quality: QualityFlags = field(default_factory=QualityFlags)

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must lie in 0..1, got {self.confidence}")
        for name in ("observed_at", "received_at"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")

    @property
    def is_future_dated(self) -> bool:
        """A sender claiming an observation time after we received it."""
        return self.observed_at > self.received_at

    @property
    def transport_delay_s(self) -> float:
        """Seconds between the claimed observation and our receipt. Never negative."""
        return max(0.0, (self.received_at - self.observed_at).total_seconds())
