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

    def is_dropped_out(self, t: float) -> bool:
        return any(start <= t <= end for start, end in self.dropout_windows)

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
        # Bleed the excess into UNKNOWN so no observation is ever an oracle.
        adjusted = distribution.as_dict()
        excess = top_probability - MAX_CLASS_MASS
        adjusted[top_class] = MAX_CLASS_MASS
        adjusted[ObjectClass.UNKNOWN] = adjusted.get(ObjectClass.UNKNOWN, 0.0) + excess
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
) -> List[Tuple[float, SensorObservation]]:
    """Generate one sensor's observations of one entity.

    Returns (simulation_time, observation) pairs. Arrival effects are applied
    later by the delivery layer.
    """
    results: List[Tuple[float, SensorObservation]] = []
    t = max(0.0, entity.spawn_time)
    end = min(duration_s, entity.end_time or duration_s)
    while t <= end:
        if sensor.is_dropped_out(t):
            t += sensor.interval_s
            continue
        if rng.random() > sensor.detection_probability * sensor.visibility:
            t += sensor.interval_s
            continue

        point = entity.state_at(t)
        x, y, z = _measure(point, sensor, rng)
        low, high = sensor.confidence_range
        signals: Tuple[SignalFeature, ...] = ()
        if sensor.emits_signal_features:
            signals = (
                SignalFeature(
                    centre_frequency_hz=round(rng.uniform(2.40e9, 2.48e9), 1),
                    amplitude=round(rng.uniform(0.1, 1.0), 4),
                    bandwidth_hz=round(rng.uniform(1e6, 2e7), 1),
                ),
            )

        observation = SensorObservation(
            observation_id=sequence.next(sensor.sensor_id),
            sensor_id=sensor.sensor_id,
            modality=sensor.modality,
            observed_at=t_zero + timedelta(seconds=t),
            # Overwritten by the delivery layer; a placeholder equal to the
            # observation time keeps the object valid in the meantime.
            received_at=t_zero + timedelta(seconds=t),
            position=_to_position(x, y, z),
            classification=_class_evidence(
                entity.true_class, sensor.class_evidence_strength, rng
            ),
            confidence=round(rng.uniform(low, high), 4),
            signals=signals,
            raw={
                "sensor_id": sensor.sensor_id,
                "modality": sensor.modality.value,
                "simulation_time_s": round(t, 4),
                "synthetic": True,
            },
        )
        results.append((t, observation))
        t += sensor.interval_s
    return results


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
    """Deterministic observation identifiers, stable across runs."""

    def __init__(self) -> None:
        self._counts: Dict[str, int] = {}

    def next(self, sensor_id: str) -> str:
        index = self._counts.get(sensor_id, 0)
        self._counts[sensor_id] = index + 1
        return f"{sensor_id}-{index:06d}"
