"""M2 synthetic generator contracts.

The numbering follows the 22 required checks. Determinism and ground-truth
isolation are the two properties everything downstream depends on, so both are
tested from several angles.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dronewatch.domain.enums import Modality, ObjectClass
from dronewatch.synthetic.delivery import count_duplicates, count_out_of_order
from dronewatch.synthetic.generator import generate_scenario
from dronewatch.synthetic.groundtruth import ControlMode, ScenarioGroundTruth
from dronewatch.synthetic.scenarios import SCENARIO_NAMES, generate_swarm
from dronewatch.synthetic.serialise import (
    observation_to_dict,
    read_observations_only,
    read_scenario,
    write_scenario,
)
from dronewatch.synthetic.stats import describe

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_SCENARIOS = (
    "single_threat", "single_decoy", "straight_flying_threat", "controlled_decoy",
    "mixed_threat_decoy", "sensor_disagreement", "sensor_dropout",
    "track_reacquisition_fixture", "false_positive", "delayed_out_of_order",
    "small_swarm",
)


def _payload(result):
    """A comparable, fully-expanded view of a generated scenario."""
    return {
        "observations": [observation_to_dict(o) for o in result.observations],
        "entities": [
            (e.entity_id, e.true_class.value, e.true_control_mode.value,
             [tuple(round(v, 6) for v in (p.t, p.x, p.y, p.z)) for p in e.trajectory])
            for e in result.ground_truth.entities
        ],
    }


# --- 1, 2, 19: determinism --------------------------------------------------

def test_1_same_seed_gives_an_identical_scenario():
    first = generate_scenario("mixed_threat_decoy", seed=42)
    second = generate_scenario("mixed_threat_decoy", seed=42)
    assert _payload(first) == _payload(second)


def test_2_a_different_seed_changes_stochastic_output():
    first = generate_scenario("mixed_threat_decoy", seed=42)
    other = generate_scenario("mixed_threat_decoy", seed=43)
    assert _payload(first) != _payload(other)
    # The scenario's intended structure survives the seed change.
    assert len(first.ground_truth.entities) == len(other.ground_truth.entities)
    assert {e.true_class for e in first.ground_truth.entities} == {
        e.true_class for e in other.ground_truth.entities
    }


def test_19_generation_does_not_depend_on_global_random_state():
    import random

    random.seed(1)
    first = _payload(generate_scenario("single_threat", seed=7))
    random.seed(999)
    [random.random() for _ in range(50)]
    second = _payload(generate_scenario("single_threat", seed=7))
    assert first == second


def test_all_registered_scenarios_generate():
    for name in SCENARIO_NAMES:
        result = generate_scenario(name, seed=5)
        assert result.observations, f"{name} produced no observations"


def test_required_scenarios_are_registered():
    for name in REQUIRED_SCENARIOS:
        assert name in SCENARIO_NAMES


# --- 3, 4, 5: ground-truth separation ---------------------------------------

def test_3_ground_truth_and_observations_are_separate_objects():
    scenario = generate_scenario("mixed_threat_decoy", seed=42)
    pipeline_input = scenario.observations
    evaluation_truth = scenario.ground_truth

    assert isinstance(evaluation_truth, ScenarioGroundTruth)
    assert all(not isinstance(o, ScenarioGroundTruth) for o in pipeline_input)
    # Nothing reachable from an observation leads back to the answer key.
    assert not hasattr(pipeline_input[0], "ground_truth")
    assert not hasattr(pipeline_input[0], "entity_id")


FORBIDDEN_KEYS = ("true_class", "true_control_mode", "control_mode", "entity_id",
                  "ground_truth", "is_false_positive", "intent")


def test_4_and_5_observations_never_expose_identity_or_control_mode():
    scenario = generate_scenario("mixed_threat_decoy", seed=42)
    for observation in scenario.observations:
        serialised = json.dumps(observation_to_dict(observation)).lower()
        for key in FORBIDDEN_KEYS:
            assert key not in serialised, f"{key} leaked into an observation"
        for mode in ControlMode:
            assert mode.value.lower() not in serialised


def test_class_evidence_is_never_an_oracle():
    """The true class may be a tendency, never a certainty."""
    from dronewatch.synthetic.sensors import MAX_CLASS_MASS

    scenario = generate_scenario("mixed_threat_decoy", seed=42)
    provenance = scenario.ground_truth.observation_provenance

    correct = 0
    counted = 0
    for observation in scenario.observations:
        assert observation.classification.top_probability <= MAX_CLASS_MASS + 1e-9
        entity_id = provenance.get(observation.observation_id)
        if entity_id is None:
            continue
        truth = scenario.ground_truth.entity(entity_id).true_class
        counted += 1
        if observation.classification.top_class is truth:
            correct += 1

    # Informative but fallible: not a coin flip, and emphatically not perfect.
    assert counted > 0
    assert correct < counted, "observations are acting as an oracle"


# --- 6, 7: timing -----------------------------------------------------------

def test_6_observation_times_are_monotonic_per_sensor_before_delivery():
    from dronewatch.synthetic.sensors import Counter, SensorModel, observe_entity
    from dronewatch.synthetic.generator import T_ZERO
    from dronewatch.synthetic.rng import stream

    entity = generate_scenario("single_threat", seed=42).ground_truth.entities[0]
    sensor = SensorModel(sensor_id="radar-test", modality=Modality.RADAR, cadence_hz=2.0)
    pairs = observe_entity(
        entity, sensor, t_zero=T_ZERO, duration_s=60.0,
        rng=stream(42, "test"), sequence=Counter(),
    )
    times = [observation.observed_at for _, observation in pairs]
    assert times == sorted(times)


def test_7_arrival_time_may_differ_from_observation_time():
    scenario = generate_scenario("mixed_threat_decoy", seed=42)
    assert any(o.received_at > o.observed_at for o in scenario.observations)
    # Arrival is never before observation.
    assert all(o.received_at >= o.observed_at for o in scenario.observations)
    assert all(o.transport_delay_s >= 0 for o in scenario.observations)


# --- 8, 9, 10: injected imperfections ---------------------------------------

def test_8_out_of_order_scenario_contains_out_of_order_arrivals():
    scenario = generate_scenario("delayed_out_of_order", seed=42)
    assert count_out_of_order(list(scenario.observations)) > 0


def test_9_duplicates_are_produced_where_configured():
    scenario = generate_scenario("delayed_out_of_order", seed=42)
    duplicates = count_duplicates(list(scenario.observations))
    assert duplicates > 0
    # A duplicate is the same report delivered twice, not a new report.
    seen = {}
    for observation in scenario.observations:
        if observation.observation_id in seen:
            assert observation.observed_at == seen[observation.observation_id]
        seen[observation.observation_id] = observation.observed_at


def test_10_dropout_removes_observations_over_the_configured_interval():
    scenario = generate_scenario("sensor_dropout", seed=42)
    duration = scenario.metadata.duration_s
    window = (duration / 3, 2 * duration / 3)

    def rf_times(result):
        return [
            o.raw["simulation_time_s"]
            for o in result.observations
            if o.modality is Modality.RF
        ]

    within = [t for t in rf_times(scenario) if window[0] <= t <= window[1]]
    assert within == [], "RF should be silent during its dropout window"
    assert rf_times(scenario), "RF should report outside the dropout window"


def test_reacquisition_fixture_contains_a_genuine_gap():
    scenario = generate_scenario("track_reacquisition_fixture", seed=42)
    times = sorted(o.raw["simulation_time_s"] for o in scenario.observations)
    largest_gap = max(b - a for a, b in zip(times, times[1:]))
    assert largest_gap > 10.0, f"expected an observation gap, largest was {largest_gap}"


# --- 11: false positives ----------------------------------------------------

def test_11_false_positives_have_no_ground_truth_entity():
    scenario = generate_scenario("false_positive", seed=42)
    spurious = scenario.ground_truth.false_positive_observation_ids
    assert spurious, "the false_positive scenario must contain spurious observations"

    by_id = {o.observation_id: o for o in scenario.observations}
    for observation_id in spurious:
        assert scenario.ground_truth.source_of(observation_id) is None
        observation = by_id.get(observation_id)
        if observation is None:
            continue
        # Structurally indistinguishable from a real detection.
        serialised = json.dumps(observation_to_dict(observation)).lower()
        assert "false" not in serialised.replace('"duplicate": false', "").replace(
            '"noisy": false', "").replace('"delayed": false', "").replace(
            '"out_of_order": false', "")


# --- 12, 13, 14, 15: identity and control are independent -------------------

def test_12_and_13_class_and_control_mode_are_independent():
    scenario = generate_scenario("mixed_threat_decoy", seed=42)
    pairs = {
        (e.true_class, e.true_control_mode) for e in scenario.ground_truth.entities
    }
    # A THREAT is not always CONTROLLED and a DECOY is not always PASSIVE.
    assert (ObjectClass.DECOY, ControlMode.CONTROLLED) in pairs

    swarm = generate_swarm(24, seed=42, duration=60.0, dt=0.2)
    classes = {e.true_class for e in swarm}
    modes = {e.true_control_mode for e in swarm}
    assert len(classes) > 1 and len(modes) > 1
    # Control mode is drawn independently, so both classes carry several modes.
    for object_class in classes:
        observed_modes = {
            e.true_control_mode for e in swarm if e.true_class is object_class
        }
        assert len(observed_modes) > 1, f"{object_class} has a fixed control mode"


def test_14_straight_flying_threat_counterexample_exists():
    entity = generate_scenario("straight_flying_threat", seed=42).ground_truth.entities[0]
    assert entity.true_class is ObjectClass.THREAT
    assert entity.true_control_mode is ControlMode.CONTROLLED


def test_15_controlled_decoy_counterexample_exists():
    entity = generate_scenario("controlled_decoy", seed=42).ground_truth.entities[0]
    assert entity.true_class is ObjectClass.DECOY
    assert entity.true_control_mode is ControlMode.CONTROLLED


# --- 16: every modality works -----------------------------------------------

def test_16_every_modality_generates_valid_observations():
    scenario = generate_scenario("mixed_threat_decoy", seed=42)
    seen = {o.modality for o in scenario.observations}
    for modality in (Modality.RADAR, Modality.RF, Modality.EO, Modality.IR,
                     Modality.ACOUSTIC):
        assert modality in seen, f"{modality} produced no observations"
    for observation in scenario.observations:
        assert observation.confidence is None or 0.0 <= observation.confidence <= 1.0
        assert observation.observed_at.tzinfo is not None


def test_rf_carries_signal_features_and_acoustic_does_not():
    scenario = generate_scenario("mixed_threat_decoy", seed=42)
    rf = [o for o in scenario.observations if o.modality is Modality.RF]
    acoustic = [o for o in scenario.observations if o.modality is Modality.ACOUSTIC]
    assert any(o.signals for o in rf)
    assert all(not o.signals for o in acoustic)


# --- 17, 18: serialisation and CLI ------------------------------------------

def test_17_serialisation_round_trips(tmp_path):
    original = generate_scenario("mixed_threat_decoy", seed=42)
    directory = write_scenario(original, tmp_path)
    restored = read_scenario(directory)

    assert restored.metadata == original.metadata
    assert restored.ground_truth.entities == original.ground_truth.entities
    assert restored.observations == original.observations


def test_serialisation_is_byte_identical_for_the_same_seed(tmp_path):
    first = write_scenario(generate_scenario("single_threat", seed=42), tmp_path / "a")
    second = write_scenario(generate_scenario("single_threat", seed=42), tmp_path / "b")
    for name in ("metadata.json", "ground_truth.json", "observations.jsonl"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_observations_can_be_loaded_without_touching_ground_truth(tmp_path):
    directory = write_scenario(generate_scenario("single_threat", seed=42), tmp_path)
    (directory / "ground_truth.json").unlink()
    observations = read_observations_only(directory)
    assert observations, "the pipeline must be able to load observations alone"


def test_18_cli_generates_a_scenario(tmp_path):
    output = tmp_path / "out"
    completed = subprocess.run(
        [sys.executable, "-m", "dronewatch.synthetic.generate",
         "--scenario", "small_swarm", "--seed", "42", "--count", "4",
         "--duration", "40", "--output", str(output)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "scenario     small_swarm" in completed.stdout
    assert "entities     4" in completed.stdout
    written = output / "small_swarm" / "seed-000042"
    assert (written / "metadata.json").exists()
    assert (written / "observations.jsonl").exists()


# --- swarm primitive --------------------------------------------------------

def test_swarm_is_parameterised_and_scales():
    small = generate_swarm(4, seed=42, duration=40.0, dt=0.2)
    larger = generate_swarm(16, seed=42, duration=40.0, dt=0.2)
    assert len(small) == 4 and len(larger) == 16
    with pytest.raises(ValueError):
        generate_swarm(0, seed=42, duration=40.0, dt=0.2)


def test_swarm_threat_fraction_is_respected():
    swarm = generate_swarm(10, seed=42, duration=40.0, dt=0.2,
                           threat_fraction=0.8, decoy_fraction=0.2)
    threats = [e for e in swarm if e.true_class is ObjectClass.THREAT]
    assert len(threats) == 8


# --- 17b: statistics report data, not algorithm performance -----------------

def test_statistics_describe_the_dataset_only():
    summary = describe(generate_scenario("delayed_out_of_order", seed=42))
    for key in ("entity_count", "observation_count", "observations_by_modality",
                "observations_per_entity", "false_positive_observations",
                "dropped_observations", "delayed_observations",
                "duplicate_observations", "duration_s"):
        assert key in summary
    for forbidden in ("classification_accuracy", "track_accuracy", "threat_accuracy"):
        assert forbidden not in summary
