"""Scenario generation.

    scenario = generate_scenario("mixed_threat_decoy", seed=42)
    pipeline_input  = scenario.observations      # what the system may see
    evaluation_only = scenario.ground_truth      # the answer key

Reproducibility contract: scenario name + seed + config determines the output.
Every random draw comes from a named, derived RNG, so adding a new scenario
cannot disturb the output of an existing one.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..domain.observation import SensorObservation
from .delivery import DeliveryProfile, deliver
from .groundtruth import (
    GroundTruthEntity,
    ScenarioGroundTruth,
    ScenarioMetadata,
    ScenarioResult,
)
from .rng import stream
from .scenarios import ENTITY_BUILDERS, generate_incoming_group, generate_swarm
from .sensors import Counter, SensorModel, default_sensor_suite, observe_entity, spurious_observations

GENERATOR_VERSION = "0.2.0"
DEFAULT_DURATION_S = 120.0
OPERATOR_DEMO_DURATION_S = 90.0
DEFAULT_TICK_HZ = 5.0

#: Fixed epoch so timestamps are reproducible across runs and machines.
T_ZERO = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def _tuned_sensors(scenario_name: str, duration: float) -> List[SensorModel]:
    """Per-scenario sensor adjustments, applied to a fresh suite each time."""
    sensors = default_sensor_suite()
    by_id = {sensor.sensor_id: sensor for sensor in sensors}

    if scenario_name.startswith("operator_demo"):
        # A legible baseline: modest noise, no clutter. Harder conditions stay
        # in the research scenarios rather than the first screen an operator sees.
        for sensor in sensors:
            sensor.false_positive_rate = 0.0
        by_id["radar-north"].position_noise_m = 10.0
        by_id["radar-north"].detection_probability = 0.95
        if scenario_name == "operator_demo_signal_loss":
            # One deliberate, understandable gap so coasting and stale states
            # can be demonstrated and recovered from.
            by_id["radar-north"].dropout_windows = [(40.0, 52.0)]
    elif scenario_name == "sensor_dropout":
        # RF disappears entirely for the middle third of the scenario.
        by_id["rf-east"].dropout_windows = [(duration / 3, 2 * duration / 3)]
    elif scenario_name == "track_reacquisition_fixture":
        # Every sensor goes quiet, creating a genuine observation gap.
        for sensor in sensors:
            sensor.dropout_windows = [(duration * 0.4, duration * 0.65)]
    elif scenario_name == "sensor_disagreement":
        # EO and IR pull confidently in different directions; radar stays weak.
        by_id["eo-south"].class_evidence_strength = 0.65
        by_id["ir-south"].class_evidence_strength = 0.05
        by_id["radar-north"].class_evidence_strength = 0.05
        by_id["acoustic-west"].class_evidence_strength = 0.0
    elif scenario_name == "false_positive":
        for sensor in sensors:
            sensor.false_positive_rate = 0.25
    return sensors


def _delivery_for(scenario_name: str) -> DeliveryProfile:
    if scenario_name == "delayed_out_of_order":
        return DeliveryProfile(
            delay_probability=0.35, delay_extra_s=(2.0, 6.0),
            duplicate_probability=0.12, burst_probability=0.2,
        )
    if scenario_name == "small_swarm":
        return DeliveryProfile(
            delay_probability=0.1, duplicate_probability=0.05, burst_probability=0.25
        )
    return DeliveryProfile(duplicate_probability=0.02)


def observations_only(
    scenario_name: str,
    *,
    seed: int,
    duration_s: float = DEFAULT_DURATION_S,
    tick_hz: float = DEFAULT_TICK_HZ,
    count: Optional[int] = None,
) -> Tuple[SensorObservation, ...]:
    """Generate a scenario and return ONLY what the pipeline may see.

    The in-memory equivalent of `serialise.read_observations_only`. Ground truth
    is discarded before returning, so a caller cannot reach entity identities,
    true classes, control modes or observation provenance even by accident.

    This is the accessor the preview API uses. Everything ground-truth-shaped
    stays inside this function.
    """
    result = generate_scenario(
        scenario_name, seed=seed, duration_s=duration_s, tick_hz=tick_hz, count=count
    )
    return result.observations


def generate_scenario(
    scenario_name: str,
    *,
    seed: int,
    duration_s: float = DEFAULT_DURATION_S,
    tick_hz: float = DEFAULT_TICK_HZ,
    count: Optional[int] = None,
    threat_fraction: float = 0.5,
    decoy_fraction: float = 0.5,
) -> ScenarioResult:
    if scenario_name not in ENTITY_BUILDERS:
        raise KeyError(
            f"unknown scenario {scenario_name!r}; known: {sorted(ENTITY_BUILDERS)}"
        )

    dt = 1.0 / tick_hz

    if scenario_name == "small_swarm":
        entities: List[GroundTruthEntity] = generate_swarm(
            count or 6, seed=seed, duration=duration_s, dt=dt,
            threat_fraction=threat_fraction, decoy_fraction=decoy_fraction,
        )
    elif scenario_name.startswith("operator_demo"):
        entities = generate_incoming_group(
            count or 6, seed=seed, duration=duration_s, dt=dt
        )
    else:
        entities = ENTITY_BUILDERS[scenario_name](seed, duration_s, dt)

    sensors = _tuned_sensors(scenario_name, duration_s)
    sensors_by_id = {sensor.sensor_id: sensor for sensor in sensors}
    sequence = Counter()

    pairs: List[Tuple[float, SensorObservation]] = []
    provenance: Dict[str, Optional[str]] = {}

    # Deterministic ordering: sensors then entities, both by identifier.
    for sensor in sorted(sensors, key=lambda s: s.sensor_id):
        sensor_rng = stream(seed, "observe", scenario_name, sensor.sensor_id)
        for entity in sorted(entities, key=lambda e: e.entity_id):
            observed = observe_entity(
                entity, sensor, t_zero=T_ZERO, duration_s=duration_s,
                rng=sensor_rng, sequence=sequence,
            )
            for _, observation in observed:
                provenance[observation.observation_id] = entity.entity_id
            pairs.extend(observed)

        spurious = spurious_observations(
            sensor, t_zero=T_ZERO, duration_s=duration_s,
            rng=stream(seed, "spurious", scenario_name, sensor.sensor_id),
            sequence=sequence,
        )
        for _, observation in spurious:
            provenance[observation.observation_id] = None
        pairs.extend(spurious)

    pairs.sort(key=lambda item: (round(item[0], 9), item[1].observation_id))
    observations = deliver(
        pairs, sensors_by_id, _delivery_for(scenario_name),
        stream(seed, "delivery", scenario_name),
    )

    metadata = ScenarioMetadata(
        scenario_id=f"{scenario_name}-seed-{seed:06d}",
        scenario_name=scenario_name,
        seed=seed,
        duration_s=duration_s,
        generator_version=GENERATOR_VERSION,
        tick_hz=tick_hz,
        t_zero=T_ZERO,
        config={
            "count": count,
            "threat_fraction": threat_fraction,
            "decoy_fraction": decoy_fraction,
        },
    )
    ground_truth = ScenarioGroundTruth(
        scenario_id=metadata.scenario_id,
        seed=seed,
        generator_version=GENERATOR_VERSION,
        entities=tuple(entities),
        observation_provenance=provenance,
    )
    return ScenarioResult(
        metadata=metadata, ground_truth=ground_truth, observations=tuple(observations)
    )
