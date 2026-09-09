"""Dataset statistics.

Describes the DATA only. No algorithm performance is reported here, because at
M2 no algorithm exists: there is no classifier, no tracker and no assessment to
score. Classification, track and threat accuracy arrive with the milestones that
introduce the things being measured.
"""
from __future__ import annotations

from collections import Counter as _Counter
from typing import Any, Dict

from .delivery import count_duplicates, count_out_of_order
from .groundtruth import ScenarioResult


def describe(result: ScenarioResult) -> Dict[str, Any]:
    observations = list(result.observations)
    provenance = result.ground_truth.observation_provenance

    by_modality = _Counter(o.modality.value for o in observations)
    per_entity = _Counter(
        entity_id for entity_id in provenance.values() if entity_id is not None
    )

    delivered_ids = {o.observation_id for o in observations}
    generated_ids = set(provenance)

    delayed = sum(
        1 for o in observations if (o.received_at - o.observed_at).total_seconds() > 1.0
    )

    return {
        "scenario_name": result.metadata.scenario_name,
        "seed": result.metadata.seed,
        "duration_s": result.metadata.duration_s,
        "entity_count": len(result.ground_truth.entities),
        "observation_count": len(observations),
        "observations_by_modality": dict(sorted(by_modality.items())),
        "observations_per_entity": dict(sorted(per_entity.items())),
        "false_positive_observations": len(
            result.ground_truth.false_positive_observation_ids
        ),
        "dropped_observations": len(generated_ids - delivered_ids),
        "delayed_observations": delayed,
        "duplicate_observations": count_duplicates(observations),
        "out_of_order_observations": count_out_of_order(observations),
    }
