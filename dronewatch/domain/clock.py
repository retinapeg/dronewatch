"""Clock abstraction.

Durations come from a monotonic source; wall-clock is carried alongside for
display only. Every Instant records which clock produced it, because comparing
simulated time with real time silently produces meaningless latency numbers.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .enums import ClockKind


@dataclass(frozen=True)
class Instant:
    monotonic_s: float
    wall: datetime
    kind: ClockKind

    def __post_init__(self) -> None:
        if self.wall.tzinfo is None:
            raise ValueError("Instant.wall must be timezone-aware")


def elapsed_seconds(start: Instant, end: Instant) -> float:
    """Seconds between two instants from the same clock. Never negative."""
    if start.kind is not end.kind:
        raise ValueError(
            f"cannot compare a {start.kind.value} instant with a {end.kind.value} instant"
        )
    delta = end.monotonic_s - start.monotonic_s
    if delta < 0:
        raise ValueError("negative duration: end instant precedes start instant")
    return delta


class Clock(Protocol):
    kind: ClockKind

    def now(self) -> Instant: ...


class SystemClock:
    """Real time. Monotonic for durations, wall-clock for display."""

    kind = ClockKind.SYSTEM

    def now(self) -> Instant:
        return Instant(
            monotonic_s=time.monotonic(),
            wall=datetime.now(timezone.utc),
            kind=ClockKind.SYSTEM,
        )


class SimulatedClock:
    """Deterministic time for scenarios and benchmarks. Advances only when told."""

    kind = ClockKind.SIMULATED

    def __init__(self, start: datetime, *, monotonic_s: float = 0.0) -> None:
        if start.tzinfo is None:
            raise ValueError("SimulatedClock start must be timezone-aware")
        self._wall = start
        self._monotonic = monotonic_s

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("simulated time cannot move backwards")
        self._monotonic += seconds
        self._wall = self._wall + timedelta(seconds=seconds)

    def now(self) -> Instant:
        return Instant(
            monotonic_s=self._monotonic, wall=self._wall, kind=ClockKind.SIMULATED
        )
