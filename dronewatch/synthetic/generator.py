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
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..domain.observation import Modality, SensorObservation
from .delivery import DeliveryProfile, deliver
from .groundtruth import (
    GroundTruthEntity,
    ScenarioGroundTruth,
    ScenarioMetadata,
    ScenarioResult,
)
from .rng import stream
from .scenarios import ENTITY_BUILDERS, generate_incoming_group, generate_swarm
from .sensors import (Counter, SensorModel, SensorScan, default_sensor_suite, observe_entity,
                      scan_records, spurious_observations)

GENERATOR_VERSION = "0.2.0"
DEFAULT_DURATION_S = 120.0
OPERATOR_DEMO_DURATION_S = 90.0
DEFAULT_TICK_HZ = 5.0

#: Fixed epoch so timestamps are reproducible across runs and machines.
T_ZERO = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FaultSpec:
    """What is injected into the observation stream, in simulation seconds.

    Faults change the reports that reach the estimator. They never touch the
    trajectories (separate RNG streams) and they are never applied in the
    browser.
    """
    #: Radar source outage: no detections and no heartbeats.
    radar_off: Tuple[Tuple[float, float], ...] = ()
    #: Every positional source off (radar, EO, IR, acoustic, RF positions).
    all_positional_off: Tuple[Tuple[float, float], ...] = ()
    #: Radar keeps scanning but its noise is multiplied: (start, end, factor).
    radar_degraded: Tuple[Tuple[float, float, float], ...] = ()
    #: Radar cadence override in Hz (sparse sampling); None keeps 2 Hz.
    radar_cadence_hz: Optional[float] = None
    #: One contact unobserved by radar while radar itself keeps scanning:
    #: (entity index 1-based, start, end).
    single_loss: Tuple[Tuple[int, float, float], ...] = ()
    #: Backup measurement source: None, "bearing" (bearing-only synthetic
    #: sensor at a known location) or "position" (the EO sensor's 25 m
    #: positions admitted to the tracker).
    backup: Optional[str] = None
    #: Delivery profile: "default" or "delayed" (late, out-of-order, bursty,
    #: duplicated reports, as in the delayed_out_of_order research scenario).
    delivery: str = "default"
    #: Aim the centre pair of the wedge across each other so their paths cross.
    crossing: bool = False

    @classmethod
    def parse(cls, text: Optional[str]) -> "FaultSpec":
        """radar:40-55;all:40-55;degrade:40-55x4;sparse:0.5;loss:2@40-55;backup:bearing"""
        if not text:
            return cls()
        radar, allp, deg, loss = [], [], [], []
        cadence, backup, delivery, crossing = None, None, "default", False
        for part in text.split(";"):
            part = part.strip()
            if not part:
                continue
            key, _, value = part.partition(":")
            key = key.strip().lower()
            if key == "radar":
                a, b = value.split("-"); radar.append((float(a), float(b)))
            elif key == "all":
                a, b = value.split("-"); allp.append((float(a), float(b)))
            elif key == "degrade":
                window, _, factor = value.partition("x")
                a, b = window.split("-"); deg.append((float(a), float(b), float(factor or 4.0)))
            elif key == "sparse":
                cadence = float(value)
            elif key == "loss":
                idx, _, window = value.partition("@")
                a, b = window.split("-"); loss.append((int(idx), float(a), float(b)))
            elif key == "backup":
                backup = value.strip().lower() or None
            elif key == "delivery":
                delivery = value.strip().lower() or "default"
            elif key == "crossing":
                crossing = True
            else:
                raise ValueError(f"unknown fault {key!r}")
        return cls(tuple(radar), tuple(allp), tuple(deg), cadence, tuple(loss), backup,
                   delivery, crossing)

    def label(self) -> str:
        bits = []
        for a, b in self.radar_off: bits.append(f"radar off {a:.0f}-{b:.0f} s")
        for a, b in self.all_positional_off: bits.append(f"all positional off {a:.0f}-{b:.0f} s")
        for a, b, f in self.radar_degraded: bits.append(f"radar noise x{f:g} {a:.0f}-{b:.0f} s")
        if self.radar_cadence_hz: bits.append(f"radar {self.radar_cadence_hz:g} Hz")
        for i, a, b in self.single_loss: bits.append(f"contact {i} unobserved {a:.0f}-{b:.0f} s")
        if self.backup: bits.append(f"backup {self.backup}")
        if self.delivery != "default": bits.append(f"{self.delivery} delivery")
        if self.crossing: bits.append("crossing pair")
        return ", ".join(bits) or "no faults"


POSITIONAL_SENSOR_IDS = ("radar-north", "eo-south", "ir-south", "acoustic-west", "rf-east")
BEARING_SENSOR_ID = "bearing-west"
#: A Viso Now-style visual detector: a camera at the site's north edge, cued
#: up the approach axis. It geolocates what it detects (calibrated camera,
#: known height, ground-plane intersection) with modest noise, but ONLY inside
#: its sector and range. Outside that it reports nothing at all.
VISO_SENSOR_ID = "viso-eo"
VISO_SENSOR_LOCATION = (0.0, 560.0)
VISO_FOV_CENTRE_DEG = 90.0          # looks north, up the approach
VISO_FOV_HALF_DEG = 32.0
VISO_MAX_RANGE_M = 1500.0
BACKUP_POSITION_SENSOR_ID = "eo-south"


def _tuned_sensors(scenario_name: str, duration: float,
                   faults: Optional[FaultSpec] = None,
                   entity_ids: Optional[List[str]] = None) -> List[SensorModel]:
    """Per-scenario sensor adjustments, applied to a fresh suite each time."""
    sensors = default_sensor_suite()
    by_id = {sensor.sensor_id: sensor for sensor in sensors}
    faults = faults or FaultSpec()

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
    # --- fault injection (observation stream only) -------------------------
    radar = by_id["radar-north"]
    if faults.radar_cadence_hz:
        radar.cadence_hz = faults.radar_cadence_hz
    radar.dropout_windows = list(radar.dropout_windows) + list(faults.radar_off)
    for window in faults.all_positional_off:
        for sid in POSITIONAL_SENSOR_IDS:
            by_id[sid].dropout_windows = list(by_id[sid].dropout_windows) + [window]
    radar.degraded_windows = list(faults.radar_degraded)
    if faults.single_loss and entity_ids:
        for index, a, b in faults.single_loss:
            if 1 <= index <= len(entity_ids):
                radar.blind_windows.setdefault(entity_ids[index - 1], []).append((a, b))
    if faults.backup == "viso":
        sensors.append(SensorModel(
            sensor_id=VISO_SENSOR_ID, modality=Modality.EO,
            cadence_hz=1.0, detection_probability=0.85, position_noise_m=18.0,
            latency_mean_s=0.35, latency_jitter_s=0.1, confidence_range=(0.6, 0.95),
            class_evidence_strength=0.5, false_positive_rate=0.0,
            location=VISO_SENSOR_LOCATION, fov_centre_deg=VISO_FOV_CENTRE_DEG,
            fov_half_deg=VISO_FOV_HALF_DEG, max_range_m=VISO_MAX_RANGE_M,
        ))
    if faults.backup == "bearing":
        sensors.append(SensorModel(
            sensor_id=BEARING_SENSOR_ID, modality=Modality.ACOUSTIC,
            cadence_hz=1.0, detection_probability=0.85, position_noise_m=0.0,
            latency_mean_s=0.2, latency_jitter_s=0.05, confidence_range=(0.3, 0.6),
            class_evidence_strength=0.0, false_positive_rate=0.0,
            location=(-900.0, -300.0), bearing_only=True, bearing_noise_deg=2.0,
        ))
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


def pipeline_input(
    scenario_name: str,
    *,
    seed: int,
    duration_s: float = DEFAULT_DURATION_S,
    tick_hz: float = DEFAULT_TICK_HZ,
    count: Optional[int] = None,
    faults: Optional[FaultSpec] = None,
) -> Tuple[Tuple[SensorObservation, ...], Tuple[SensorScan, ...]]:
    """Observations and sensor heartbeats only; ground truth is discarded.

    Fault injection happens here, in the generated stream, so what reaches the
    estimator is genuinely different. Nothing downstream can undo it.
    """
    result = generate_scenario(
        scenario_name, seed=seed, duration_s=duration_s, tick_hz=tick_hz, count=count,
        faults=faults,
    )
    return result.observations, result.scans


def generate_scenario(
    scenario_name: str,
    *,
    seed: int,
    duration_s: float = DEFAULT_DURATION_S,
    tick_hz: float = DEFAULT_TICK_HZ,
    count: Optional[int] = None,
    threat_fraction: float = 0.5,
    decoy_fraction: float = 0.5,
    faults: Optional[FaultSpec] = None,
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
            count or 6, seed=seed, duration=duration_s, dt=dt,
            crossing=bool(faults and faults.crossing),
        )
    else:
        entities = ENTITY_BUILDERS[scenario_name](seed, duration_s, dt)

    sensors = _tuned_sensors(scenario_name, duration_s, faults,
                             [e.entity_id for e in sorted(entities, key=lambda e: e.entity_id)])
    sensors_by_id = {sensor.sensor_id: sensor for sensor in sensors}
    sequence = Counter(seed)

    pairs: List[Tuple[float, SensorObservation]] = []
    provenance: Dict[str, Optional[str]] = {}

    # Deterministic ordering: sensors then entities, both by identifier.
    for sensor in sorted(sensors, key=lambda s: s.sensor_id):
        for entity in sorted(entities, key=lambda e: e.entity_id):
            # Independent streams per purpose and per (sensor, entity), so a
            # fault on one sensor cannot change another sensor's noise.
            observed = observe_entity(
                entity, sensor, t_zero=T_ZERO, duration_s=duration_s,
                rng=stream(seed, "detect", scenario_name, sensor.sensor_id, entity.entity_id),
                noise_rng=stream(seed, "noise", scenario_name, sensor.sensor_id, entity.entity_id),
                sequence=sequence,
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
    profile = _delivery_for(scenario_name)
    if faults and faults.delivery == "delayed":
        profile = _delivery_for("delayed_out_of_order")
    observations = deliver(
        pairs, sensors_by_id, profile,
        stream(seed, "delivery", scenario_name),
    )
    scans: List[SensorScan] = []
    for sensor in sensors:
        for scan in scan_records(sensor, duration_s):
            scans.append(replace(scan, t=scan.t))
    scans.sort(key=lambda s: (s.t, s.sensor_id))

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
            "faults": (faults or FaultSpec()).label(),
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
        metadata=metadata, ground_truth=ground_truth, observations=tuple(observations),
        scans=tuple(scans),
    )
