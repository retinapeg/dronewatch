"""Abstract motion primitives.

Deliberately crude. This produces controlled experimental data, not a flight
simulator. Coordinates are a generic simulation frame in metres:

    x, y   horizontal plane
    z      altitude
    vx, vy, vz   velocity components in metres per second

Nothing here models a real platform, and no real-world performance envelope is
represented.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import List, Sequence


@dataclass(frozen=True)
class SimState:
    t: float
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float

    @property
    def speed(self) -> float:
        return math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)


class TrajectorySegment:
    """One phase of motion. Segments compose into a trajectory."""

    duration: float

    def step(self, state: SimState, dt: float, rng: random.Random) -> SimState:
        raise NotImplementedError


@dataclass
class ConstantVelocity(TrajectorySegment):
    duration: float

    def step(self, state: SimState, dt: float, rng: random.Random) -> SimState:
        return replace(
            state,
            t=state.t + dt,
            x=state.x + state.vx * dt,
            y=state.y + state.vy * dt,
            z=state.z + state.vz * dt,
        )


@dataclass
class ConstantAcceleration(TrajectorySegment):
    duration: float
    ax: float = 0.0
    ay: float = 0.0
    az: float = 0.0

    def step(self, state: SimState, dt: float, rng: random.Random) -> SimState:
        vx, vy, vz = (
            state.vx + self.ax * dt,
            state.vy + self.ay * dt,
            state.vz + self.az * dt,
        )
        return replace(
            state,
            t=state.t + dt,
            x=state.x + vx * dt,
            y=state.y + vy * dt,
            z=state.z + vz * dt,
            vx=vx, vy=vy, vz=vz,
        )


@dataclass
class HeadingChange(TrajectorySegment):
    """Turn in the horizontal plane at a fixed rate."""

    duration: float
    turn_rate_deg_s: float

    def step(self, state: SimState, dt: float, rng: random.Random) -> SimState:
        angle = math.radians(self.turn_rate_deg_s * dt)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        vx = state.vx * cos_a - state.vy * sin_a
        vy = state.vx * sin_a + state.vy * cos_a
        return replace(
            state,
            t=state.t + dt,
            x=state.x + vx * dt,
            y=state.y + vy * dt,
            z=state.z + state.vz * dt,
            vx=vx, vy=vy,
        )


@dataclass
class AltitudeChange(TrajectorySegment):
    duration: float
    climb_rate_m_s: float

    def step(self, state: SimState, dt: float, rng: random.Random) -> SimState:
        vz = self.climb_rate_m_s
        return replace(
            state,
            t=state.t + dt,
            x=state.x + state.vx * dt,
            y=state.y + state.vy * dt,
            z=max(0.0, state.z + vz * dt),
            vz=vz,
        )


@dataclass
class ManoeuvreImpulse(TrajectorySegment):
    """The manoeuvre process: bounded, structured control input.

    This is what separates a controlled trajectory from a passive one. It is a
    property of CONTROL, not of identity. A decoy may carry it and a threat may
    not; see the counterexample families in scenarios.py.
    """

    duration: float
    magnitude_m_s2: float = 2.0
    impulse_probability: float = 0.35

    def step(self, state: SimState, dt: float, rng: random.Random) -> SimState:
        vx, vy, vz = state.vx, state.vy, state.vz
        if rng.random() < self.impulse_probability:
            vx += rng.uniform(-self.magnitude_m_s2, self.magnitude_m_s2) * dt
            vy += rng.uniform(-self.magnitude_m_s2, self.magnitude_m_s2) * dt
            vz += rng.uniform(-self.magnitude_m_s2 / 2, self.magnitude_m_s2 / 2) * dt
        return replace(
            state,
            t=state.t + dt,
            x=state.x + vx * dt,
            y=state.y + vy * dt,
            z=max(0.0, state.z + vz * dt),
            vx=vx, vy=vy, vz=vz,
        )


@dataclass
class ControlDegradation(TrajectorySegment):
    """Temporary loss of control authority. Velocity decays toward drift."""

    duration: float
    decay: float = 0.15

    def step(self, state: SimState, dt: float, rng: random.Random) -> SimState:
        factor = max(0.0, 1.0 - self.decay * dt)
        vx, vy = state.vx * factor, state.vy * factor
        vz = state.vz - 0.5 * dt
        return replace(
            state,
            t=state.t + dt,
            x=state.x + vx * dt,
            y=state.y + vy * dt,
            z=max(0.0, state.z + vz * dt),
            vx=vx, vy=vy, vz=vz,
        )


def integrate(
    initial: SimState,
    segments: Sequence[TrajectorySegment],
    *,
    dt: float,
    rng: random.Random,
    disturbance_sigma: float = 0.0,
) -> List[SimState]:
    """Run segments in order, applying environmental disturbance throughout.

    Disturbance is zero-mean noise applied to every entity regardless of control
    mode, so it cannot by itself distinguish a controlled entity from a passive
    one. That distinction has to come from the manoeuvre process.
    """
    states = [initial]
    state = initial
    for segment in segments:
        steps = max(1, int(round(segment.duration / dt)))
        for _ in range(steps):
            state = segment.step(state, dt, rng)
            if disturbance_sigma > 0:
                state = replace(
                    state,
                    vx=state.vx + rng.gauss(0.0, disturbance_sigma),
                    vy=state.vy + rng.gauss(0.0, disturbance_sigma),
                    vz=state.vz + rng.gauss(0.0, disturbance_sigma / 2),
                )
            states.append(state)
    return states
