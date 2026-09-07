#!/usr/bin/env python3
"""Deterministically export or verify DroneWatch's checked-in JSON Schemas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jsonschema.validators import validator_for

from contracts import observation_json_schema
from replay_artifacts import FixtureManifestV1, ReplayRunRecordV1, VisoEvidenceRecordV1


SCHEMA_DIRECTORY = ROOT / "schemas"
DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _artifact_schema(model: type, filename: str, title: str) -> dict[str, Any]:
    schema = model.model_json_schema(mode="validation")
    schema["$schema"] = DRAFT
    schema["$id"] = f"https://dronewatch.invalid/schemas/{filename}"
    schema["title"] = title
    schema["$comment"] = (
        "This schema defines the portable structure. Cross-field and pack-level semantic rules are "
        "normatively enforced by replay_artifacts.py and scripts/verify_replay_artifacts.py."
    )
    return schema


def expected_schemas() -> dict[str, dict[str, Any]]:
    return {
        "dronewatch.event.v1.schema.json": observation_json_schema(canonical=True),
        "dronewatch.event-input.v1.schema.json": observation_json_schema(canonical=False),
        "dronewatch.fixture-manifest.v1.schema.json": _artifact_schema(
            FixtureManifestV1,
            "dronewatch.fixture-manifest.v1.schema.json",
            "DroneWatch fixture manifest v1",
        ),
        "dronewatch.replay-run.v1.schema.json": _artifact_schema(
            ReplayRunRecordV1,
            "dronewatch.replay-run.v1.schema.json",
            "DroneWatch replay run record v1",
        ),
        "dronewatch.viso-evidence.v1.schema.json": _artifact_schema(
            VisoEvidenceRecordV1,
            "dronewatch.viso-evidence.v1.schema.json",
            "DroneWatch Viso supervised evidence record v1",
        ),
    }


def _encoded(schema: dict[str, Any]) -> bytes:
    return (json.dumps(schema, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _check_schema(schema: dict[str, Any]) -> None:
    validator = validator_for(schema)
    validator.check_schema(schema)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if any checked-in schema is missing or differs from the models",
    )
    args = parser.parse_args(argv)
    schemas = expected_schemas()
    for schema in schemas.values():
        _check_schema(schema)
    if args.check:
        stale: list[str] = []
        for filename, schema in schemas.items():
            path = SCHEMA_DIRECTORY / filename
            if not path.is_file() or path.read_bytes() != _encoded(schema):
                stale.append(filename)
        unexpected = sorted(
            path.name
            for path in SCHEMA_DIRECTORY.glob("*.schema.json")
            if path.name not in schemas
        )
        if stale or unexpected:
            details = []
            if stale:
                details.append("missing or stale: " + ", ".join(stale))
            if unexpected:
                details.append("unexpected: " + ", ".join(unexpected))
            raise SystemExit("schema check failed (" + "; ".join(details) + ")")
        print(f"schemas verified: {len(schemas)}")
        return 0

    SCHEMA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for filename, schema in schemas.items():
        (SCHEMA_DIRECTORY / filename).write_bytes(_encoded(schema))
    print(f"schemas exported: {len(schemas)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
