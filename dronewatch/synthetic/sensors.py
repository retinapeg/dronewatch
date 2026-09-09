"""Synthetic sensor models.

ALL CHARACTERISTICS HERE ARE INVENTED SIMULATION ABSTRACTIONS.

Nothing in this module represents the performance of any real sensor, product or
military system. The numbers exist so that different modalities behave
differently and fusion therefore has a reason to exist. They are not claims.

Two rules constrain what a synthetic observation may contain:

  * no ground-truth class and no ground-truth control mode
  * no entity identifier

Class evidence is deliberately noisy and never certain: the true class is only
ever a weighted tendency in the distribution, capped below 1.0, with UNKNOWN
always retaining mass.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from ..domain.classification import ClassificationDistribution
from ..domain.enums import Modality, ObjectClass
from ..domain.observation import (
    GeoPosition,
    SensorObservation,
    SignalFeature,
)
from .groundtruth import GroundTruthEntity, TrajectoryPoint

#: The most probability mass a synthetic observation may place on any class.
#: Keeps an observation informative without ever being an oracle.
MAX_CLASS_MASS = 0.70

#: Classes a synthetic sensor is willing to hypothesise about.
CANDIDATE_CLASSES: Tuple[ObjectClass, ...] = (
    ObjectClass.THREAT,
    ObjectClass.DECOY,
    ObjectClass.BENIGN,
)


@dataclass
class SensorModel:
    """A synthetic sensor. Every field is a simulation knob, not a specification."""

    sensor_id: str
    modality: Modality
    cadence_hz: float = 1.0
    detection_probability: float = 0.9
    position_noise_m: float = 15.0
    latency_mean_s: float = 0.2
    latency_jitter_s: float = 0.05
    confidence_range: Tuple[float, float] = (0.4, 0.8)
    #: 0 means the sensor contributes no class evidence at all.
    class_evidence_strength: float = 0.3
    false_positive_rate: float = 0.0
    #: Simulation-time windows in which this sensor produces nothing.
    dropout_windows: List[Tuple[float, float]] = field(default_factory=list)
    #: Emits RF signal features.
    emits_signal_features: bool = False
    #: Scales detection probability, standing in for synthetic visibility.
    visibility: float = 1.0
    #: Sensor location in simulation metres; required for bearing-only sensors.
    location: Optional[Tuple[float, float]] = None
    #: A bearing-only sensor reports the angle from `location` to the target,
    #: mathematical convention, and no position at all.
    bearing_only: bool = False
    bearing_noise_deg: float = 2.0
    #: Windows in which the sensor scans normally but its position noise is
    #: multiplied by the given factor (quality degradation, not outage).
    degraded_windows: List[Tuple[float, float, float]] = field(default_factory=list)
    #: Windows in which the sensor scans normally but cannot see the named
    #: entities (a single contact temporarily unobserved). Keyed by entity id;
    #: the generator owns ground truth, the pipeline never sees this.
    blind_windows: Dict[str, List[Tuple[float, float]]] = field(default_factory=dict)

    def is_dropped_out(self, t: float) -> bool:
        """Source outage: no scans, no heartbeat, nothing at all."""
        return any(start <= t <= end for start, end in self.dropout_windows)

    def noise_factor(self, t: float) -> float:
        for start, end, factor in self.degraded_windows:
            if start <= t <= end:
                return factor
        return 1.0

    def is_blind_to(self, entity_id: str, t: float) -> bool:
        return any(start <= t <= end for start, end in self.blind_windows.get(entity_id, ()))

    @property
    def interval_s(self) -> float:
        return 1.0 / self.cadence_hz


def default_sensor_suite() -> List[SensorModel]:
    """One sensor per modality with deliberately different synthetic character.

    RADAR      steady positional evidence, weak class evidence, some clutter
    RF         intermittent, carries signal features, can vanish
    EO         good class evidence when it sees anything, visibility dependent
    IR         similar to EO, less positional precision
    ACOUSTIC   noisy positions, useful only as corroboration
    """
    return [
        SensorModel(
            sensor_id="radar-north", modality=Modality.RADAR,
            cadence_hz=2.0, detection_probability=0.92, position_noise_m=12.0,
            latency_mean_s=0.15, confidence_range=(0.45, 0.8),
            class_evidence_strength=0.25, false_positive_rate=0.02,
        ),
        SensorModel(
            sensor_id="rf-east", modality=Modality.RF,
            cadence_hz=0.5, detection_probability=0.55, position_noise_m=120.0,
            latency_mean_s=0.4, latency_jitter_s=0.2, confidence_range=(0.3, 0.7),
            class_evidence_strength=0.35, emits_signal_features=True,
        ),
        SensorModel(
            sensor_id="eo-south", modality=Modality.EO,
            cadence_hz=1.0, detection_probability=0.7, position_noise_m=25.0,
            latency_mean_s=0.25, confidence_range=(0.5, 0.9),
            class_evidence_strength=0.55, visibility=0.9,
        ),
        SensorModel(
            sensor_id="ir-south", modality=Modality.IR,
            cadence_hz=1.0, detection_probability=0.65, position_noise_m=40.0,
            latency_mean_s=0.25, confidence_range=(0.4, 0.85),
            class_evidence_strength=0.45, visibility=0.95,
        ),
        SensorModel(
            sensor_id="acoustic-west", modality=Modality.ACOUSTIC,
            cadence_hz=0.5, detection_probability=0.5, position_noise_m=200.0,
            latency_mean_s=0.8, latency_jitter_s=0.3, confidence_range=(0.2, 0.5),
            class_evidence_strength=0.1,
        ),
    ]


def _class_evidence(
    true_class: ObjectClass, strength: float, rng: random.Random
) -> ClassificationDistribution:
    """Noisy, capped class evidence.

    With `strength` 0 the observation is uninformative. As strength rises the
    true class becomes more likely to attract mass, but never certainty, and
    the sensor sometimes favours the wrong class outright.
    """
    if strength <= 0:
        return ClassificationDistribution.unknown()

    scores: Dict[ObjectClass, float] = {
        candidate: rng.uniform(0.05, 0.35) for candidate in CANDIDATE_CLASSES
    }
    # The sensor is only sometimes right, in proportion to its strength.
    favoured = true_class if rng.random() < strength else rng.choice(CANDIDATE_CLASSES)
    if favoured in scores:
        scores[favoured] += rng.uniform(0.3, 0.9) * strength
    scores[ObjectClass.UNKNOWN] = rng.uniform(0.15, 0.5) * (1.0 - strength) + 0.1

    distribution = ClassificationDistribution.from_scores(scores)
    top_class, top_probability = distribution.top()
    if top_probability > MAX_CLASS_MASS:
        # Bleed the excess away from the top class so no observation is ever
        # an oracle. Into UNKNOWN normally; when UNKNOWN itself is on top,
        # spread it over the other hypotheses instead.
        adjusted = distribution.as_dict()
        excess = top_probability - MAX_CLASS_MASS
        adjusted[top_class] = MAX_CLASS_MASS
        if top_class is not ObjectClass.UNKNOWN:
            adjusted[ObjectClass.UNKNOWN] = adjusted.get(ObjectClass.UNKNOWN, 0.0) + excess
        else:
            others = [c for c in adjusted if c is not top_class]
            if others:
                for c in others:
                    adjusted[c] += excess / len(others)
            else:
                adjusted[top_class] = top_probability
        distribution = ClassificationDistribution.normalised(adjusted)
    return distribution


def _measure(point: TrajectoryPoint, sensor: SensorModel, rng: random.Random):
    """True state to measured state. Sensors only see the world through noise."""
    sigma = sensor.position_noise_m
    return (
        point.x + rng.gauss(0.0, sigma),
        point.y + rng.gauss(0.0, sigma),
        max(0.0, point.z + rng.gauss(0.0, sigma / 2)),
    )


def _to_position(x: float, y: float, z: float) -> GeoPosition:
    """Simulation metres carried in a generic position container.

    Values are simulation-frame offsets, not geographic coordinates. M3 will
    introduce a proper simulation-frame position type; reusing GeoPosition here
    avoids changing the M1 domain during M2.
    """
    return GeoPosition(latitude=round(x, 4), longitude=round(y, 4), altitude_m=round(z, 4))


def observe_entity(
    entity: GroundTruthEntity,
    sensor: SensorModel,
    *,
    t_zero: datetime,
    duration_s: float,
    rng: random.Random,
    sequence: "Counter",
    noise_rng: Optional[random.Random] = None,
) -> List[Tuple[float, SensorObservation]]:
    """Generate one sensor's observations of one entity.

    Returns (simulation_time, observation) pairs. Arrival effects are applied
    later by the delivery layer.

    `rng` decides detection, `noise_rng` (defaults to `rng`) draws measurement
    noise. Both are consumed at every scan time, including scans suppressed by
    a fault window, so changing a fault configuration changes only the
    affected reports and nothing else.
    """
    noise_rng = noise_rng or rng
    results: List[Tuple[float, SensorObservation]] = []
    t = max(0.0, entity.spawn_time)
    end = min(duration_s, entity.end_time or duration_s)
    while t <= end:
        detected = rng.random() <= sensor.detection_probability * sensor.visibility
        gauss = [noise_rng.gauss(0.0, 1.0) for _ in range(3)]
        conf = noise_rng.uniform(*sensor.confidence_range)
        class_rng = random.Random(noise_rng.random())
        if sensor.is_dropped_out(t) or not detected or sensor.is_blind_to(entity.entity_id, t):
            t += sensor.interval_s
            continue

        point = entity.state_at(t)
        factor = sensor.noise_factor(t)
        signals: Tuple[SignalFeature, ...] = ()
        if sensor.emits_signal_features:
            signals = (
                SignalFeature(
                    centre_frequency_hz=round(class_rng.uniform(2.40e9, 2.48e9), 1),
                    amplitude=round(class_rng.uniform(0.1, 1.0), 4),
                    bandwidth_hz=round(class_rng.uniform(1e6, 2e7), 1),
                ),
            )
        raw = {
            "sensor_id": sensor.sensor_id,
            "modality": sensor.modality.value,
            "simulation_time_s": round(t, 4),
            "synthetic": True,
        }
        if sensor.bearing_only:
            sx, sy = sensor.location or (0.0, 0.0)
            sigma = math.radians(sensor.bearing_noise_deg) * factor
            bearing = math.atan2(point.y - sy, point.x - sx) + gauss[0] * sigma
            position = None
            raw.update({"kind": "bearing", "bearing_rad": round(bearing, 6),
                        "sensor_xy": [sx, sy], "sigma_rad": round(sigma, 6)})
        else:
            sigma = sensor.position_noise_m * factor
            x = point.x + gauss[0] * sigma
            y = point.y + gauss[1] * sigma
            z = max(0.0, point.z + gauss[2] * sigma / 2)
            position = _to_position(x, y, z)
            raw.update({"kind": "position", "sigma_m": round(sigma, 3)})

        observation = SensorObservation(
            observation_id=sequence.derived(sensor.sensor_id, entity.entity_id, t),
            sensor_id=sensor.sensor_id,
            modality=sensor.modality,
            observed_at=t_zero + timedelta(seconds=t),
            received_at=t_zero + timedelta(seconds=t),
            position=position,
            classification=_class_evidence(
                entity.true_class, sensor.class_evidence_strength, class_rng
            ),
            confidence=round(conf, 4),
            signals=signals,
            raw=raw,
        )
        results.append((t, observation))
        t += sensor.interval_s
    return results


@dataclass(frozen=True)
class SensorScan:
    """A heartbeat: the sensor ran at time t. Carries no detection.

    Source health is derived from these, never from the absence of
    detections, because a dead sensor and an empty sky produce the same
    detection stream.
    """
    sensor_id: str
    t: float
    noise_sigma_m: Optional[float]


def scan_records(sensor: SensorModel, duration_s: float) -> List[SensorScan]:
    scans: List[SensorScan] = []
    t = 0.0
    while t <= duration_s:
        if not sensor.is_dropped_out(t):
            sigma = None if sensor.bearing_only else sensor.position_noise_m * sensor.noise_factor(t)
            scans.append(SensorScan(sensor.sensor_id, round(t, 4), sigma))
        t += sensor.interval_s
    return scans


def spurious_observations(
    sensor: SensorModel,
    *,
    t_zero: datetime,
    duration_s: float,
    rng: random.Random,
    sequence: "Counter",
    extent_m: float = 3000.0,
) -> List[Tuple[float, SensorObservation]]:
    """Observations with no entity behind them.

    Structurally indistinguishable from a real detection. Nothing marks them;
    discovering that they are spurious is the algorithm's job.
    """
    results: List[Tuple[float, SensorObservation]] = []
    if sensor.false_positive_rate <= 0:
        return results
    t = 0.0
    while t <= duration_s:
        if not sensor.is_dropped_out(t) and rng.random() < sensor.false_positive_rate:
            low, high = sensor.confidence_range
            results.append(
                (
                    t,
                    SensorObservation(
                        observation_id=sequence.next(sensor.sensor_id),
                        sensor_id=sensor.sensor_id,
                        modality=sensor.modality,
                        observed_at=t_zero + timedelta(seconds=t),
                        received_at=t_zero + timedelta(seconds=t),
                        position=_to_position(
                            rng.uniform(-extent_m, extent_m),
                            rng.uniform(-extent_m, extent_m),
                            rng.uniform(0.0, 300.0),
                        ),
                        classification=_class_evidence(
                            rng.choice(CANDIDATE_CLASSES),
                            sensor.class_evidence_strength,
                            rng,
                        ),
                        confidence=round(rng.uniform(low, min(high, 0.6)), 4),
                        raw={
                            "sensor_id": sensor.sensor_id,
                            "modality": sensor.modality.value,
                            "simulation_time_s": round(t, 4),
                            "synthetic": True,
                        },
                    ),
                )
            )
        t += sensor.interval_s
    return results


class Counter:
    """Deterministic observation identifiers, stable across runs.

    Identifiers are derived from what was observed (sensor, subject, time)
    through a hash, so injecting a fault into one sensor cannot renumber
    another sensor's reports. The subject is hashed with the seed and never
    appears in the identifier: the pipeline must not be able to read ground
    truth out of an id.
    """

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed
        self._counts: Dict[str, int] = {}

    def next(self, sensor_id: str) -> str:
        index = self._counts.get(sensor_id, 0)
        self._counts[sensor_id] = index + 1
        return f"{sensor_id}-{index:06d}"

    def derived(self, sensor_id: str, subject: str, t: float) -> str:
        digest = hashlib.sha1(f"{self._seed}|{sensor_id}|{subject}|{t:.3f}".encode()).hexdigest()
        return f"{sensor_id}-{digest[:10]}"
