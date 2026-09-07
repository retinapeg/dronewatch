"""SQLite migration, idempotency, lifecycle, projection, and retention."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from contracts import (
    CanonicalObservationV1,
    Classification,
    DetectionResult,
    LifecycleState,
    content_digest,
    observed_at_microseconds,
    rfc3339,
)


MIGRATION_VERSION = "v0.2-canonical-observations"
SQLITE_USER_VERSION = 2
MAX_COMPATIBILITY_JSON_BYTES = 4_096
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LEGACY_COLUMNS = {
    "id",
    "event_id",
    "received_at",
    "detection_type",
    "drone_detected",
    "confidence",
    "state",
    "severity",
    "source",
    "media_url",
    "raw_payload",
    "is_simulated",
}
OBSERVATION_COLUMNS = {
    "id",
    "observation_id",
    "schema_version",
    "source_event_id",
    "source_system",
    "source_scope",
    "track_id",
    "scenario_id",
    "run_id",
    "observed_at",
    "observed_at_us",
    "received_at",
    "modality",
    "provenance",
    "delivery_mode",
    "simulation",
    "lifecycle_state",
    "detection_result",
    "classification",
    "confidence",
    "frame_coordinates_json",
    "content_digest",
    "request_digest",
}
ColumnSignature = tuple[str, bool, int, str | None]
TABLE_SIGNATURES: dict[str, dict[str, ColumnSignature]] = {
    "incidents": {
        "id": ("INTEGER", False, 1, None),
        "event_id": ("TEXT", True, 0, None),
        "received_at": ("TEXT", True, 0, None),
        "detection_type": ("TEXT", False, 0, None),
        "drone_detected": ("INTEGER", True, 0, "0"),
        "confidence": ("REAL", False, 0, None),
        "state": ("TEXT", True, 0, "'UNKNOWN'"),
        "severity": ("TEXT", True, 0, "'INFO'"),
        "source": ("TEXT", False, 0, None),
        "media_url": ("TEXT", False, 0, None),
        "raw_payload": ("TEXT", True, 0, None),
        "is_simulated": ("INTEGER", True, 0, "0"),
    },
    "schema_migrations": {
        "version": ("TEXT", False, 1, None),
        "applied_at": ("TEXT", True, 0, None),
    },
    "delivery_keys": {
        "id": ("INTEGER", False, 1, None),
        "source_system": ("TEXT", True, 0, None),
        "source_scope": ("TEXT", True, 0, None),
        "source_event_id": ("TEXT", True, 0, None),
        "observation_id": ("TEXT", True, 0, None),
        "content_digest": ("TEXT", True, 0, None),
        "first_received_at": ("TEXT", True, 0, None),
    },
    "observations_v1": {
        "id": ("INTEGER", False, 1, None),
        "observation_id": ("TEXT", True, 0, None),
        "schema_version": ("TEXT", True, 0, None),
        "source_event_id": ("TEXT", True, 0, None),
        "source_system": ("TEXT", True, 0, None),
        "source_scope": ("TEXT", True, 0, None),
        "track_id": ("TEXT", False, 0, None),
        "scenario_id": ("TEXT", False, 0, None),
        "run_id": ("TEXT", False, 0, None),
        "observed_at": ("TEXT", True, 0, None),
        "observed_at_us": ("INTEGER", True, 0, None),
        "received_at": ("TEXT", True, 0, None),
        "modality": ("TEXT", True, 0, None),
        "provenance": ("TEXT", True, 0, None),
        "delivery_mode": ("TEXT", True, 0, None),
        "simulation": ("INTEGER", True, 0, None),
        "lifecycle_state": ("TEXT", True, 0, None),
        "detection_result": ("TEXT", True, 0, None),
        "classification": ("TEXT", True, 0, None),
        "confidence": ("REAL", False, 0, None),
        "frame_coordinates_json": ("TEXT", False, 0, None),
        "content_digest": ("TEXT", True, 0, None),
        "request_digest": ("TEXT", True, 0, None),
    },
    "track_heads": {
        "source_system": ("TEXT", True, 1, None),
        "source_scope": ("TEXT", True, 2, None),
        "track_id": ("TEXT", True, 3, None),
        "observation_id": ("TEXT", True, 0, None),
        "observation_database_id": ("INTEGER", True, 0, None),
        "source_event_id": ("TEXT", True, 0, None),
        "observed_at": ("TEXT", True, 0, None),
        "observed_at_us": ("INTEGER", True, 0, None),
        "received_at": ("TEXT", True, 0, None),
        "scenario_id": ("TEXT", False, 0, None),
        "run_id": ("TEXT", False, 0, None),
        "modality": ("TEXT", True, 0, None),
        "provenance": ("TEXT", True, 0, None),
        "delivery_mode": ("TEXT", True, 0, None),
        "simulation": ("INTEGER", True, 0, None),
        "lifecycle_state": ("TEXT", True, 0, None),
        "state_rank": ("INTEGER", True, 0, None),
        "detection_result": ("TEXT", True, 0, None),
        "classification": ("TEXT", True, 0, None),
        "confidence": ("REAL", False, 0, None),
        "frame_coordinates_json": ("TEXT", False, 0, None),
        "content_digest": ("TEXT", True, 0, None),
    },
    "delivery_conflicts": {
        "id": ("INTEGER", False, 1, None),
        "source_system": ("TEXT", True, 0, None),
        "source_scope": ("TEXT", True, 0, None),
        "source_event_id": ("TEXT", True, 0, None),
        "existing_digest": ("TEXT", True, 0, None),
        "attempted_digest": ("TEXT", True, 0, None),
        "first_received_at": ("TEXT", True, 0, None),
        "last_received_at": ("TEXT", True, 0, None),
        "attempt_count": ("INTEGER", True, 0, "1"),
    },
}


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetentionPolicy:
    observation_days: int = 30
    observation_max_count: int = 10_000
    conflict_days: int = 7
    conflict_max_count: int = 1_000


@dataclass(frozen=True)
class StoreResult:
    status: Literal["accepted", "duplicate", "conflict"]
    observation_id: str
    database_id: int | None
    content_digest: str


def _connect(database_path: Path) -> sqlite3.Connection:
    descriptor = os.open(database_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("database path is not a regular file")
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(database_path) + suffix)
        try:
            sidecar_descriptor = os.open(sidecar, os.O_RDWR)
        except FileNotFoundError:
            continue
        try:
            if not stat.S_ISREG(os.fstat(sidecar_descriptor).st_mode):
                raise OSError("database sidecar is not a regular file")
            os.fchmod(sidecar_descriptor, 0o600)
        finally:
            os.close(sidecar_descriptor)
    connection = sqlite3.connect(database_path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _table_signature(
    connection: sqlite3.Connection, table: str
) -> dict[str, ColumnSignature]:
    return {
        row["name"]: (
            str(row["type"]).strip().upper(),
            bool(row["notnull"]),
            int(row["pk"]),
            row["dflt_value"],
        )
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def _has_unique_index(
    connection: sqlite3.Connection,
    table: str,
    expected_columns: tuple[str, ...],
) -> bool:
    for index in connection.execute(f"PRAGMA index_list({table})"):
        if not bool(index["unique"]) or bool(index["partial"]):
            continue
        quoted_name = '"' + str(index["name"]).replace('"', '""') + '"'
        key_rows = [
            row
            for row in connection.execute(f"PRAGMA index_xinfo({quoted_name})")
            if bool(row["key"])
        ]
        columns = tuple(row["name"] for row in key_rows)
        if (
            columns == expected_columns
            and all(row["name"] is not None for row in key_rows)
            and all(str(row["coll"]).upper() == "BINARY" for row in key_rows)
            and all(not bool(row["desc"]) for row in key_rows)
        ):
            return True
    return False


def _require_schema_postconditions(connection: sqlite3.Connection) -> None:
    for table, expected_signature in TABLE_SIGNATURES.items():
        if _table_signature(connection, table) != expected_signature:
            raise MigrationError(f"existing {table} table has an incompatible definition")

    unique_requirements = (
        ("delivery_keys", ("source_system", "source_scope", "source_event_id")),
        ("delivery_keys", ("observation_id",)),
        ("observations_v1", ("observation_id",)),
        ("track_heads", ("source_system", "source_scope", "track_id")),
        (
            "delivery_conflicts",
            ("source_system", "source_scope", "source_event_id", "attempted_digest"),
        ),
    )
    for table, columns in unique_requirements:
        if not _has_unique_index(connection, table, columns):
            joined = ", ".join(columns)
            raise MigrationError(f"existing {table} table lacks required uniqueness for {joined}")


def migrate_database(database_path: Path) -> None:
    """Apply the V0.2 migration atomically and repeatably."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("BEGIN IMMEDIATE")
        try:
            current_user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_user_version > SQLITE_USER_VERSION:
                raise MigrationError("database was created by a newer DroneWatch schema")
            existing_legacy = _table_signature(connection, "incidents")
            if existing_legacy and existing_legacy != TABLE_SIGNATURES["incidents"]:
                raise MigrationError("existing incidents table is not compatible with the V0.1 schema")

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    detection_type TEXT,
                    drone_detected INTEGER NOT NULL DEFAULT 0,
                    confidence REAL,
                    state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    severity TEXT NOT NULL DEFAULT 'INFO',
                    source TEXT,
                    media_url TEXT,
                    raw_payload TEXT NOT NULL,
                    is_simulated INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_system TEXT NOT NULL,
                    source_scope TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL UNIQUE,
                    content_digest TEXT NOT NULL,
                    first_received_at TEXT NOT NULL,
                    UNIQUE (source_system, source_scope, source_event_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observations_v1 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    source_system TEXT NOT NULL,
                    source_scope TEXT NOT NULL,
                    track_id TEXT,
                    scenario_id TEXT,
                    run_id TEXT,
                    observed_at TEXT NOT NULL,
                    observed_at_us INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    delivery_mode TEXT NOT NULL,
                    simulation INTEGER NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    detection_result TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    confidence REAL,
                    frame_coordinates_json TEXT,
                    content_digest TEXT NOT NULL,
                    request_digest TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS track_heads (
                    source_system TEXT NOT NULL,
                    source_scope TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    observation_database_id INTEGER NOT NULL,
                    source_event_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    observed_at_us INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    scenario_id TEXT,
                    run_id TEXT,
                    modality TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    delivery_mode TEXT NOT NULL,
                    simulation INTEGER NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    state_rank INTEGER NOT NULL,
                    detection_result TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    confidence REAL,
                    frame_coordinates_json TEXT,
                    content_digest TEXT NOT NULL,
                    PRIMARY KEY (source_system, source_scope, track_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_system TEXT NOT NULL,
                    source_scope TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    existing_digest TEXT NOT NULL,
                    attempted_digest TEXT NOT NULL,
                    first_received_at TEXT NOT NULL,
                    last_received_at TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    UNIQUE (source_system, source_scope, source_event_id, attempted_digest)
                )
                """
            )

            _require_schema_postconditions(connection)

            connection.execute(
                "CREATE INDEX IF NOT EXISTS observations_received_idx ON observations_v1(received_at DESC, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS observations_track_idx ON observations_v1(source_system, source_scope, track_id, observed_at_us DESC)"
            )

            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (MIGRATION_VERSION, rfc3339(datetime.now(timezone.utc))),
            )
            connection.execute(f"PRAGMA user_version = {SQLITE_USER_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def migration_versions(database_path: Path) -> list[str]:
    with _connect(database_path) as connection:
        return [row["version"] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]


def _insert_observation(
    connection: sqlite3.Connection,
    observation: CanonicalObservationV1,
    *,
    digest: str,
    request_digest: str,
) -> int:
    frame_json = (
        json.dumps(observation.frame_coordinates.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        if observation.frame_coordinates
        else None
    )
    cursor = connection.execute(
        """
        INSERT INTO observations_v1 (
            observation_id, schema_version, source_event_id, source_system,
            source_scope, track_id, scenario_id, run_id, observed_at,
            observed_at_us, received_at, modality, provenance, delivery_mode,
            simulation, lifecycle_state, detection_result, classification,
            confidence, frame_coordinates_json, content_digest, request_digest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(observation.observation_id),
            observation.schema_version,
            observation.source_event_id,
            observation.source_system,
            observation.source_scope,
            observation.track_id,
            observation.scenario_id,
            observation.run_id,
            rfc3339(observation.observed_at),
            observed_at_microseconds(observation.observed_at),
            rfc3339(observation.received_at),
            observation.modality,
            observation.provenance.value,
            observation.delivery_mode.value,
            int(observation.simulation),
            observation.lifecycle_state.value,
            observation.detection_result.value,
            observation.classification.value,
            observation.confidence,
            frame_json,
            digest,
            request_digest,
        ),
    )
    return int(cursor.lastrowid)


def _update_track_head(
    connection: sqlite3.Connection,
    observation: CanonicalObservationV1,
    *,
    database_id: int,
    digest: str,
) -> None:
    if (
        observation.track_id is None
        or observation.detection_result is not DetectionResult.POSITIVE
        or observation.classification is not Classification.DRONE
    ):
        return
    state_rank = {
        LifecycleState.DETECTED: 1,
        LifecycleState.APPROACHING: 2,
        LifecycleState.RESTRICTED_ZONE: 3,
        LifecycleState.EXITED: 4,
    }[observation.lifecycle_state]
    frame_json = (
        json.dumps(observation.frame_coordinates.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        if observation.frame_coordinates
        else None
    )
    connection.execute(
        """
        INSERT INTO track_heads (
            source_system, source_scope, track_id, observation_id,
            observation_database_id, source_event_id, observed_at,
            observed_at_us, received_at, scenario_id, run_id, modality,
            provenance, delivery_mode, simulation, lifecycle_state, state_rank,
            detection_result, classification, confidence,
            frame_coordinates_json, content_digest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_system, source_scope, track_id) DO UPDATE SET
            observation_id = excluded.observation_id,
            observation_database_id = excluded.observation_database_id,
            source_event_id = excluded.source_event_id,
            observed_at = excluded.observed_at,
            observed_at_us = excluded.observed_at_us,
            received_at = excluded.received_at,
            scenario_id = excluded.scenario_id,
            run_id = excluded.run_id,
            modality = excluded.modality,
            provenance = excluded.provenance,
            delivery_mode = excluded.delivery_mode,
            simulation = excluded.simulation,
            lifecycle_state = excluded.lifecycle_state,
            state_rank = excluded.state_rank,
            detection_result = excluded.detection_result,
            classification = excluded.classification,
            confidence = excluded.confidence,
            frame_coordinates_json = excluded.frame_coordinates_json,
            content_digest = excluded.content_digest
        WHERE excluded.observed_at_us > track_heads.observed_at_us
           OR (
                excluded.observed_at_us = track_heads.observed_at_us
                AND excluded.state_rank > track_heads.state_rank
           )
           OR (
                excluded.observed_at_us = track_heads.observed_at_us
                AND excluded.state_rank = track_heads.state_rank
                AND excluded.source_event_id COLLATE BINARY > track_heads.source_event_id COLLATE BINARY
           )
           OR (
                excluded.observed_at_us = track_heads.observed_at_us
                AND excluded.state_rank = track_heads.state_rank
                AND excluded.source_event_id COLLATE BINARY = track_heads.source_event_id COLLATE BINARY
                AND excluded.content_digest COLLATE BINARY > track_heads.content_digest COLLATE BINARY
           )
        """,
        (
            observation.source_system,
            observation.source_scope,
            observation.track_id,
            str(observation.observation_id),
            database_id,
            observation.source_event_id,
            rfc3339(observation.observed_at),
            observed_at_microseconds(observation.observed_at),
            rfc3339(observation.received_at),
            observation.scenario_id,
            observation.run_id,
            observation.modality,
            observation.provenance.value,
            observation.delivery_mode.value,
            int(observation.simulation),
            observation.lifecycle_state.value,
            state_rank,
            observation.detection_result.value,
            observation.classification.value,
            observation.confidence,
            frame_json,
            digest,
        ),
    )


def _apply_retention(
    connection: sqlite3.Connection,
    *,
    policy: RetentionPolicy,
    now: datetime,
) -> None:
    observation_cutoff = rfc3339(now - timedelta(days=policy.observation_days))
    conflict_cutoff = rfc3339(now - timedelta(days=policy.conflict_days))
    connection.execute("DELETE FROM observations_v1 WHERE received_at < ?", (observation_cutoff,))
    connection.execute(
        """
        DELETE FROM observations_v1
        WHERE id NOT IN (
            SELECT id FROM observations_v1 ORDER BY received_at DESC, id DESC LIMIT ?
        )
        """,
        (policy.observation_max_count,),
    )
    connection.execute("DELETE FROM delivery_conflicts WHERE last_received_at < ?", (conflict_cutoff,))
    connection.execute(
        """
        DELETE FROM delivery_conflicts
        WHERE id NOT IN (
            SELECT id FROM delivery_conflicts ORDER BY last_received_at DESC, id DESC LIMIT ?
        )
        """,
        (policy.conflict_max_count,),
    )


def store_observation(
    database_path: Path,
    observation: CanonicalObservationV1,
    *,
    request_digest: str,
    retention: RetentionPolicy,
) -> StoreResult:
    if not SHA256_PATTERN.fullmatch(request_digest):
        raise ValueError("request_digest must be a lowercase SHA-256 hex digest")
    digest = content_digest(observation)
    received = rfc3339(observation.received_at)
    with _connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            inserted_key = connection.execute(
                """
                INSERT INTO delivery_keys (
                    source_system, source_scope, source_event_id,
                    observation_id, content_digest, first_received_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_system, source_scope, source_event_id) DO NOTHING
                """,
                (
                    observation.source_system,
                    observation.source_scope,
                    observation.source_event_id,
                    str(observation.observation_id),
                    digest,
                    received,
                ),
            ).rowcount

            if inserted_key:
                database_id = _insert_observation(
                    connection,
                    observation,
                    digest=digest,
                    request_digest=request_digest,
                )
                _update_track_head(connection, observation, database_id=database_id, digest=digest)
                _apply_retention(connection, policy=retention, now=observation.received_at)
                connection.commit()
                return StoreResult("accepted", str(observation.observation_id), database_id, digest)

            existing = connection.execute(
                """
                SELECT observation_id, content_digest
                FROM delivery_keys
                WHERE source_system = ? AND source_scope = ? AND source_event_id = ?
                """,
                (observation.source_system, observation.source_scope, observation.source_event_id),
            ).fetchone()
            if existing is None:
                raise RuntimeError("idempotency ledger changed during a protected transaction")
            if existing["content_digest"] == digest:
                _apply_retention(connection, policy=retention, now=observation.received_at)
                connection.commit()
                return StoreResult("duplicate", existing["observation_id"], None, digest)

            connection.execute(
                """
                INSERT INTO delivery_conflicts (
                    source_system, source_scope, source_event_id,
                    existing_digest, attempted_digest, first_received_at,
                    last_received_at, attempt_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(source_system, source_scope, source_event_id, attempted_digest)
                DO UPDATE SET
                    last_received_at = excluded.last_received_at,
                    attempt_count = delivery_conflicts.attempt_count + 1
                """,
                (
                    observation.source_system,
                    observation.source_scope,
                    observation.source_event_id,
                    existing["content_digest"],
                    digest,
                    received,
                    received,
                ),
            )
            _apply_retention(connection, policy=retention, now=observation.received_at)
            connection.commit()
            return StoreResult("conflict", existing["observation_id"], None, digest)
        except Exception:
            connection.rollback()
            raise


def _compatibility_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": row["schema_version"] if "schema_version" in row.keys() else "dronewatch.event.v1",
        "source_event_id": row["source_event_id"],
        "source_scope": row["source_scope"],
        "track_id": row["track_id"],
        "scenario_id": row["scenario_id"],
        "run_id": row["run_id"],
        "observed_at": row["observed_at"],
        "modality": row["modality"],
        "provenance": row["provenance"],
        "delivery_mode": row["delivery_mode"],
        "classification": row["classification"],
        "detection_result": row["detection_result"],
    }
    frame_json = row["frame_coordinates_json"]
    if frame_json:
        frame = json.loads(frame_json)
        payload["position"] = {
            "x": round(frame["x"] + frame["width"] / 2, 6),
            "y": round(frame["y"] + frame["height"] / 2, 6),
        }
        payload["coordinate_space"] = "FRAME_NORMALIZED"
    sanitized = {key: value for key, value in payload.items() if value is not None}
    encoded = json.dumps(sanitized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_COMPATIBILITY_JSON_BYTES:
        # This cannot occur for a valid v1 observation with bounded identifiers,
        # but retain a deterministic fail-closed projection if a future schema is
        # widened without revisiting the dashboard compatibility boundary.
        return {
            "schema_version": str(payload["schema_version"])[:64],
            "source_event_id": str(payload["source_event_id"])[:128],
            "source_scope": str(payload["source_scope"])[:128],
        }
    return sanitized


def _severity(state: str, confidence: float | None) -> str:
    if state == LifecycleState.RESTRICTED_ZONE.value:
        return "HIGH"
    if state == LifecycleState.APPROACHING.value:
        return "WARNING"
    if state == LifecycleState.DETECTED.value and confidence is not None and confidence >= 0.85:
        return "WARNING"
    return "INFO"


def _project_row(row: sqlite3.Row, *, head: bool = False) -> dict[str, Any]:
    state = row["lifecycle_state"]
    positive_drone = (
        row["detection_result"] == DetectionResult.POSITIVE.value
        and row["classification"] == Classification.DRONE.value
    )
    database_id = row["observation_database_id"] if head else row["id"]
    return {
        "id": database_id,
        "schema_version": row["schema_version"] if "schema_version" in row.keys() else "dronewatch.event.v1",
        "observation_id": row["observation_id"],
        "event_id": row["source_event_id"],
        "source_event_id": row["source_event_id"],
        "source_system": row["source_system"],
        "source_scope": row["source_scope"],
        "track_id": row["track_id"],
        "scenario_id": row["scenario_id"],
        "run_id": row["run_id"],
        "observed_at": row["observed_at"],
        "received_at": row["received_at"],
        "modality": row["modality"],
        "provenance": row["provenance"],
        "delivery_mode": row["delivery_mode"],
        "detection_type": "drone" if positive_drone else None,
        "detection_result": row["detection_result"],
        "classification": row["classification"],
        "drone_detected": positive_drone,
        "confidence": row["confidence"],
        "state": state,
        "severity": _severity(state, row["confidence"]),
        "source": "SIMULATED" if bool(row["simulation"]) else row["source_system"],
        "media_url": None,
        "raw_payload": _compatibility_payload(row),
        "is_simulated": bool(row["simulation"]),
    }


def query_events(database_path: Path, *, limit: int) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 200))
    with _connect(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM observations_v1 ORDER BY id DESC LIMIT ?",
            (bounded_limit,),
        ).fetchall()
    return [_project_row(row) for row in rows]


def query_open_tracks(database_path: Path) -> list[dict[str, Any]]:
    with _connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM track_heads
            WHERE detection_result = ?
              AND classification = ?
              AND lifecycle_state IN (?, ?, ?)
            ORDER BY observed_at_us DESC, source_event_id COLLATE BINARY DESC
            """,
            (
                DetectionResult.POSITIVE.value,
                Classification.DRONE.value,
                LifecycleState.DETECTED.value,
                LifecycleState.APPROACHING.value,
                LifecycleState.RESTRICTED_ZONE.value,
            ),
        ).fetchall()
    return [_project_row(row, head=True) for row in rows]


def legacy_count(database_path: Path) -> int:
    with _connect(database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM incidents").fetchone()[0])


def query_legacy_events(database_path: Path, *, limit: int) -> list[dict[str, Any]]:
    """Return a fixed, sanitized quarantine view without parsing legacy raw data."""

    bounded_limit = max(1, min(int(limit), 200))
    with _connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, received_at, drone_detected, confidence, state, severity, is_simulated
            FROM incidents ORDER BY id DESC LIMIT ?
            """,
            (bounded_limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "schema_version": "legacy.v0.1.unverified",
            "event_id": f"legacy-{row['id']}",
            "received_at": str(row["received_at"])[:64],
            "detection_type": None,
            "drone_detected": False,
            "confidence": None,
            "state": "UNKNOWN",
            "severity": "INFO",
            "source": "LEGACY_UNVERIFIED",
            "media_url": None,
            "raw_payload": {"legacy_unverified": True},
            "is_simulated": bool(row["is_simulated"]),
        }
        for row in rows
    ]


def observation_count(database_path: Path) -> int:
    with _connect(database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM observations_v1").fetchone()[0])


def delivery_key_count(database_path: Path) -> int:
    with _connect(database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM delivery_keys").fetchone()[0])


def conflict_count(database_path: Path) -> int:
    with _connect(database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM delivery_conflicts").fetchone()[0])
