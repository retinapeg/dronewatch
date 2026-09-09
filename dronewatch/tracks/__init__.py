"""A small tracking baseline for the operator preview.

This is NOT production tracking, validated classification, or multi-sensor
fusion. It is a constant-velocity filter over one simulated positional sensor,
built so the preview can show stable contacts instead of a cloud of points.

This package sits inside the M1 import guard, so it cannot reach synthetic
ground truth. Association and display are driven by observations alone.
"""
from .attention import AttentionRule, Priority, evaluate_priority
from .site import MonitoredSite
from .tracker import Track, TrackState, Tracker, TrackerConfig

__all__ = [
    "AttentionRule", "MonitoredSite", "Priority", "Track", "TrackState",
    "Tracker", "TrackerConfig", "evaluate_priority",
]
