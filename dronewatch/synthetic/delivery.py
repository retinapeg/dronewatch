"""Temporal imperfections in delivery.

Observation time and arrival time are kept independent, which is what makes the
later latency and fusion work possible. Nothing here sets a quality flag on the
observation: an algorithm has to discover lateness, duplication and disorder
from the data, exactly as it would in a real deployment.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import List, Tuple

from ..domain.observation import SensorObservation
from .sensors import SensorModel


@dataclass
class DeliveryProfile:
    """How reports reach the system after they are made."""

    #: Probability an observation is delayed far beyond its sensor's latency.
    delay_probability: float = 0.0
    delay_extra_s: Tuple[float, float] = (1.5, 4.0)
    #: Probability an observation is delivered twice.
    duplicate_probability: float = 0.0
    #: Probability an observation is simply never delivered.
    loss_probability: float = 0.0
    #: Bursty delivery: observations held then released together.
    burst_probability: float = 0.0
    burst_hold_s: Tuple[float, float] = (0.5, 1.5)


def deliver(
    pairs: List[Tuple[float, SensorObservation]],
    sensors_by_id: dict,
    profile: DeliveryProfile,
    rng: random.Random,
) -> List[SensorObservation]:
    """Apply latency, delay, loss, duplication and bursts.

    Returns observations ordered by arrival time, which is the order a real
    system would see. Because arrival order is not observation order, the result
    can legitimately contain out-of-order observations.
    """
    delivered: List[Tuple[float, SensorObservation]] = []
    master = rng.getrandbits(64)

    for simulation_time, observation in pairs:
        sensor: SensorModel = sensors_by_id[observation.sensor_id]
        # One derived stream per report: removing or adding a report elsewhere
        # in the stream must not change this report's latency or duplication.
        rng = random.Random(f"{master}|{observation.observation_id}")

        if rng.random() < profile.loss_probability:
            continue

        latency = max(
            0.0, rng.gauss(sensor.latency_mean_s, max(1e-9, sensor.latency_jitter_s))
        )
        if rng.random() < profile.delay_probability:
            latency += rng.uniform(*profile.delay_extra_s)
        if rng.random() < profile.burst_probability:
            latency += rng.uniform(*profile.burst_hold_s)

        arrival = simulation_time + latency
        settled = replace(
            observation,
            received_at=observation.observed_at + timedelta(seconds=latency),
        )
        delivered.append((arrival, settled))

        if rng.random() < profile.duplicate_probability:
            # A genuine duplicate: the same report delivered a second time.
            # Same observation_id is what makes it detectable as a duplicate.
            extra = max(0.0, rng.gauss(0.15, 0.05))
            delivered.append(
                (
                    arrival + extra,
                    replace(
                        settled,
                        received_at=settled.received_at + timedelta(seconds=extra),
                    ),
                )
            )

    # Sort by arrival, then by observation id so ties are deterministic.
    delivered.sort(key=lambda item: (round(item[0], 9), item[1].observation_id))
    return [observation for _, observation in delivered]


def count_out_of_order(observations: List[SensorObservation]) -> int:
    """Observations that arrive after a later-observed report already arrived."""
    out_of_order = 0
    highest_seen = None
    for observation in observations:
        if highest_seen is not None and observation.observed_at < highest_seen:
            out_of_order += 1
        if highest_seen is None or observation.observed_at > highest_seen:
            highest_seen = observation.observed_at
    return out_of_order


def count_duplicates(observations: List[SensorObservation]) -> int:
    seen = set()
    duplicates = 0
    for observation in observations:
        if observation.observation_id in seen:
            duplicates += 1
        seen.add(observation.observation_id)
    return duplicates
