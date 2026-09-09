"""Ground-truth types for synthetic scenarios.

GROUND TRUTH MUST NEVER REACH THE ALGORITHM BEING EVALUATED.

A scenario carries two disjoint namespaces. The pipeline under test is handed
observations only. Evaluation joins observations back to ground truth
afterwards, outside the pipeline.

If ground truth leaks into fusion, threat assessment, decisions or effectors,
every metric produced becomes meaningless while still looking plausible. A test
in the suite asserts that no evaluated module imports this one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from ..domain.enums import ObjectClass
from ..domain.observation import SensorObservation

#: Marker used by the leak test to identify ground-truth-only modules.
IS_GROUND_TRUTH_MODULE = True


class ControlMode(str, Enum):
    """How an entity is actually flown. Ground truth only.

    Recorded separately from `true_class` so evaluation can distinguish
    "misidentified the object" from "misread the motion". Case S in the scenario
    catalogue, a controlled decoy, exists precisely because agency and hostility
    are different things.
    """

    PASSIVE = "PASSIVE"
    LOW_CONTROL = "LOW_CONTROL"
    DEGRADED_CONTROL = "DEGRADED_CONTROL"
    CONTROLLED = "CONTROLLED"


@dataclass(frozen=True)
class TrajectoryPoint:
    """A true state sample in the simulation frame. Metres and metres/second."""

    t: float
    x: float
    y: float
    z: float
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0


@dataclass(frozen=True)
class GroundTruthEntity:
    """The truth about one synthetic entity.

    `true_class` and `true_control_mode` are independent variables. A DECOY may
    be CONTROLLED and a THREAT may be PASSIVE. Nothing in the generator ties
    them together, and tests assert that both counterexamples exist.
    """

    entity_id: str
    true_class: ObjectClass
    true_control_mode: ControlMode
    intent: str = ""
    spawn_time: float = 0.0
    end_time: float = 0.0
    trajectory: Tuple[TrajectoryPoint, ...] = ()

    def state_at(self, t: float) -> TrajectoryPoint:
        """Nearest true state sample at or before `t`."""
        if not self.trajectory:
            raise ValueError(f"entity {self.entity_id} has no trajectory")
        chosen = self.trajectory[0]
        for point in self.trajectory:
            if point.t > t:
                break
            chosen = point
        return chosen


@dataclass(frozen=True)
class ScenarioGroundTruth:
    """The answer key. Never passed to the pipeline under evaluation."""

    scenario_id: str
    seed: int
    generator_version: str
    entities: Tuple[GroundTruthEntity, ...] = field(default_factory=tuple)
    #: observation_id -> entity_id, or None for a false positive.
    #: This is evaluation metadata. It deliberately does not live on the
    #: observation, because discovering which observations are spurious is the
    #: algorithm's job.
    observation_provenance: Mapping[str, Optional[str]] = field(default_factory=dict)

    def entity(self, entity_id: str) -> GroundTruthEntity:
        for candidate in self.entities:
            if candidate.entity_id == entity_id:
                return candidate
        raise KeyError(entity_id)

    def source_of(self, observation_id: str) -> Optional[str]:
        """Which entity produced an observation, or None if it was spurious."""
        return self.observation_provenance.get(observation_id)

    @property
    def false_positive_observation_ids(self) -> Tuple[str, ...]:
        return tuple(
            sorted(
                observation_id
                for observation_id, entity_id in self.observation_provenance.items()
                if entity_id is None
            )
        )


@dataclass(frozen=True)
class ScenarioMetadata:
    scenario_id: str
    scenario_name: str
    seed: int
    duration_s: float
    generator_version: str
    tick_hz: float
    t_zero: datetime
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioResult:
    """A generated scenario.

    The pipeline under evaluation receives `observations` and nothing else:

        scenario = generate_scenario(...)
        pipeline_input  = scenario.observations
        evaluation_only = scenario.ground_truth

    This whole module is on the protected side of the ground-truth boundary, so
    the M1 import guard prevents an evaluated module from reaching any of it.
    """

    metadata: ScenarioMetadata
    ground_truth: ScenarioGroundTruth
    observations: Tuple["SensorObservation", ...] = field(default_factory=tuple)
    #: Sensor heartbeats (scan records) in delivery order. Pipeline input.
    scans: tuple = ()
