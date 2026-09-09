"""The monitored site.

A fictional site at the origin of the local simulation frame. Distances are
simulation metres. These are not geographic coordinates.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MonitoredSite:
    name: str = "SITE ALPHA"
    x: float = 0.0
    y: float = 0.0
    radius_m: float = 600.0

    def range_to(self, x: float, y: float) -> float:
        return math.hypot(x - self.x, y - self.y)

    def is_inside(self, x: float, y: float) -> bool:
        return self.range_to(x, y) <= self.radius_m

    def closing_speed(self, x: float, y: float, vx: float, vy: float) -> float:
        """Positive when moving toward the site, negative when moving away."""
        distance = self.range_to(x, y)
        if distance < 1e-6:
            return 0.0
        # Component of velocity along the inbound unit vector.
        return -((x - self.x) * vx + (y - self.y) * vy) / distance
