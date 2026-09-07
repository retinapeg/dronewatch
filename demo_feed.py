"""Serve one local video or run a finite, manifest-verified file replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import stat
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from pydantic import ValidationError

from replay_artifacts import (
    ARTIFACT_ID_PATTERN,
    FIXTURE_MANIFEST_SCHEMA_VERSION,
    MAX_ARTIFACT_BYTES,
    MAX_REPLAY_COPIES,
    MAX_REPLAY_INTERVAL_SECONDS,
    MIN_REPLAY_INTERVAL_SECONDS,
    REPLAY_RUN_SCHEMA_VERSION,
    ArtifactJsonError,
    FixtureManifestV1,
    ManifestStatus,
    ReplayCopyV1,
    ReplayFailureCode,
    ReplayRunRecordV1,
    ReplayState,
    dump_artifact,
    load_replay_run_record,
    sha256_file,
    strict_json_object,
    utc_now,
    utc_text,
    validate_artifact_json,
)


COPY_CHUNK_BYTES = 1024 * 1024
VIDEO_ROUTE = "/mq9-reaper.mp4"
DEFAULT_RECORD_DIR = Path(__file__).resolve().parent / "run-records"
ALLOWED_VIDEO_ORIGINS = frozenset(
    {"http://127.0.0.1:8000", "http://localhost:8000"}
)


class ReplayFailure(Exception):
    """A redacted, stable replay failure suitable for a retained run record."""

    def __init__(self, code: ReplayFailureCode):
        super().__init__(code.value)
        self.code = code


class TerminationRequested(BaseException):
    """Internal signal marker used to finalize an interrupted run record."""


@dataclass(frozen=True)
class CopyResult:
    destination: Path
    sha256: str


@dataclass(frozen=True)
class ReplayInputs:
    scenario_id: str
    run_id: str
    fixture_id: str
    manifest_path: Path
    source: Path
    watched_folder: Path
    count: int
    interval: float
    record_dir: Path


@dataclass(frozen=True)
class PreparedReplay:
    inputs: ReplayInputs
    manifest: FixtureManifestV1
    source: Path
    watched_folder: Path
    record_dir: Path
    record_path: Path
    source_sha256: str


@dataclass
class ReplayExecutionState:
    prepared: PreparedReplay | None = None
    record: ReplayRunRecordV1 | None = None
    active_sequence: int | None = None
    active_basename: str | None = None
    copy_started: datetime | None = None
    completed_result: CopyResult | None = None


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unique_destination_basename(run_id: str, fixture_id: str, sequence: int) -> str:
    token = uuid.uuid4().hex[:12]
    return f"dronewatch-{run_id}-{fixture_id}-{sequence:03d}-{token}.mp4"


def atomic_copy(
    source: Path,
    watched_folder: Path,
    destination_basename: str,
    expected_source_sha256: str,
) -> CopyResult:
    """Copy read-only source bytes through `.part`, then atomically publish once."""

    if (
        not destination_basename
        or destination_basename in {".", ".."}
        or "/" in destination_basename
        or "\\" in destination_basename
        or not destination_basename.lower().endswith(".mp4")
    ):
        raise ReplayFailure(ReplayFailureCode.INVALID_DESTINATION_BASENAME)
    destination = watched_folder / destination_basename
    if os.path.lexists(destination):
        raise ReplayFailure(ReplayFailureCode.DESTINATION_EXISTS)

    descriptor = -1
    temporary = None
    copied_digest = hashlib.sha256()
    try:
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".dronewatch-", suffix=".part", dir=watched_folder
            )
            temporary = Path(temporary_name)
        except OSError as error:
            raise ReplayFailure(ReplayFailureCode.COPY_IO_FAILED) from error
        try:
            with source.open("rb") as input_file, os.fdopen(
                descriptor, "wb", closefd=True
            ) as output_file:
                descriptor = -1
                while True:
                    chunk = input_file.read(COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    output_file.write(chunk)
                    copied_digest.update(chunk)
                output_file.flush()
                os.fsync(output_file.fileno())
        except (KeyboardInterrupt, TerminationRequested):
            raise
        except OSError as error:
            raise ReplayFailure(ReplayFailureCode.COPY_IO_FAILED) from error

        digest_during_copy = copied_digest.hexdigest()
        try:
            digest_after_copy = sha256_file(source)
        except OSError as error:
            raise ReplayFailure(ReplayFailureCode.COPY_IO_FAILED) from error
        if (
            digest_during_copy != expected_source_sha256
            or digest_after_copy != expected_source_sha256
        ):
            raise ReplayFailure(ReplayFailureCode.SOURCE_CHANGED_DURING_COPY)
        try:
            # Same-directory hard-link publication is atomic and, unlike POSIX
            # rename/replace, fails rather than clobbering a racing destination.
            assert temporary is not None
            os.link(temporary, destination)
            temporary.unlink()
            _fsync_directory(watched_folder)
        except FileExistsError as error:
            raise ReplayFailure(ReplayFailureCode.DESTINATION_EXISTS) from error
        except ReplayFailure:
            raise
        except OSError as error:
            raise ReplayFailure(ReplayFailureCode.COPY_IO_FAILED) from error
        try:
            completed_digest = sha256_file(destination)
        except OSError as error:
            raise ReplayFailure(ReplayFailureCode.COPY_IO_FAILED) from error
        if completed_digest != expected_source_sha256:
            # The published file is intentionally retained for operator audit.
            raise ReplayFailure(ReplayFailureCode.COMPLETED_COPY_HASH_MISMATCH)
        return CopyResult(destination=destination, sha256=completed_digest)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _verified_published_result(
    watched_folder: Path,
    destination_basename: str,
    expected_sha256: str,
) -> CopyResult | None:
    destination = watched_folder / destination_basename
    try:
        metadata = destination.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return None
        completed_digest = sha256_file(destination)
    except OSError:
        return None
    if completed_digest != expected_sha256:
        return None
    return CopyResult(destination=destination, sha256=completed_digest)


def copy_once(source: Path, watched_folder: Path) -> Path:
    """Compatibility helper: make one bounded, verified atomic local copy."""

    expected = sha256_file(source)
    stamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    basename = f"mq9-demo-{stamp}-{uuid.uuid4().hex[:10]}.mp4"
    return atomic_copy(source, watched_folder, basename, expected).destination


def make_handler(source: Path):
    """Return an HTTP handler that exposes exactly one MP4 route."""

    class VideoHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Repeated video range requests should not obscure operator output.
            pass

        def authorize_local_request(self) -> str | None | bool:
            expected_hosts = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1 or hosts[0] not in expected_hosts:
                self.send_error(403, "Local demo feed only")
                return False
            origins = self.headers.get_all("Origin", [])
            if len(origins) > 1 or (origins and origins[0] not in ALLOWED_VIDEO_ORIGINS):
                self.send_error(403, "Dashboard origin not allowed")
                return False
            return origins[0] if origins else None

        def send_cors_origin(self, origin: str | None) -> None:
            if origin is not None:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def do_OPTIONS(self):
            origin = self.authorize_local_request()
            if origin is False:
                return
            self.send_response(204)
            self.send_cors_origin(origin)
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Range")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_HEAD(self):
            self.serve_video(head_only=True)

        def do_GET(self):
            self.serve_video()

        def serve_video(self, head_only=False):
            origin = self.authorize_local_request()
            if origin is False:
                return
            if urlsplit(self.path).path != VIDEO_ROUTE:
                self.send_error(404)
                return
            try:
                video = source.open("rb")
            except OSError:
                self.send_error(503, "Demo source video unavailable")
                return
            with video:
                size = os.fstat(video.fileno()).st_size
                if size <= 0:
                    self.send_error(503, "Demo source video unavailable")
                    return
                start, end, status = 0, size - 1, 200
                requested = self.headers.get("Range")
                if requested:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
                    valid = bool(match and (match[1] or match[2]))
                    if valid and any(
                        len(component) > 20 for component in match.groups() if component
                    ):
                        valid = False
                    if valid:
                        if match[1]:
                            start = int(match[1])
                            end = min(int(match[2]), size - 1) if match[2] else size - 1
                        else:
                            suffix_length = int(match[2])
                            valid = suffix_length > 0
                            start = max(0, size - suffix_length)
                        valid = valid and 0 <= start <= end < size
                    if not valid:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_cors_origin(origin)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    status = 206
                self.send_response(status)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                self.send_cors_origin(origin)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if head_only:
                    return
                video.seek(start)
                remaining = end - start + 1
                try:
                    while remaining:
                        chunk = video.read(min(128 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    return VideoHandler


def _artifact_id(value: str) -> str:
    if value in {".", ".."} or not re.fullmatch(ARTIFACT_ID_PATTERN, value):
        raise argparse.ArgumentTypeError(
            "must use 1-64 letters, digits, dot, underscore, or hyphen and start alphanumeric"
        )
    return value


def _bounded_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if not 1 <= count <= MAX_REPLAY_COPIES:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_REPLAY_COPIES}")
    return count


def _bounded_interval(value: str) -> float:
    try:
        interval = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not MIN_REPLAY_INTERVAL_SECONDS <= interval <= MAX_REPLAY_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(
            f"must be between {MIN_REPLAY_INTERVAL_SECONDS:g} and "
            f"{MAX_REPLAY_INTERVAL_SECONDS:g} seconds"
        )
    return interval


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser(
        "serve", help="serve one local MP4 until interrupted; creates no files"
    )
    serve_parser.add_argument("--source", type=Path, required=True)
    serve_parser.add_argument(
        "--port", type=int, default=8001, choices=range(1, 65536)
    )

    replay_parser = subparsers.add_parser(
        "replay", help="make a finite manifest-verified series of atomic copies"
    )
    replay_parser.add_argument("--scenario-id", type=_artifact_id, required=True)
    replay_parser.add_argument("--run-id", type=_artifact_id, required=True)
    replay_parser.add_argument("--fixture-id", type=_artifact_id, required=True)
    replay_parser.add_argument("--manifest", type=Path, required=True)
    replay_parser.add_argument("--source", type=Path, required=True)
    replay_parser.add_argument("--watch-dir", type=Path, required=True)
    replay_parser.add_argument("--count", type=_bounded_count, required=True)
    replay_parser.add_argument(
        "--interval",
        type=_bounded_interval,
        default=25.0,
        help="seconds between copies, 20-30 inclusive (default: 25)",
    )
    replay_parser.add_argument(
        "--record-dir",
        type=Path,
        default=DEFAULT_RECORD_DIR,
        help="run-record directory outside the watched folder (default: repository run-records)",
    )
    return parser.parse_args(argv)


def _resolve_existing_file(
    path: Path,
    missing_code: ReplayFailureCode,
    nonregular_code: ReplayFailureCode,
) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as error:
        raise ReplayFailure(missing_code) from error
    if not resolved.is_file():
        raise ReplayFailure(nonregular_code)
    return resolved


def _resolve_watched_folder(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as error:
        raise ReplayFailure(ReplayFailureCode.WATCH_DIR_NOT_FOUND) from error
    if not resolved.is_dir():
        raise ReplayFailure(ReplayFailureCode.WATCH_DIR_NOT_DIRECTORY)
    return resolved


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _read_manifest(path: Path) -> FixtureManifestV1:
    try:
        with path.open("rb") as manifest_file:
            body = manifest_file.read(MAX_ARTIFACT_BYTES + 1)
    except OSError as error:
        raise ReplayFailure(ReplayFailureCode.MANIFEST_NOT_FOUND) from error
    if len(body) > MAX_ARTIFACT_BYTES:
        raise ReplayFailure(ReplayFailureCode.MANIFEST_INVALID)
    try:
        decoded = strict_json_object(body)
    except ArtifactJsonError as error:
        raise ReplayFailure(ReplayFailureCode.MANIFEST_INVALID) from error
    if decoded.get("status") != ManifestStatus.VERIFIED.value:
        raise ReplayFailure(ReplayFailureCode.MANIFEST_NOT_VERIFIED)
    if decoded.get("schema_version") != FIXTURE_MANIFEST_SCHEMA_VERSION:
        raise ReplayFailure(ReplayFailureCode.MANIFEST_INVALID)
    try:
        return validate_artifact_json(FixtureManifestV1, body)
    except (ArtifactJsonError, ValidationError) as error:
        raise ReplayFailure(ReplayFailureCode.MANIFEST_INVALID) from error


def prepare_replay(inputs: ReplayInputs) -> PreparedReplay:
    identifiers = (inputs.scenario_id, inputs.run_id, inputs.fixture_id)
    if any(
        not isinstance(value, str)
        or value in {".", ".."}
        or re.fullmatch(ARTIFACT_ID_PATTERN, value) is None
        for value in identifiers
    ):
        raise ReplayFailure(ReplayFailureCode.INVALID_RUN_CONFIGURATION)
    if (
        isinstance(inputs.count, bool)
        or not isinstance(inputs.count, int)
        or not 1 <= inputs.count <= MAX_REPLAY_COPIES
        or isinstance(inputs.interval, bool)
        or not isinstance(inputs.interval, (int, float))
        or not MIN_REPLAY_INTERVAL_SECONDS
        <= float(inputs.interval)
        <= MAX_REPLAY_INTERVAL_SECONDS
    ):
        raise ReplayFailure(ReplayFailureCode.INVALID_RUN_CONFIGURATION)
    source = _resolve_existing_file(
        inputs.source,
        ReplayFailureCode.SOURCE_NOT_FOUND,
        ReplayFailureCode.SOURCE_NOT_REGULAR,
    )
    watched_folder = _resolve_watched_folder(inputs.watched_folder)
    try:
        source_bytes = source.stat().st_size
    except OSError as error:
        raise ReplayFailure(ReplayFailureCode.SOURCE_NOT_FOUND) from error
    if source_bytes <= 0:
        raise ReplayFailure(ReplayFailureCode.SOURCE_EMPTY)
    if _is_within(source, watched_folder):
        raise ReplayFailure(ReplayFailureCode.SOURCE_INSIDE_WATCH_DIR)

    manifest_path = _resolve_existing_file(
        inputs.manifest_path,
        ReplayFailureCode.MANIFEST_NOT_FOUND,
        ReplayFailureCode.MANIFEST_INVALID,
    )
    manifest = _read_manifest(manifest_path)
    try:
        fixture = manifest.fixture(inputs.fixture_id)
    except KeyError as error:
        raise ReplayFailure(ReplayFailureCode.FIXTURE_NOT_FOUND) from error
    if source.name != fixture.derived_filename:
        raise ReplayFailure(ReplayFailureCode.FIXTURE_BASENAME_MISMATCH)
    if source_bytes != fixture.derived_bytes:
        raise ReplayFailure(ReplayFailureCode.SOURCE_SIZE_MISMATCH)
    try:
        source_digest = sha256_file(source)
    except OSError as error:
        raise ReplayFailure(ReplayFailureCode.COPY_IO_FAILED) from error
    if source_digest != fixture.derived_sha256:
        raise ReplayFailure(ReplayFailureCode.SOURCE_HASH_MISMATCH)

    try:
        record_dir = inputs.record_dir.expanduser().resolve(strict=False)
    except OSError as error:
        raise ReplayFailure(ReplayFailureCode.RECORD_WRITE_FAILED) from error
    if _is_within(record_dir, watched_folder):
        raise ReplayFailure(ReplayFailureCode.RECORD_DIR_INSIDE_WATCH_DIR)
    try:
        record_dir.mkdir(parents=True, exist_ok=True)
        record_dir = record_dir.resolve(strict=True)
    except OSError as error:
        raise ReplayFailure(ReplayFailureCode.RECORD_WRITE_FAILED) from error
    if not record_dir.is_dir() or _is_within(record_dir, watched_folder):
        raise ReplayFailure(ReplayFailureCode.RECORD_DIR_INSIDE_WATCH_DIR)
    record_path = record_dir / f"{inputs.run_id}.json"
    if os.path.lexists(record_path):
        raise ReplayFailure(ReplayFailureCode.RECORD_ALREADY_EXISTS)
    return PreparedReplay(
        inputs=inputs,
        manifest=manifest,
        source=source,
        watched_folder=watched_folder,
        record_dir=record_dir,
        record_path=record_path,
        source_sha256=source_digest,
    )


def _new_run_record(prepared: PreparedReplay, started_at: datetime) -> ReplayRunRecordV1:
    payload = {
        "schema_version": REPLAY_RUN_SCHEMA_VERSION,
        "scenario_id": prepared.inputs.scenario_id,
        "run_id": prepared.inputs.run_id,
        "fixture_id": prepared.inputs.fixture_id,
        "manifest_id": prepared.manifest.manifest_id,
        "delivery_mode": "NEAR_REAL_TIME_FILE_REPLAY",
        "provenance": "REPLAYED_REAL",
        "source_sha256": prepared.source_sha256,
        "requested_count": prepared.inputs.count,
        "interval_seconds": prepared.inputs.interval,
        "started_at": utc_text(started_at),
        "completed_at": None,
        "state": ReplayState.RUNNING.value,
        "failure_code": None,
        "completed_count": 0,
        "copies": [],
        "proof_boundary": (
            "LOCAL_ATOMIC_COPY_ONLY_NOT_DRIVE_SYNC_VISO_PROCESSING_OR_WEBHOOK_DELIVERY"
        ),
    }
    return ReplayRunRecordV1.model_validate_json(json.dumps(payload))


def _updated_record(record: ReplayRunRecordV1, **updates) -> ReplayRunRecordV1:
    payload = record.model_dump(mode="json", exclude_none=False)
    for key, value in updates.items():
        if isinstance(value, datetime):
            payload[key] = utc_text(value)
        elif isinstance(value, (ReplayState, ReplayFailureCode)):
            payload[key] = value.value
        elif key == "copies":
            payload[key] = [copy.model_dump(mode="json") for copy in value]
        else:
            payload[key] = value
    return ReplayRunRecordV1.model_validate_json(json.dumps(payload))


def _reserve_record(path: Path, record: ReplayRunRecordV1) -> None:
    descriptor = -1
    created = False
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            descriptor = -1
            output.write(dump_artifact(record))
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(path.parent)
    except FileExistsError as error:
        raise ReplayFailure(ReplayFailureCode.RECORD_ALREADY_EXISTS) from error
    except OSError as error:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ReplayFailure(ReplayFailureCode.RECORD_WRITE_FAILED) from error
    except BaseException:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_record(path: Path, record: ReplayRunRecordV1) -> None:
    descriptor = -1
    temporary = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}-", suffix=".json.part", dir=path.parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            descriptor = -1
            output.write(dump_artifact(record))
            output.flush()
            os.fsync(output.fileno())
        assert temporary is not None
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as error:
        raise ReplayFailure(ReplayFailureCode.RECORD_WRITE_FAILED) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _copy_record(
    *,
    sequence: int,
    source_sha256: str,
    destination_basename: str,
    started_at: datetime,
    completed_at: datetime,
    state: ReplayState,
    completed_sha256: str | None,
    failure_code: ReplayFailureCode | None,
) -> ReplayCopyV1:
    payload = {
        "sequence_number": sequence,
        "source_sha256": source_sha256,
        "destination_basename": destination_basename,
        "started_at": utc_text(started_at),
        "completed_at": utc_text(completed_at),
        "completed_copy_sha256": completed_sha256,
        "state": state.value,
        "failure_code": failure_code.value if failure_code else None,
    }
    return ReplayCopyV1.model_validate_json(json.dumps(payload))


def _run_replay_impl(
    inputs: ReplayInputs,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = utc_now,
    basename_fn: Callable[[str, str, int], str] = _unique_destination_basename,
    copy_fn: Callable[[Path, Path, str, str], CopyResult] = atomic_copy,
    execution_state: ReplayExecutionState,
) -> int:
    """Run one finite replay. Return 0 success, 1 failure, 130/143 interruption."""

    try:
        prepared = prepare_replay(inputs)
    except ReplayFailure as error:
        print(f"REPLAY_FAILED {error.code.value}", flush=True)
        return 1
    except Exception:
        print("REPLAY_FAILED INVALID_RUN_CONFIGURATION", flush=True)
        return 1

    execution_state.prepared = prepared
    record = _new_run_record(prepared, clock())
    execution_state.record = record
    try:
        _reserve_record(prepared.record_path, record)
    except ReplayFailure as error:
        print(f"REPLAY_FAILED {error.code.value}", flush=True)
        return 1

    print(
        f"REPLAY_STARTED run={inputs.run_id} fixture={inputs.fixture_id} "
        f"count={inputs.count}",
        flush=True,
    )
    for sequence in range(1, inputs.count + 1):
        try:
            basename = basename_fn(inputs.run_id, inputs.fixture_id, sequence)
        except Exception:
            basename = "invalid-destination.mp4"
            error = ReplayFailure(ReplayFailureCode.INVALID_DESTINATION_BASENAME)
        else:
            error = None
        if (
            not isinstance(basename, str)
            or not basename
            or basename in {".", ".."}
            or "/" in basename
            or "\\" in basename
            or not basename.lower().endswith(".mp4")
        ):
            basename = "invalid-destination.mp4"
            error = ReplayFailure(ReplayFailureCode.INVALID_DESTINATION_BASENAME)
        execution_state.active_sequence = sequence
        execution_state.active_basename = basename
        execution_state.completed_result = None
        copy_started = clock()
        execution_state.copy_started = copy_started
        try:
            if error is not None:
                raise error
            result = copy_fn(
                prepared.source,
                prepared.watched_folder,
                basename,
                prepared.source_sha256,
            )
            execution_state.completed_result = result
        except (KeyboardInterrupt, TerminationRequested) as error:
            interrupted_at = clock()
            published_result = _verified_published_result(
                prepared.watched_folder,
                basename,
                prepared.source_sha256,
            )
            copy_record = _copy_record(
                sequence=sequence,
                source_sha256=prepared.source_sha256,
                destination_basename=basename,
                started_at=copy_started,
                completed_at=interrupted_at,
                state=(
                    ReplayState.SUCCEEDED
                    if published_result is not None
                    else ReplayState.INTERRUPTED
                ),
                completed_sha256=(
                    published_result.sha256 if published_result is not None else None
                ),
                failure_code=(
                    None
                    if published_result is not None
                    else ReplayFailureCode.INTERRUPTED
                ),
            )
            record = _updated_record(
                record,
                copies=record.copies + (copy_record,),
                completed_count=(
                    record.completed_count + (1 if published_result is not None else 0)
                ),
                completed_at=interrupted_at,
                state=ReplayState.INTERRUPTED,
                failure_code=ReplayFailureCode.INTERRUPTED,
            )
            execution_state.record = record
            try:
                _write_record(prepared.record_path, record)
            except ReplayFailure:
                print("REPLAY_FAILED RECORD_WRITE_FAILED", flush=True)
                return 1
            code = 143 if isinstance(error, TerminationRequested) else 130
            print("REPLAY_INTERRUPTED", flush=True)
            return code
        except ReplayFailure as error:
            failed_at = clock()
            copy_record = _copy_record(
                sequence=sequence,
                source_sha256=prepared.source_sha256,
                destination_basename=basename,
                started_at=copy_started,
                completed_at=failed_at,
                state=ReplayState.FAILED,
                completed_sha256=None,
                failure_code=error.code,
            )
            record = _updated_record(
                record,
                copies=record.copies + (copy_record,),
                completed_at=failed_at,
                state=ReplayState.FAILED,
                failure_code=error.code,
            )
            execution_state.record = record
            try:
                _write_record(prepared.record_path, record)
            except ReplayFailure:
                print("REPLAY_FAILED RECORD_WRITE_FAILED", flush=True)
                return 1
            print(f"REPLAY_FAILED {error.code.value}", flush=True)
            return 1
        except Exception:
            failed_at = clock()
            code = ReplayFailureCode.COPY_IO_FAILED
            copy_record = _copy_record(
                sequence=sequence,
                source_sha256=prepared.source_sha256,
                destination_basename=basename,
                started_at=copy_started,
                completed_at=failed_at,
                state=ReplayState.FAILED,
                completed_sha256=None,
                failure_code=code,
            )
            record = _updated_record(
                record,
                copies=record.copies + (copy_record,),
                completed_at=failed_at,
                state=ReplayState.FAILED,
                failure_code=code,
            )
            execution_state.record = record
            try:
                _write_record(prepared.record_path, record)
            except ReplayFailure:
                print("REPLAY_FAILED RECORD_WRITE_FAILED", flush=True)
                return 1
            print(f"REPLAY_FAILED {code.value}", flush=True)
            return 1

        completed_at = clock()
        copy_record = _copy_record(
            sequence=sequence,
            source_sha256=prepared.source_sha256,
            destination_basename=result.destination.name,
            started_at=copy_started,
            completed_at=completed_at,
            state=ReplayState.SUCCEEDED,
            completed_sha256=result.sha256,
            failure_code=None,
        )
        record = _updated_record(
            record,
            copies=record.copies + (copy_record,),
            completed_count=record.completed_count + 1,
        )
        execution_state.record = record
        try:
            _write_record(prepared.record_path, record)
        except ReplayFailure:
            print("REPLAY_FAILED RECORD_WRITE_FAILED", flush=True)
            return 1
        execution_state.active_sequence = None
        execution_state.active_basename = None
        execution_state.copy_started = None
        execution_state.completed_result = None
        print(f"COPY_SUCCEEDED sequence={sequence} file={result.destination.name}", flush=True)
        if sequence < inputs.count:
            try:
                sleep_fn(inputs.interval)
            except (KeyboardInterrupt, TerminationRequested) as error:
                interrupted_at = clock()
                record = _updated_record(
                    record,
                    completed_at=interrupted_at,
                    state=ReplayState.INTERRUPTED,
                    failure_code=ReplayFailureCode.INTERRUPTED,
                )
                execution_state.record = record
                try:
                    _write_record(prepared.record_path, record)
                except ReplayFailure:
                    print("REPLAY_FAILED RECORD_WRITE_FAILED", flush=True)
                    return 1
                code = 143 if isinstance(error, TerminationRequested) else 130
                print("REPLAY_INTERRUPTED", flush=True)
                return code
            except Exception:
                failed_at = clock()
                failure_code = ReplayFailureCode.COPY_IO_FAILED
                record = _updated_record(
                    record,
                    completed_at=failed_at,
                    state=ReplayState.FAILED,
                    failure_code=failure_code,
                )
                execution_state.record = record
                try:
                    _write_record(prepared.record_path, record)
                except ReplayFailure:
                    print("REPLAY_FAILED RECORD_WRITE_FAILED", flush=True)
                    return 1
                print(f"REPLAY_FAILED {failure_code.value}", flush=True)
                return 1

    record = _updated_record(
        record,
        completed_at=clock(),
        state=ReplayState.SUCCEEDED,
        failure_code=None,
    )
    execution_state.record = record
    try:
        _write_record(prepared.record_path, record)
    except ReplayFailure:
        print("REPLAY_FAILED RECORD_WRITE_FAILED", flush=True)
        return 1
    print(
        f"REPLAY_SUCCEEDED run={inputs.run_id} completed={record.completed_count} "
        "proof=LOCAL_ATOMIC_COPY_ONLY",
        flush=True,
    )
    return 0


def _finalize_unhandled_interruption(
    execution_state: ReplayExecutionState,
    interruption: KeyboardInterrupt | TerminationRequested,
) -> int:
    exit_code = 143 if isinstance(interruption, TerminationRequested) else 130
    prepared = execution_state.prepared
    if prepared is None or not prepared.record_path.exists():
        print("REPLAY_INTERRUPTED", flush=True)
        return exit_code
    try:
        record = load_replay_run_record(prepared.record_path)
    except (ArtifactJsonError, OSError, ValidationError):
        print("REPLAY_FAILED RECORD_WRITE_FAILED", flush=True)
        return 1
    try:
        record = execution_state.record or record
        result = execution_state.completed_result
        sequence = execution_state.active_sequence
        started_at = execution_state.copy_started
        if result is None and execution_state.active_basename is not None:
            result = _verified_published_result(
                prepared.watched_folder,
                execution_state.active_basename,
                prepared.source_sha256,
            )
        if (
            result is not None
            and sequence is not None
            and started_at is not None
            and all(copy.sequence_number != sequence for copy in record.copies)
        ):
            reconciled_at = utc_now()
            copy_record = _copy_record(
                sequence=sequence,
                source_sha256=prepared.source_sha256,
                destination_basename=result.destination.name,
                started_at=started_at,
                completed_at=reconciled_at,
                state=ReplayState.SUCCEEDED,
                completed_sha256=result.sha256,
                failure_code=None,
            )
            record = _updated_record(
                record,
                copies=record.copies + (copy_record,),
                completed_count=record.completed_count + 1,
            )
        if record.state is ReplayState.RUNNING:
            record = _updated_record(
                record,
                completed_at=utc_now(),
                state=ReplayState.INTERRUPTED,
                failure_code=ReplayFailureCode.INTERRUPTED,
            )
        _write_record(prepared.record_path, record)
    except BaseException:
        print("REPLAY_FAILED RECORD_WRITE_FAILED", flush=True)
        return 1
    print("REPLAY_INTERRUPTED", flush=True)
    return exit_code


def run_replay(
    inputs: ReplayInputs,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = utc_now,
    basename_fn: Callable[[str, str, int], str] = _unique_destination_basename,
    copy_fn: Callable[[Path, Path, str, str], CopyResult] = atomic_copy,
) -> int:
    """Run one finite replay and finalize any post-preflight interruption."""

    execution_state = ReplayExecutionState()
    try:
        return _run_replay_impl(
            inputs,
            sleep_fn=sleep_fn,
            clock=clock,
            basename_fn=basename_fn,
            copy_fn=copy_fn,
            execution_state=execution_state,
        )
    except (KeyboardInterrupt, TerminationRequested) as interruption:
        return _finalize_unhandled_interruption(execution_state, interruption)


def serve(source: Path, port: int) -> int:
    try:
        source = source.expanduser().resolve(strict=True)
    except OSError:
        print("SERVE_FAILED SOURCE_NOT_FOUND", flush=True)
        return 1
    try:
        valid_source = source.is_file() and source.stat().st_size > 0
    except OSError:
        valid_source = False
    if not valid_source:
        print("SERVE_FAILED SOURCE_NOT_REGULAR_OR_EMPTY", flush=True)
        return 1
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(source))
    except OSError:
        print("SERVE_FAILED SERVER_START_FAILED", flush=True)
        return 1
    print(f"DEMO_SENSOR_FEED http://127.0.0.1:{server.server_port}{VIDEO_ROUTE}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    except TerminationRequested:
        return 143
    finally:
        server.server_close()
        print("DEMO_SENSOR_FEED_STOPPED", flush=True)
    return 0


def _handle_sigterm(*_args) -> None:
    raise TerminationRequested()


def main(argv=None) -> int:
    args = parse_args(argv)
    previous_sigterm = signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        if args.command == "serve":
            return serve(args.source, args.port)
        inputs = ReplayInputs(
            scenario_id=args.scenario_id,
            run_id=args.run_id,
            fixture_id=args.fixture_id,
            manifest_path=args.manifest,
            source=args.source,
            watched_folder=args.watch_dir,
            count=args.count,
            interval=args.interval,
            record_dir=args.record_dir,
        )
        return run_replay(inputs)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == "__main__":
    sys.exit(main())
