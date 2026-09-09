"""Trajectory families, the scenario registry, and the swarm primitive.

The two baseline families are useful because they separate cleanly:

    DECOY FAMILY:      simple dynamics + environmental disturbance
    CONTROLLED FAMILY: simple dynamics + manoeuvre process + disturbance

They are a starting point, NOT the label a classifier should learn. Identity and
control mode are independent variables here, and the registry deliberately
contains counterexamples in both directions:

    straight_flying_threat   THREAT that is CONTROLLED but barely manoeuvres
    controlled_decoy         DECOY that is genuinely CONTROLLED

Anything that learns "turning means threat" will fail on those two.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Dict, List, Optional, Tuple

from ..domain.enums import ObjectClass
from .groundtruth import ControlMode, GroundTruthEntity, TrajectoryPoint
from .motion import (
    AltitudeChange,
    ConstantVelocity,
    ControlDegradation,
    HeadingChange,
    ManoeuvreImpulse,
    SimState,
    TrajectorySegment,
    integrate,
)
from .rng import stream

DISTURBANCE_SIGMA = 0.35


def _initial(rng: random.Random, *, speed: float = 22.0) -> SimState:
    bearing = rng.uniform(0, 2 * 3.14159265)
    import math

    return SimState(
        t=0.0,
        x=rng.uniform(-2500.0, -1500.0),
        y=rng.uniform(-800.0, 800.0),
        z=rng.uniform(60.0, 160.0),
        vx=abs(speed * math.cos(bearing)) or speed,
        vy=speed * math.sin(bearing) * 0.2,
        vz=0.0,
    )


# --- trajectory families ----------------------------------------------------

def family_passive(duration: float) -> List[TrajectorySegment]:
    """A. Passive decoy. Predictable motion, disturbance only."""
    return [ConstantVelocity(duration)]


def family_controlled(duration: float) -> List[TrajectorySegment]:
    """B. Controlled entity with clear manoeuvres."""
    slice_s = duration / 5
    return [
        ConstantVelocity(slice_s),
        HeadingChange(slice_s, turn_rate_deg_s=8.0),
        ManoeuvreImpulse(slice_s, magnitude_m_s2=3.0, impulse_probability=0.5),
        HeadingChange(slice_s, turn_rate_deg_s=-6.0),
        ConstantVelocity(slice_s),
    ]


def family_nearly_straight(duration: float) -> List[TrajectorySegment]:
    """C and F. Controlled, but with weak manoeuvre evidence."""
    slice_s = duration / 4
    return [
        ConstantVelocity(slice_s),
        ManoeuvreImpulse(slice_s, magnitude_m_s2=0.4, impulse_probability=0.08),
        ConstantVelocity(slice_s),
        HeadingChange(slice_s, turn_rate_deg_s=1.0),
    ]


def family_tumbling(duration: float) -> List[TrajectorySegment]:
    """D. Passive, but visually erratic. Looks manoeuvring, is not controlled."""
    slice_s = duration / 4
    return [
        ConstantVelocity(slice_s),
        ControlDegradation(slice_s, decay=0.05),
        AltitudeChange(slice_s, climb_rate_m_s=-2.5),
        ControlDegradation(slice_s, decay=0.08),
    ]


def _points(states) -> Tuple[TrajectoryPoint, ...]:
    return tuple(
        TrajectoryPoint(
            t=round(s.t, 4), x=round(s.x, 4), y=round(s.y, 4), z=round(s.z, 4),
            vx=round(s.vx, 4), vy=round(s.vy, 4), vz=round(s.vz, 4),
        )
        for s in states
    )


def make_entity(
    entity_id: str,
    true_class: ObjectClass,
    control_mode: ControlMode,
    segments_for: Callable[[float], List[TrajectorySegment]],
    *,
    seed: int,
    duration: float,
    dt: float,
    spawn_time: float = 0.0,
    end_time: Optional[float] = None,
    intent: str = "",
    initial: Optional[SimState] = None,
    disturbance_sigma: Optional[float] = None,
) -> GroundTruthEntity:
    """Build one ground-truth entity.

    `true_class` and `control_mode` are supplied independently by the caller.
    Nothing in this function derives one from the other.

    `initial` lets a caller place an entity deliberately instead of drawing a
    random start, which the operator demo needs so the group arrives from one
    sector. Existing callers keep the random placement.
    """
    rng = stream(seed, "entity", entity_id)
    states = integrate(
        initial if initial is not None else _initial(rng),
        segments_for(duration), dt=dt, rng=rng,
        disturbance_sigma=(
            DISTURBANCE_SIGMA if disturbance_sigma is None else disturbance_sigma
        ),
    )
    return GroundTruthEntity(
        entity_id=entity_id,
        true_class=true_class,
        true_control_mode=control_mode,
        intent=intent,
        spawn_time=spawn_time,
        end_time=duration if end_time is None else end_time,
        trajectory=_points(states),
    )


# --- entity sets for each registered scenario -------------------------------

def _single_threat(seed, duration, dt):
    return [make_entity("gt-threat-1", ObjectClass.THREAT, ControlMode.CONTROLLED,
                        family_controlled, seed=seed, duration=duration, dt=dt,
                        intent="INCURSION")]


def _single_decoy(seed, duration, dt):
    return [make_entity("gt-decoy-1", ObjectClass.DECOY, ControlMode.PASSIVE,
                        family_passive, seed=seed, duration=duration, dt=dt,
                        intent="SATURATION")]


def _straight_flying_threat(seed, duration, dt):
    """Counterexample: a real threat with almost no manoeuvre evidence."""
    return [make_entity("gt-threat-straight", ObjectClass.THREAT, ControlMode.CONTROLLED,
                        family_nearly_straight, seed=seed, duration=duration, dt=dt,
                        intent="INCURSION")]


def _controlled_decoy(seed, duration, dt):
    """Counterexample: genuine agency without hostility."""
    return [make_entity("gt-decoy-controlled", ObjectClass.DECOY, ControlMode.CONTROLLED,
                        family_controlled, seed=seed, duration=duration, dt=dt,
                        intent="SATURATION")]


def _tumbling_decoy(seed, duration, dt):
    return [make_entity("gt-decoy-tumbling", ObjectClass.DECOY, ControlMode.DEGRADED_CONTROL,
                        family_tumbling, seed=seed, duration=duration, dt=dt)]


def _mixed_threat_decoy(seed, duration, dt):
    return (
        _single_threat(seed, duration, dt)
        + _single_decoy(seed, duration, dt)
        + _controlled_decoy(seed, duration, dt)
        + _straight_flying_threat(seed, duration, dt)
    )


def _benign(seed, duration, dt):
    return [make_entity("gt-benign-1", ObjectClass.BENIGN, ControlMode.CONTROLLED,
                        family_nearly_straight, seed=seed, duration=duration, dt=dt,
                        intent="TRANSIT")]


def _reacquisition(seed, duration, dt):
    return [make_entity("gt-threat-reacq", ObjectClass.THREAT, ControlMode.CONTROLLED,
                        family_controlled, seed=seed, duration=duration, dt=dt,
                        intent="INCURSION")]


def generate_swarm(
    count: int,
    *,
    seed: int,
    duration: float,
    dt: float,
    threat_fraction: float = 0.5,
    decoy_fraction: float = 0.5,
) -> List[GroundTruthEntity]:
    """Parameterised entity-set generator.

    Produces trajectories only. No ranking, grouping, authorisation, effector
    assignment or engagement happens here; a swarm at M2 is simply many
    synthetic entities observed at the same time.

    Control mode is assigned independently of class, so the swarm naturally
    contains passive threats and controlled decoys.
    """
    if count < 1:
        raise ValueError("swarm count must be at least 1")
    total = threat_fraction + decoy_fraction
    if total <= 0:
        raise ValueError("threat_fraction + decoy_fraction must be positive")

    rng = stream(seed, "swarm-composition", str(count))
    threat_count = int(round(count * (threat_fraction / total)))
    entities: List[GroundTruthEntity] = []

    for index in range(count):
        is_threat = index < threat_count
        object_class = ObjectClass.THREAT if is_threat else ObjectClass.DECOY
        # Control mode drawn independently of class, on purpose.
        control_mode = rng.choice(
            [ControlMode.CONTROLLED, ControlMode.PASSIVE, ControlMode.DEGRADED_CONTROL]
        )
        family = {
            ControlMode.CONTROLLED: family_controlled,
            ControlMode.PASSIVE: family_passive,
            ControlMode.DEGRADED_CONTROL: family_tumbling,
            ControlMode.LOW_CONTROL: family_nearly_straight,
        }[control_mode]
        entities.append(
            make_entity(
                f"gt-swarm-{index:03d}", object_class, control_mode, family,
                seed=seed, duration=duration, dt=dt,
                spawn_time=round(rng.uniform(0.0, duration * 0.25), 3),
            )
        )
    return entities


# --- operator demonstration --------------------------------------------------
#
# A deliberately legible scenario for the track-based preview. A group appears
# in one sector, approaches the monitored site, then separates: roughly half
# continue inward and cross the boundary, the rest turn and pass at separation.
# Modest disturbance, no clutter. Harder scenarios stay in Diagnostics.

SITE_X, SITE_Y = 0.0, 0.0
MONITORED_RADIUS_M = 600.0
DEMO_SPEED_M_S = 25.0
DEMO_DISTURBANCE = 0.12
GROUP_BEARING_DEG = 145.0   # entities sit NW of the site and fly inbound
GROUP_ARC_DEG = 26.0
SPLIT_TIME_S = 35.0


def _inbound_initial(index: int, count: int, rng: random.Random) -> SimState:
    """Place an entity in the approach sector, heading at the site."""
    spread = 0.0 if count == 1 else (index / (count - 1)) - 0.5
    angle = math.radians(GROUP_BEARING_DEG + spread * GROUP_ARC_DEG)
    radius = 2200.0 + (index % 3) * 190.0 + rng.uniform(-40.0, 40.0)
    x, y = radius * math.cos(angle), radius * math.sin(angle)
    # Aim at an offset point inside the area rather than the exact centre.
    # A contact passing directly overhead has an enormous angular rate at close
    # range, which a constant-velocity filter cannot follow; the track would
    # break and re-form. Contacts still cross the boundary, so the geometry the
    # demonstration needs is unchanged.
    aim_lateral = 180.0 + (index % 4) * 90.0
    aim_x = SITE_X + aim_lateral * math.cos(math.radians(GROUP_BEARING_DEG - 90.0))
    aim_y = SITE_Y + aim_lateral * math.sin(math.radians(GROUP_BEARING_DEG - 90.0))
    heading = math.atan2(aim_y - y, aim_x - x) + math.radians(rng.uniform(-2.0, 2.0))
    return SimState(
        t=0.0, x=x, y=y, z=90.0 + rng.uniform(-15.0, 25.0),
        vx=DEMO_SPEED_M_S * math.cos(heading),
        vy=DEMO_SPEED_M_S * math.sin(heading),
        vz=0.0,
    )


def _continues_inbound(duration: float) -> List[TrajectorySegment]:
    return [ConstantVelocity(duration)]


def _turns_away(duration: float) -> List[TrajectorySegment]:
    remaining = max(1.0, duration - SPLIT_TIME_S - 26.0)
    return [
        ConstantVelocity(SPLIT_TIME_S),
        HeadingChange(26.0, turn_rate_deg_s=3.4),
        ConstantVelocity(remaining),
    ]


def generate_incoming_group(
    count: int, *, seed: int, duration: float, dt: float
) -> List[GroundTruthEntity]:
    """The operator demo: an incoming group that separates.

    Roughly half continue toward the site and cross the monitored boundary; the
    remainder turn and pass at separation. That populates every attention level
    in a single run without any clutter.
    """
    if not 3 <= count <= 10:
        raise ValueError("the operator demo supports 3 to 10 contacts")

    rng = stream(seed, "operator-demo", str(count))
    inbound = math.ceil(count / 2)
    entities: List[GroundTruthEntity] = []
    for index in range(count):
        continues = index < inbound
        entities.append(
            make_entity(
                f"gt-contact-{index + 1:02d}",
                ObjectClass.UNKNOWN, ControlMode.CONTROLLED,
                _continues_inbound if continues else _turns_away,
                seed=seed, duration=duration, dt=dt,
                initial=_inbound_initial(index, count, rng),
                disturbance_sigma=DEMO_DISTURBANCE,
                intent="INBOUND" if continues else "PASSING",
            )
        )
    return entities


#: name -> (entity builder, scenario notes)
ENTITY_BUILDERS: Dict[str, Callable] = {
    "single_threat": _single_threat,
    "single_decoy": _single_decoy,
    "straight_flying_threat": _straight_flying_threat,
    "controlled_decoy": _controlled_decoy,
    "tumbling_decoy": _tumbling_decoy,
    "mixed_threat_decoy": _mixed_threat_decoy,
    "sensor_disagreement": _mixed_threat_decoy,
    "sensor_dropout": _single_threat,
    "track_reacquisition_fixture": _reacquisition,
    "false_positive": _benign,
    "delayed_out_of_order": _mixed_threat_decoy,
    "small_swarm": None,  # handled by the swarm primitive
    "operator_demo": None,  # handled by generate_incoming_group
    "operator_demo_signal_loss": None,  # operator demo with a deliberate gap
}

SCENARIO_NAMES = tuple(sorted(ENTITY_BUILDERS))
