#!/usr/bin/env python3
"""Validate the V0.2 manifest/template and optionally external fixture bytes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from replay_artifacts import (
    ArtifactJsonError as ReplayArtifactJsonError,
    EvidenceStatus,
    ExpectedResult,
    FixtureManifestV1,
    VisoEvidenceRecordV1,
    load_fixture_manifest,
    read_artifact_bytes,
    sha256_file,
    strict_json_object,
)


DEFAULT_MANIFEST = ROOT / "fixtures" / "halmstad-selection.v1.json"
DEFAULT_TEMPLATE = ROOT / "evidence" / "viso-run-template.v1.json"


class ArtifactJsonError(ValueError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = strict_json_object(read_artifact_bytes(path))
    except (OSError, ValueError, ReplayArtifactJsonError) as error:
        raise ArtifactJsonError from error
    return value


def _validate_json_model(model: type, value: dict[str, Any]):
    # JSON-mode validation retains strict scalar typing while accepting JSON
    # arrays/strings for tuple, enum, date, and datetime fields.
    return model.model_validate_json(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    )


def _verify_file(path: Path, *, expected_bytes: int, expected_sha256: str) -> None:
    if not path.is_file():
        raise ArtifactJsonError("required external fixture file is absent")
    if path.stat().st_size != expected_bytes:
        raise ArtifactJsonError("external fixture size does not match manifest")
    if sha256_file(path) != expected_sha256:
        raise ArtifactJsonError("external fixture digest does not match manifest")


def _verify_external_pack(manifest: FixtureManifestV1, media_directory: Path) -> int:
    if not media_directory.is_dir():
        raise ArtifactJsonError("external media directory is absent")
    licence = manifest.dataset.licences.data
    _verify_file(
        media_directory / PurePosixPath(licence.source_path).name,
        expected_bytes=licence.source_bytes,
        expected_sha256=licence.source_sha256,
    )
    verified = 1
    for fixture in manifest.fixtures:
        _verify_file(
            media_directory / fixture.derived_filename,
            expected_bytes=fixture.derived_bytes,
            expected_sha256=fixture.derived_sha256,
        )
        annotation_basename = PurePosixPath(fixture.annotation.source_path).name
        _verify_file(
            media_directory / annotation_basename,
            expected_bytes=fixture.annotation.source_bytes,
            expected_sha256=fixture.annotation.source_sha256,
        )
        verified += 2
    return verified


def _validate_evidence_manifest_link(
    manifest: FixtureManifestV1, evidence: VisoEvidenceRecordV1
) -> None:
    try:
        fixture = manifest.fixture(evidence.fixture_id)
    except KeyError as error:
        raise ArtifactJsonError("evidence fixture is absent from the manifest") from error
    if evidence.fixture_sha256 != fixture.derived_sha256:
        raise ArtifactJsonError("evidence fixture digest does not match the manifest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument(
        "--media-dir",
        type=Path,
        help="optional external directory containing exact selected MP4, MAT, and LICENSE bytes",
    )
    parser.add_argument(
        "--evidence-record",
        type=Path,
        help="optional filled, redacted supervised evidence record to validate",
    )
    args = parser.parse_args(argv)

    try:
        manifest = load_fixture_manifest(args.manifest)
        template = _validate_json_model(VisoEvidenceRecordV1, _load_object(args.template))
        if template.record_status is not EvidenceStatus.TEMPLATE_DO_NOT_USE_AS_EVIDENCE:
            raise ArtifactJsonError("version-controlled evidence template is not blank")
        if args.evidence_record:
            evidence = _validate_json_model(
                VisoEvidenceRecordV1, _load_object(args.evidence_record)
            )
            if evidence.record_status is not EvidenceStatus.RECORDED:
                raise ArtifactJsonError("supplied evidence record is still a blank template")
            _validate_evidence_manifest_link(manifest, evidence)
        external_files = None
        if args.media_dir:
            external_files = _verify_external_pack(manifest, args.media_dir.expanduser().resolve())
    except (ArtifactJsonError, ValidationError, OSError, ValueError):
        raise SystemExit("replay artifact verification failed; no untrusted values were printed")

    positives = sum(
        fixture.expected_result is ExpectedResult.POSITIVE for fixture in manifest.fixtures
    )
    negatives = len(manifest.fixtures) - positives
    print(
        f"manifest: {manifest.status.value}; fixtures: {len(manifest.fixtures)} "
        f"({positives} positive, {negatives} hard negative)"
    )
    print("evidence template: valid and explicitly not run evidence")
    if args.evidence_record:
        print("supervised evidence record: valid, manifest-linked, and marked RECORDED")
    if external_files is not None:
        print(f"external fixture files verified by byte count and SHA-256: {external_files}")
    else:
        print("external fixture bytes: not checked (supply --media-dir for local verification)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
