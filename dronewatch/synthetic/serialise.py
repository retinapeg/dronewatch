"""Deterministic serialisation.

Layout on disk:

    <output>/<scenario-name>/seed-<nnnnnn>/
        metadata.json
        observations.jsonl
        ground_truth.json

JSON keys are sorted and floats are rounded, so the same scenario and seed
produce byte-identical files. Generated data is not committed; the generator and
the seed are the artefacts worth versioning.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..domain.classification import ClassificationDistribution
from ..domain.enums import Modality, ObjectClass
from ..domain.observation import (
    FramePosition,
    GeoPosition,
    QualitativePosition,
    QualityFlags,
    RangeBearing,
    SensorObservation,
    SignalFeature,
)
from .groundtruth import (
    ControlMode,
    GroundTruthEntity,
    ScenarioGroundTruth,
    ScenarioMetadata,
    ScenarioResult,
    TrajectoryPoint,
)

ROUND = 6


def _position_to_dict(position) -> Dict[str, Any]:
    if isinstance(position, GeoPosition):
        return {"kind": "geo", "latitude": position.latitude,
                "longitude": position.longitude, "altitude_m": position.altitude_m}
    if isinstance(position, FramePosition):
        return {"kind": "frame", "x": position.x, "y": position.y}
    if isinstance(position, RangeBearing):
        return {"kind": "range_bearing", "range_m": position.range_m,
                "bearing_deg": position.bearing_deg,
                "elevation_deg": position.elevation_deg}
    if isinstance(position, QualitativePosition):
        return {"kind": "qualitative", "described_as": position.described_as}
    raise TypeError(f"unserialisable position: {position!r}")


def _position_from_dict(data) -> Any:
    if data is None:
        return None
    kind = data["kind"]
    if kind == "geo":
        return GeoPosition(data["latitude"], data["longitude"], data["altitude_m"])
    if kind == "frame":
        return FramePosition(data["x"], data["y"])
    if kind == "range_bearing":
        return RangeBearing(data["range_m"], data["bearing_deg"], data["elevation_deg"])
    if kind == "qualitative":
        return QualitativePosition(data["described_as"])
    raise ValueError(f"unknown position kind: {kind}")


def observation_to_dict(observation: SensorObservation) -> Dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "sensor_id": observation.sensor_id,
        "modality": observation.modality.value,
        "observed_at": observation.observed_at.isoformat(),
        "received_at": observation.received_at.isoformat(),
        "position": _position_to_dict(observation.position) if observation.position else None,
        # Written at full precision on purpose. Rounding here accumulates error
        # across classes and can push the sum outside the distribution tolerance,
        # which would make a round-trip fail validation. Float repr is
        # deterministic, so full precision does not weaken reproducibility.
        "classification": {
            object_class.value: probability
            for object_class, probability in observation.classification.entries
        },
        "confidence": observation.confidence,
        "signals": [
            {"centre_frequency_hz": s.centre_frequency_hz, "amplitude": s.amplitude,
             "bandwidth_hz": s.bandwidth_hz}
            for s in observation.signals
        ],
        "associated_ids": list(observation.associated_ids),
        "raw": dict(observation.raw),
        "quality": {
            "noisy": observation.quality.noisy, "duplicate": observation.quality.duplicate,
            "delayed": observation.quality.delayed,
            "out_of_order": observation.quality.out_of_order,
        },
    }


def observation_from_dict(data: Dict[str, Any]) -> SensorObservation:
    quality = data.get("quality", {})
    return SensorObservation(
        observation_id=data["observation_id"],
        sensor_id=data["sensor_id"],
        modality=Modality(data["modality"]),
        observed_at=datetime.fromisoformat(data["observed_at"]),
        received_at=datetime.fromisoformat(data["received_at"]),
        position=_position_from_dict(data.get("position")),
        classification=ClassificationDistribution.normalised(
            {ObjectClass(key): value for key, value in data["classification"].items()}
        ),
        confidence=data.get("confidence"),
        signals=tuple(
            SignalFeature(s["centre_frequency_hz"], s["amplitude"], s["bandwidth_hz"])
            for s in data.get("signals", [])
        ),
        associated_ids=tuple(data.get("associated_ids", [])),
        raw=dict(data.get("raw", {})),
        quality=QualityFlags(
            noisy=quality.get("noisy", False), duplicate=quality.get("duplicate", False),
            delayed=quality.get("delayed", False),
            out_of_order=quality.get("out_of_order", False),
        ),
    )


def ground_truth_to_dict(truth: ScenarioGroundTruth) -> Dict[str, Any]:
    return {
        "scenario_id": truth.scenario_id,
        "seed": truth.seed,
        "generator_version": truth.generator_version,
        "entities": [
            {
                "entity_id": entity.entity_id,
                "true_class": entity.true_class.value,
                "true_control_mode": entity.true_control_mode.value,
                "intent": entity.intent,
                "spawn_time": entity.spawn_time,
                "end_time": entity.end_time,
                "trajectory": [
                    [point.t, point.x, point.y, point.z, point.vx, point.vy, point.vz]
                    for point in entity.trajectory
                ],
            }
            for entity in truth.entities
        ],
        "observation_provenance": dict(sorted(truth.observation_provenance.items())),
    }


def ground_truth_from_dict(data: Dict[str, Any]) -> ScenarioGroundTruth:
    return ScenarioGroundTruth(
        scenario_id=data["scenario_id"],
        seed=data["seed"],
        generator_version=data["generator_version"],
        entities=tuple(
            GroundTruthEntity(
                entity_id=entity["entity_id"],
                true_class=ObjectClass(entity["true_class"]),
                true_control_mode=ControlMode(entity["true_control_mode"]),
                intent=entity["intent"],
                spawn_time=entity["spawn_time"],
                end_time=entity["end_time"],
                trajectory=tuple(TrajectoryPoint(*point) for point in entity["trajectory"]),
            )
            for entity in data["entities"]
        ),
        observation_provenance=dict(data["observation_provenance"]),
    )


def metadata_to_dict(metadata: ScenarioMetadata) -> Dict[str, Any]:
    return {
        "scenario_id": metadata.scenario_id,
        "scenario_name": metadata.scenario_name,
        "seed": metadata.seed,
        "duration_s": metadata.duration_s,
        "generator_version": metadata.generator_version,
        "tick_hz": metadata.tick_hz,
        "t_zero": metadata.t_zero.isoformat(),
        "config": dict(sorted(metadata.config.items())),
    }


def metadata_from_dict(data: Dict[str, Any]) -> ScenarioMetadata:
    return ScenarioMetadata(
        scenario_id=data["scenario_id"], scenario_name=data["scenario_name"],
        seed=data["seed"], duration_s=data["duration_s"],
        generator_version=data["generator_version"], tick_hz=data["tick_hz"],
        t_zero=datetime.fromisoformat(data["t_zero"]), config=dict(data["config"]),
    )


def _dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)


def write_scenario(result: ScenarioResult, output_root: Path) -> Path:
    directory = (
        Path(output_root)
        / result.metadata.scenario_name
        / f"seed-{result.metadata.seed:06d}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata.json").write_text(
        _dumps(metadata_to_dict(result.metadata)) + "\n", encoding="utf-8"
    )
    (directory / "ground_truth.json").write_text(
        _dumps(ground_truth_to_dict(result.ground_truth)) + "\n", encoding="utf-8"
    )
    with (directory / "observations.jsonl").open("w", encoding="utf-8") as handle:
        for observation in result.observations:
            handle.write(
                json.dumps(observation_to_dict(observation), sort_keys=True,
                           ensure_ascii=False) + "\n"
            )
    return directory


def read_scenario(directory: Path) -> ScenarioResult:
    directory = Path(directory)
    metadata = metadata_from_dict(
        json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    )
    ground_truth = ground_truth_from_dict(
        json.loads((directory / "ground_truth.json").read_text(encoding="utf-8"))
    )
    observations = []
    with (directory / "observations.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                observations.append(observation_from_dict(json.loads(line)))
    return ScenarioResult(
        metadata=metadata, ground_truth=ground_truth, observations=tuple(observations)
    )


def read_observations_only(directory: Path):
    """What the evaluated pipeline is allowed to load.

    Deliberately does not touch ground_truth.json.
    """
    observations = []
    with (Path(directory) / "observations.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                observations.append(observation_from_dict(json.loads(line)))
    return tuple(observations)
