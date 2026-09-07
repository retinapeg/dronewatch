"""Strict, secret-free artifacts for the bounded DroneWatch V0.2 replay."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated, Literal, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
    model_validator,
)


FIXTURE_MANIFEST_SCHEMA_VERSION = "dronewatch.fixture-manifest.v1"
REPLAY_RUN_SCHEMA_VERSION = "dronewatch.replay-run.v1"
VISO_EVIDENCE_SCHEMA_VERSION = "dronewatch.viso-evidence.v1"
MAX_REPLAY_COPIES = 20
MIN_REPLAY_INTERVAL_SECONDS = 20.0
MAX_REPLAY_INTERVAL_SECONDS = 30.0
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024

ARTIFACT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)

def _reject_dot_artifact_id(value: str) -> str:
    if value in {".", ".."}:
        raise ValueError("artifact identifier cannot be a dot path component")
    return value


ArtifactId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=ARTIFACT_ID_PATTERN,
        json_schema_extra={"not": {"enum": [".", ".."]}},
    ),
    AfterValidator(_reject_dot_artifact_id),
]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
GitSha = Annotated[str, Field(pattern=GIT_SHA_PATTERN)]
PositiveBytes = Annotated[int, Field(strict=True, gt=0)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _strict_utc_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if value.utcoffset().total_seconds() != 0:
            raise ValueError("artifact timestamps must be expressed in UTC")
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not UTC_TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError("timestamp must be an RFC 3339 UTC string ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("timestamp is not a valid calendar time") from error


def _relative_posix_file(value: str, *, suffix: str | None = None) -> str:
    if "\\" in value:
        raise ValueError("path must use portable POSIX separators")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts:
        raise ValueError("path must be relative")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("path must not contain empty, dot, or parent components")
    if suffix is not None and candidate.suffix.lower() != suffix:
        raise ValueError(f"path must end in {suffix}")
    return candidate.as_posix()


def _basename(value: str, *, suffix: str | None = None) -> str:
    normalized = _relative_posix_file(value, suffix=suffix)
    if "/" in normalized:
        raise ValueError("value must be a basename, not a path")
    return normalized


def sha256_file(path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a regular file without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class StrictArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ManifestStatus(str, Enum):
    VERIFIED = "VERIFIED"


class FixtureModality(str, Enum):
    VISIBLE = "VISIBLE"
    THERMAL_INFRARED = "THERMAL_INFRARED"


class FixtureCategory(str, Enum):
    DRONE_POSITIVE = "DRONE_POSITIVE"
    BIRD_HARD_NEGATIVE = "BIRD_HARD_NEGATIVE"
    AIRPLANE_HARD_NEGATIVE = "AIRPLANE_HARD_NEGATIVE"
    HELICOPTER_HARD_NEGATIVE = "HELICOPTER_HARD_NEGATIVE"
    BACKGROUND_NEGATIVE = "BACKGROUND_NEGATIVE"


class ExpectedResult(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class NotUsedLicense(StrictArtifactModel):
    status: Literal["NOT_USED"]
    reason: Annotated[str, Field(min_length=8, max_length=256)]


class DataLicense(StrictArtifactModel):
    status: Literal["VERIFIED"]
    spdx_id: Literal["CC0-1.0"]
    name: Literal["CC0 1.0 Universal"]
    source_url: HttpUrl
    source_path: str
    source_sha256: Sha256
    source_bytes: PositiveBytes
    attribution_required: Literal[False]
    redistribution_permitted: Literal[True]

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return _relative_posix_file(value)


class DatasetLicenses(StrictArtifactModel):
    data: DataLicense
    code: NotUsedLicense
    paper: NotUsedLicense
    model: NotUsedLicense


class DatasetSource(StrictArtifactModel):
    title: Annotated[str, Field(min_length=8, max_length=160)]
    owner_publisher: Annotated[str, Field(min_length=3, max_length=160)]
    repository_url: HttpUrl
    pinned_revision: GitSha
    revision_url: HttpUrl
    access_date: str
    licences: DatasetLicenses
    permitted_use: Literal["LICENCE_CLEAN_VISUAL_REPLAY_EVALUATION"]
    media_repository_policy: Literal["MEDIA_EXTERNAL_TO_GIT"]

    @field_validator("access_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("access_date must be a valid ISO date") from error
        return value

    @model_validator(mode="after")
    def pin_source_links(self) -> "DatasetSource":
        if self.pinned_revision not in str(self.revision_url):
            raise ValueError("revision_url must identify pinned_revision")
        if self.pinned_revision not in str(self.licences.data.source_url):
            raise ValueError("data licence URL must be pinned to the dataset revision")
        return self


class AnnotationArtifact(StrictArtifactModel):
    format: Literal["MATLAB_MAT"]
    source_path: str
    source_url: HttpUrl
    source_sha256: Sha256
    source_bytes: PositiveBytes
    use: Literal["UPSTREAM_REFERENCE_ONLY_NOT_PARSED_BY_DRONEWATCH_V0_2"]

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return _relative_posix_file(value, suffix=".mat")


class FixtureEntry(StrictArtifactModel):
    fixture_id: ArtifactId
    source_sequence_id: ArtifactId
    source_path: str
    source_url: HttpUrl
    source_sha256: Sha256
    source_bytes: PositiveBytes
    derived_filename: str
    derived_sha256: Sha256
    derived_bytes: PositiveBytes
    modality: FixtureModality
    category: FixtureCategory
    expected_result: ExpectedResult
    intended_use: Literal["VISUAL_FILE_REPLAY_EVALUATION"]
    transformations: tuple[Literal["NONE_SOURCE_BYTES"], ...]
    annotation: AnnotationArtifact
    acquisition_notes: Annotated[str, Field(min_length=8, max_length=500)]
    known_limitations: tuple[Annotated[str, Field(min_length=8, max_length=500)], ...]

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return _relative_posix_file(value, suffix=".mp4")

    @field_validator("derived_filename")
    @classmethod
    def validate_derived_filename(cls, value: str) -> str:
        return _basename(value, suffix=".mp4")

    @model_validator(mode="after")
    def validate_no_transform_selection(self) -> "FixtureEntry":
        if self.transformations != ("NONE_SOURCE_BYTES",):
            raise ValueError("V0.2 fixtures must retain the exact selected source bytes")
        if self.source_sha256 != self.derived_sha256:
            raise ValueError("an untransformed fixture must retain the source SHA-256")
        if self.source_bytes != self.derived_bytes:
            raise ValueError("an untransformed fixture must retain the source byte count")
        if PurePosixPath(self.source_path).name != self.derived_filename:
            raise ValueError("an untransformed fixture must retain the source basename")
        if self.expected_result is ExpectedResult.POSITIVE:
            if self.category is not FixtureCategory.DRONE_POSITIVE:
                raise ValueError("only drone-positive fixtures may expect POSITIVE")
        elif self.category is FixtureCategory.DRONE_POSITIVE:
            raise ValueError("drone-positive fixtures must expect POSITIVE")
        if not self.known_limitations:
            raise ValueError("known_limitations must not be empty")
        return self


class FixtureManifestV1(StrictArtifactModel):
    schema_version: Literal[FIXTURE_MANIFEST_SCHEMA_VERSION]
    manifest_id: ArtifactId
    status: ManifestStatus
    selected_at: datetime
    selection_method: Literal["PRESELECTED_BEFORE_ANY_VISO_RESULT"]
    selection_rationale: Annotated[str, Field(min_length=40, max_length=1000)]
    dataset: DatasetSource
    fixtures: tuple[FixtureEntry, ...]
    pack_limitations: tuple[Annotated[str, Field(min_length=8, max_length=500)], ...]

    @field_validator("selected_at", mode="before")
    @classmethod
    def validate_selected_at(cls, value: object) -> datetime:
        return _strict_utc_timestamp(value)

    @model_validator(mode="after")
    def validate_reviewable_selection(self) -> "FixtureManifestV1":
        if not 4 <= len(self.fixtures) <= 8:
            raise ValueError("fixture pack must contain between four and eight clips")
        fixture_ids = [fixture.fixture_id for fixture in self.fixtures]
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("fixture_id values must be unique")
        source_paths = [fixture.source_path for fixture in self.fixtures]
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("source_path values must be unique")
        positives = [
            fixture
            for fixture in self.fixtures
            if fixture.expected_result is ExpectedResult.POSITIVE
        ]
        negatives = [
            fixture
            for fixture in self.fixtures
            if fixture.expected_result is ExpectedResult.NEGATIVE
        ]
        if not 1 <= len(positives) <= 2:
            raise ValueError("fixture pack must contain one or two drone-positive clips")
        if len(negatives) < 3:
            raise ValueError("fixture pack must contain at least three hard negatives")
        negative_categories = {fixture.category for fixture in negatives}
        if len(negative_categories) < 3:
            raise ValueError("hard negatives must cover at least three distinct categories")
        if {fixture.modality for fixture in self.fixtures} != {
            FixtureModality.VISIBLE,
            FixtureModality.THERMAL_INFRARED,
        }:
            raise ValueError("fixture pack must include visible and thermal-infrared clips")
        revision = self.dataset.pinned_revision
        for fixture in self.fixtures:
            if revision not in str(fixture.source_url):
                raise ValueError("every fixture source_url must use the pinned revision")
            if revision not in str(fixture.annotation.source_url):
                raise ValueError("every annotation source_url must use the pinned revision")
        if not self.pack_limitations:
            raise ValueError("pack_limitations must not be empty")
        return self

    def fixture(self, fixture_id: str) -> FixtureEntry:
        matches = [fixture for fixture in self.fixtures if fixture.fixture_id == fixture_id]
        if len(matches) != 1:
            raise KeyError(fixture_id)
        return matches[0]


class ReplayState(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ReplayFailureCode(str, Enum):
    INVALID_RUN_CONFIGURATION = "INVALID_RUN_CONFIGURATION"
    INVALID_DESTINATION_BASENAME = "INVALID_DESTINATION_BASENAME"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_NOT_REGULAR = "SOURCE_NOT_REGULAR"
    SOURCE_EMPTY = "SOURCE_EMPTY"
    WATCH_DIR_NOT_FOUND = "WATCH_DIR_NOT_FOUND"
    WATCH_DIR_NOT_DIRECTORY = "WATCH_DIR_NOT_DIRECTORY"
    SOURCE_INSIDE_WATCH_DIR = "SOURCE_INSIDE_WATCH_DIR"
    RECORD_DIR_INSIDE_WATCH_DIR = "RECORD_DIR_INSIDE_WATCH_DIR"
    RECORD_ALREADY_EXISTS = "RECORD_ALREADY_EXISTS"
    RECORD_WRITE_FAILED = "RECORD_WRITE_FAILED"
    MANIFEST_NOT_FOUND = "MANIFEST_NOT_FOUND"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    MANIFEST_NOT_VERIFIED = "MANIFEST_NOT_VERIFIED"
    FIXTURE_NOT_FOUND = "FIXTURE_NOT_FOUND"
    FIXTURE_BASENAME_MISMATCH = "FIXTURE_BASENAME_MISMATCH"
    SOURCE_SIZE_MISMATCH = "SOURCE_SIZE_MISMATCH"
    SOURCE_HASH_MISMATCH = "SOURCE_HASH_MISMATCH"
    SOURCE_CHANGED_DURING_COPY = "SOURCE_CHANGED_DURING_COPY"
    COMPLETED_COPY_HASH_MISMATCH = "COMPLETED_COPY_HASH_MISMATCH"
    DESTINATION_EXISTS = "DESTINATION_EXISTS"
    COPY_IO_FAILED = "COPY_IO_FAILED"
    INTERRUPTED = "INTERRUPTED"


class ReplayCopyV1(StrictArtifactModel):
    sequence_number: Annotated[int, Field(strict=True, ge=1, le=MAX_REPLAY_COPIES)]
    source_sha256: Sha256
    destination_basename: str
    started_at: datetime
    completed_at: datetime | None
    completed_copy_sha256: Sha256 | None
    state: ReplayState
    failure_code: ReplayFailureCode | None

    @field_validator("destination_basename")
    @classmethod
    def validate_destination_basename(cls, value: str) -> str:
        return _basename(value, suffix=".mp4")

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def validate_timestamps(cls, value: object) -> datetime | None:
        return None if value is None else _strict_utc_timestamp(value)

    @model_validator(mode="after")
    def validate_state(self) -> "ReplayCopyV1":
        if self.state is ReplayState.RUNNING:
            raise ValueError("individual copy records cannot remain RUNNING")
        if self.state is ReplayState.SUCCEEDED:
            if self.completed_at is None or self.completed_copy_sha256 is None:
                raise ValueError("successful copies require completion time and hash")
            if self.failure_code is not None:
                raise ValueError("successful copies cannot have a failure code")
        else:
            if self.completed_copy_sha256 is not None:
                raise ValueError("failed or interrupted copies cannot have a completed hash")
            if self.failure_code is None:
                raise ValueError("failed or interrupted copies require a failure code")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        return self


class ReplayRunRecordV1(StrictArtifactModel):
    schema_version: Literal[REPLAY_RUN_SCHEMA_VERSION]
    scenario_id: ArtifactId
    run_id: ArtifactId
    fixture_id: ArtifactId
    manifest_id: ArtifactId
    delivery_mode: Literal["NEAR_REAL_TIME_FILE_REPLAY"]
    provenance: Literal["REPLAYED_REAL"]
    source_sha256: Sha256
    requested_count: Annotated[
        int, Field(strict=True, ge=1, le=MAX_REPLAY_COPIES)
    ]
    interval_seconds: Annotated[
        float,
        Field(
            strict=True,
            ge=MIN_REPLAY_INTERVAL_SECONDS,
            le=MAX_REPLAY_INTERVAL_SECONDS,
        ),
    ]
    started_at: datetime
    completed_at: datetime | None
    state: ReplayState
    failure_code: ReplayFailureCode | None
    completed_count: Annotated[
        int, Field(strict=True, ge=0, le=MAX_REPLAY_COPIES)
    ]
    copies: tuple[ReplayCopyV1, ...]
    proof_boundary: Literal[
        "LOCAL_ATOMIC_COPY_ONLY_NOT_DRIVE_SYNC_VISO_PROCESSING_OR_WEBHOOK_DELIVERY"
    ]

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def validate_timestamps(cls, value: object) -> datetime | None:
        return None if value is None else _strict_utc_timestamp(value)

    @model_validator(mode="after")
    def validate_progress(self) -> "ReplayRunRecordV1":
        expected_sequences = list(range(1, len(self.copies) + 1))
        actual_sequences = [copy.sequence_number for copy in self.copies]
        if actual_sequences != expected_sequences:
            raise ValueError("copy sequence numbers must be contiguous and ordered")
        if len(self.copies) > self.requested_count:
            raise ValueError("copies cannot exceed requested_count")
        if len({copy.destination_basename for copy in self.copies}) != len(self.copies):
            raise ValueError("completed destination basenames must be unique within a run")
        if any(copy.source_sha256 != self.source_sha256 for copy in self.copies):
            raise ValueError("every copy must identify the run's immutable source hash")
        if any(
            copy.state is ReplayState.SUCCEEDED
            and copy.completed_copy_sha256 != self.source_sha256
            for copy in self.copies
        ):
            raise ValueError("every successful copy must match the immutable source hash")
        succeeded = sum(copy.state is ReplayState.SUCCEEDED for copy in self.copies)
        if self.completed_count != succeeded:
            raise ValueError("completed_count must equal successful copy records")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.state is ReplayState.RUNNING:
            if self.completed_at is not None or self.failure_code is not None:
                raise ValueError("a running record cannot be finalized")
        elif self.state is ReplayState.SUCCEEDED:
            if self.completed_at is None or self.failure_code is not None:
                raise ValueError("a successful run must be finalized without failure")
            if self.completed_count != self.requested_count:
                raise ValueError("a successful run must complete the requested count")
            if any(copy.state is not ReplayState.SUCCEEDED for copy in self.copies):
                raise ValueError("a successful run cannot contain a failed copy")
        else:
            if self.completed_at is None or self.failure_code is None:
                raise ValueError("failed and interrupted runs must be finalized with a code")
        return self


class EvidenceStatus(str, Enum):
    TEMPLATE_DO_NOT_USE_AS_EVIDENCE = "TEMPLATE_DO_NOT_USE_AS_EVIDENCE"
    RECORDED = "RECORDED"


class EvidenceResult(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    MISS = "MISS"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    UNKNOWN = "UNKNOWN"


class LatencyBasis(str, Enum):
    RECEIPT_MINUS_PROVIDER_OBSERVED = "RECEIPT_MINUS_PROVIDER_OBSERVED"
    RECEIPT_MINUS_LOCAL_COPY_COMPLETED = "RECEIPT_MINUS_LOCAL_COPY_COMPLETED"


class VisoEvidenceRecordV1(StrictArtifactModel):
    schema_version: Literal[VISO_EVIDENCE_SCHEMA_VERSION]
    record_status: EvidenceStatus
    template_notice: Literal[
        "BLANK_TEMPLATE_NOT_RUN_EVIDENCE_DO_NOT_CITE_AS_EXTERNAL_VALIDATION"
    ] | None
    exact_tested_git_commit: GitSha | None
    viso_agent_configuration_date: str | None
    viso_agent_id: ArtifactId | None
    viso_configuration_id: ArtifactId | None
    scenario_id: ArtifactId | None
    run_id: ArtifactId | None
    fixture_id: ArtifactId | None
    fixture_sha256: Sha256 | None
    local_copy_completed_at: datetime | None
    provider_observed_at: datetime | None
    dronewatch_received_at: datetime | None
    response_status: Annotated[int, Field(strict=True, ge=100, le=599)] | None
    redacted_request_sha256: Sha256 | None
    latency_basis: LatencyBasis | None
    latency_ms: Annotated[float, Field(strict=True, ge=-604800000, le=604800000)] | None
    authentication_route: ArtifactId | None
    actual_result: EvidenceResult | None
    actual_result_notes: Annotated[str, Field(min_length=3, max_length=1000)] | None
    delivery_mode: Literal["NEAR_REAL_TIME_FILE_REPLAY"] | None
    provenance: Literal["REPLAYED_REAL"] | None
    limitations: tuple[Annotated[str, Field(min_length=8, max_length=500)], ...]
    secrets_or_sensitive_data_included: Literal[False]

    @field_validator(
        "local_copy_completed_at",
        "provider_observed_at",
        "dronewatch_received_at",
        mode="before",
    )
    @classmethod
    def validate_timestamps(cls, value: object) -> datetime | None:
        return None if value is None else _strict_utc_timestamp(value)

    @field_validator("viso_agent_configuration_date")
    @classmethod
    def validate_configuration_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("configuration date must be a valid ISO date") from error
        return value

    @model_validator(mode="after")
    def validate_evidence_gate(self) -> "VisoEvidenceRecordV1":
        evidence_fields = (
            self.exact_tested_git_commit,
            self.viso_agent_configuration_date,
            self.viso_agent_id,
            self.viso_configuration_id,
            self.scenario_id,
            self.run_id,
            self.fixture_id,
            self.fixture_sha256,
            self.local_copy_completed_at,
            self.provider_observed_at,
            self.dronewatch_received_at,
            self.response_status,
            self.redacted_request_sha256,
            self.latency_basis,
            self.latency_ms,
            self.authentication_route,
            self.actual_result,
            self.actual_result_notes,
            self.delivery_mode,
            self.provenance,
        )
        if self.record_status is EvidenceStatus.TEMPLATE_DO_NOT_USE_AS_EVIDENCE:
            if self.template_notice is None:
                raise ValueError("the blank template requires its non-evidence notice")
            if any(value is not None for value in evidence_fields):
                raise ValueError("the blank template cannot contain run evidence")
            return self

        if self.template_notice is not None:
            raise ValueError("a recorded evidence record cannot retain the template notice")
        required_fields = {
            "exact_tested_git_commit": self.exact_tested_git_commit,
            "viso_agent_configuration_date": self.viso_agent_configuration_date,
            "viso_agent_id": self.viso_agent_id,
            "viso_configuration_id": self.viso_configuration_id,
            "scenario_id": self.scenario_id,
            "run_id": self.run_id,
            "fixture_id": self.fixture_id,
            "fixture_sha256": self.fixture_sha256,
            "local_copy_completed_at": self.local_copy_completed_at,
            "dronewatch_received_at": self.dronewatch_received_at,
            "response_status": self.response_status,
            "redacted_request_sha256": self.redacted_request_sha256,
            "latency_basis": self.latency_basis,
            "latency_ms": self.latency_ms,
            "authentication_route": self.authentication_route,
            "actual_result": self.actual_result,
            "actual_result_notes": self.actual_result_notes,
            "delivery_mode": self.delivery_mode,
            "provenance": self.provenance,
        }
        missing = [name for name, value in required_fields.items() if value is None]
        if missing:
            raise ValueError("recorded evidence is missing: " + ", ".join(missing))
        if not self.limitations:
            raise ValueError("recorded evidence requires explicit limitations")
        if self.latency_basis is LatencyBasis.RECEIPT_MINUS_PROVIDER_OBSERVED:
            if self.provider_observed_at is None:
                raise ValueError("provider-based latency requires provider_observed_at")
            basis_time = self.provider_observed_at
        else:
            basis_time = self.local_copy_completed_at
        assert basis_time is not None
        assert self.dronewatch_received_at is not None
        expected_ms = (
            self.dronewatch_received_at - basis_time
        ).total_seconds() * 1000.0
        assert self.latency_ms is not None
        if abs(self.latency_ms - expected_ms) > 0.001:
            raise ValueError("latency_ms does not match the declared latency basis")
        return self


class ArtifactJsonError(ValueError):
    """A structural JSON error that never includes raw artifact content."""


def strict_json_object(body: bytes) -> dict:
    """Decode one duplicate-free finite JSON object without coercion."""

    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ArtifactJsonError("artifact must be valid UTF-8 JSON") from error

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ArtifactJsonError("artifact JSON contains a duplicate object key")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ArtifactJsonError("artifact JSON contains a non-finite number")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ArtifactJsonError("artifact JSON contains a non-finite number")
        return parsed

    def bounded_int(value: str) -> int:
        if len(value.removeprefix("-")) > 128:
            raise ArtifactJsonError("artifact JSON contains an oversized integer")
        return int(value)

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
            parse_float=finite_float,
            parse_int=bounded_int,
        )
    except ArtifactJsonError:
        raise
    except json.JSONDecodeError as error:
        raise ArtifactJsonError("artifact must be valid JSON") from error
    if not isinstance(decoded, dict):
        raise ArtifactJsonError("artifact JSON must be a top-level object")
    return decoded


ArtifactModel = TypeVar("ArtifactModel", bound=BaseModel)


def validate_artifact_json(model_type: type[ArtifactModel], body: bytes) -> ArtifactModel:
    """Apply strict JSON decoding, then the selected Pydantic artifact model."""

    decoded = strict_json_object(body)
    normalized = json.dumps(
        decoded, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    try:
        return model_type.model_validate_json(normalized)
    except ValidationError as error:
        raise ArtifactJsonError("artifact does not match the required schema") from error


def read_artifact_bytes(path) -> bytes:
    """Read a bounded local artifact without exposing its path in failures."""

    try:
        with path.open("rb") as artifact:
            body = artifact.read(MAX_ARTIFACT_BYTES + 1)
    except OSError as error:
        raise ArtifactJsonError("artifact file is unavailable") from error
    if len(body) > MAX_ARTIFACT_BYTES:
        raise ArtifactJsonError("artifact exceeds the maximum byte size")
    return body


def load_fixture_manifest(path) -> FixtureManifestV1:
    return validate_artifact_json(FixtureManifestV1, read_artifact_bytes(path))


def load_replay_run_record(path) -> ReplayRunRecordV1:
    return validate_artifact_json(ReplayRunRecordV1, read_artifact_bytes(path))


def load_viso_evidence_record(path) -> VisoEvidenceRecordV1:
    return validate_artifact_json(VisoEvidenceRecordV1, read_artifact_bytes(path))


def dump_artifact(model: BaseModel) -> bytes:
    """Serialize a validated artifact deterministically with a trailing newline."""

    payload = model.model_dump(mode="json", exclude_none=False)
    return (
        json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
