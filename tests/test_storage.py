"""Database migration, idempotency, lifecycle, retention, and projection tests."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from contracts import InboundObservationV1, build_canonical_observation, rfc3339
from storage import (
    LEGACY_COLUMNS,
    MIGRATION_VERSION,
    OBSERVATION_COLUMNS,
    SQLITE_USER_VERSION,
    MigrationError,
    RetentionPolicy,
    conflict_count,
    delivery_key_count,
    legacy_count,
    migrate_database,
    migration_versions,
    observation_count,
    query_events,
    query_legacy_events,
    query_open_tracks,
    store_observation,
)


DEFAULT_POLICY = RetentionPolicy(
    observation_days=3650,
    observation_max_count=10_000,
    conflict_days=365,
    conflict_max_count=1_000,
)
BASE_TIME = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)


def make_observation(
    event_id: str,
    *,
    scope: str = "camera-north",
    track_id: str | None = "track-1",
    state: str = "DETECTED",
    result: str = "POSITIVE",
    classification: str = "DRONE",
    observed_at: datetime = BASE_TIME,
    received_at: datetime | None = None,
    confidence: float | None = 0.8,
    coordinates: dict | None = None,
):
    inbound = InboundObservationV1.model_validate(
        {
            "schema_version": "dronewatch.event.v1",
            "source_event_id": event_id,
            "source_system": "STORAGE_TEST",
            "source_scope": scope,
            "track_id": track_id,
            "scenario_id": None,
            "run_id": None,
            "observed_at": rfc3339(observed_at),
            "modality": "VISUAL",
            "provenance": "LIVE",
            "delivery_mode": "DIRECT",
            "simulation": False,
            "lifecycle_state": state,
            "detection_result": result,
            "classification": classification,
            "confidence": confidence,
            "frame_coordinates": coordinates,
        }
    )
    return build_canonical_observation(inbound, received_at=received_at or observed_at)


def request_digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def store(database_path, observation, *, policy=DEFAULT_POLICY, digest_label=None):
    return store_observation(
        database_path,
        observation,
        request_digest=request_digest(digest_label or observation.source_event_id),
        retention=policy,
    )


def create_v01_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE incidents (
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


def test_database_and_wal_sidecars_are_owner_only(tmp_path):
    database_path = tmp_path / "private.db"
    with sqlite3.connect(database_path) as connection:
        create_v01_table(connection)
    os.chmod(database_path, 0o644)

    migrate_database(database_path)
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO incidents(event_id, received_at, raw_payload) VALUES (?, ?, ?)",
            ("permission-test", "2026-09-07T00:00:00Z", "{}"),
        )
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(database_path) + suffix)
            assert sidecar.is_file()
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600
        connection.rollback()


def test_fresh_migration_is_complete_versioned_and_repeatable(tmp_path):
    database_path = tmp_path / "fresh.db"

    migrate_database(database_path)
    first_schema = sqlite3.connect(database_path).execute(
        "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name"
    ).fetchall()
    migrate_database(database_path)
    second_schema = sqlite3.connect(database_path).execute(
        "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name"
    ).fetchall()

    assert first_schema == second_schema
    assert migration_versions(database_path) == [MIGRATION_VERSION]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SQLITE_USER_VERSION
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {
        "incidents",
        "schema_migrations",
        "delivery_keys",
        "observations_v1",
        "track_heads",
        "delivery_conflicts",
    }.issubset(tables)


def test_migration_preserves_v01_rows_and_raw_payload_bytes_exactly(tmp_path):
    database_path = tmp_path / "v01.db"
    raw_payload = b'\x00{"secret":"do-not-expose"}\xff'
    with sqlite3.connect(database_path) as connection:
        create_v01_table(connection)
        connection.execute(
            """
            INSERT INTO incidents (
                event_id, received_at, detection_type, drone_detected,
                confidence, state, severity, source, media_url,
                raw_payload, is_simulated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-event",
                "2026-01-01T00:00:00Z",
                "drone",
                1,
                0.99,
                "RESTRICTED_ZONE",
                "HIGH",
                "legacy-source",
                "https://private.example/media",
                sqlite3.Binary(raw_payload),
                0,
            ),
        )
        before = connection.execute("SELECT * FROM incidents").fetchall()

    migrate_database(database_path)
    migrate_database(database_path)

    with sqlite3.connect(database_path) as connection:
        after = connection.execute("SELECT * FROM incidents").fetchall()
        stored_raw, storage_type = connection.execute(
            "SELECT raw_payload, typeof(raw_payload) FROM incidents"
        ).fetchone()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(incidents)")}
    assert after == before
    assert stored_raw == raw_payload
    assert storage_type == "blob"
    assert LEGACY_COLUMNS.issubset(columns)
    assert legacy_count(database_path) == 1


def test_incompatible_legacy_schema_fails_without_partial_v02_tables(tmp_path):
    database_path = tmp_path / "bad-legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE incidents (id INTEGER PRIMARY KEY, raw_payload TEXT)")

    with pytest.raises(MigrationError, match="V0.1 schema"):
        migrate_database(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "incidents" in tables
    assert "observations_v1" not in tables
    assert "delivery_keys" not in tables


def test_partial_v02_schema_fails_closed_and_rolls_back_other_tables(tmp_path):
    database_path = tmp_path / "partial.db"
    with sqlite3.connect(database_path) as connection:
        create_v01_table(connection)
        connection.execute("CREATE TABLE observations_v1 (id INTEGER PRIMARY KEY)")

    with pytest.raises(MigrationError, match="observations_v1 table has an incompatible definition"):
        migrate_database(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {row[1] for row in connection.execute("PRAGMA table_info(observations_v1)")} == {"id"}
    assert "delivery_keys" not in tables
    assert "track_heads" not in tables


def test_all_required_v02_columns_with_wrong_signatures_fail_closed(tmp_path):
    database_path = tmp_path / "wrong-signatures.db"
    definitions = ", ".join(
        f'"{column}" TEXT' for column in sorted(OBSERVATION_COLUMNS)
    )
    with sqlite3.connect(database_path) as connection:
        create_v01_table(connection)
        connection.execute(f"CREATE TABLE observations_v1 ({definitions})")

    with pytest.raises(MigrationError, match="incompatible definition"):
        migrate_database(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "observations_v1" in tables
    assert "delivery_keys" not in tables
    assert "track_heads" not in tables


def test_partial_unique_index_does_not_satisfy_schema_postcondition(tmp_path):
    reference_path = tmp_path / "reference.db"
    migrate_database(reference_path)
    with sqlite3.connect(reference_path) as connection:
        create_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='observations_v1'"
        ).fetchone()[0]
    without_unique = create_sql.replace(
        "observation_id TEXT NOT NULL UNIQUE", "observation_id TEXT NOT NULL"
    )
    assert without_unique != create_sql

    database_path = tmp_path / "partial-index.db"
    with sqlite3.connect(database_path) as connection:
        create_v01_table(connection)
        connection.execute(without_unique)
        connection.execute(
            """
            CREATE UNIQUE INDEX partial_observation_id
            ON observations_v1(observation_id)
            WHERE source_system = 'ONLY_THIS_SOURCE'
            """
        )

    with pytest.raises(MigrationError, match="lacks required uniqueness"):
        migrate_database(database_path)


def test_newer_database_user_version_is_rejected(tmp_path):
    database_path = tmp_path / "future.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {SQLITE_USER_VERSION + 1}")

    with pytest.raises(MigrationError, match="newer DroneWatch schema"):
        migrate_database(database_path)


def test_exact_retry_is_idempotent_and_changed_retry_is_audited(tmp_path):
    database_path = tmp_path / "idempotency.db"
    migrate_database(database_path)
    first = make_observation("evt-1", received_at=BASE_TIME)
    exact_retry = make_observation("evt-1", received_at=BASE_TIME + timedelta(seconds=5))
    changed_retry = make_observation(
        "evt-1", received_at=BASE_TIME + timedelta(seconds=10), confidence=0.9
    )

    accepted = store(database_path, first, digest_label="first-request")
    duplicate = store(database_path, exact_retry, digest_label="retry-request")
    conflict = store(database_path, changed_retry, digest_label="conflict-request")

    assert accepted.status == "accepted"
    assert duplicate.status == "duplicate"
    assert duplicate.observation_id == accepted.observation_id
    assert conflict.status == "conflict"
    assert conflict.observation_id == accepted.observation_id
    assert observation_count(database_path) == 1
    assert delivery_key_count(database_path) == 1
    assert conflict_count(database_path) == 1
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT existing_digest, attempted_digest, attempt_count FROM delivery_conflicts"
        ).fetchone()
    assert row[0] != row[1]
    assert row[2] == 1


def test_idempotency_scope_includes_source_scope(tmp_path):
    database_path = tmp_path / "scoped.db"
    migrate_database(database_path)

    one = store(database_path, make_observation("evt-shared", scope="camera-a"))
    two = store(database_path, make_observation("evt-shared", scope="camera-b"))

    assert (one.status, two.status) == ("accepted", "accepted")
    assert one.observation_id != two.observation_id
    assert observation_count(database_path) == 2
    assert delivery_key_count(database_path) == 2


def test_concurrent_exact_deliveries_commit_once(tmp_path):
    database_path = tmp_path / "concurrent.db"
    migrate_database(database_path)

    def submit(index: int):
        observation = make_observation(
            "evt-concurrent", received_at=BASE_TIME + timedelta(microseconds=index)
        )
        return store(database_path, observation, digest_label=f"request-{index}")

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(submit, range(24)))

    assert sum(result.status == "accepted" for result in results) == 1
    assert sum(result.status == "duplicate" for result in results) == 23
    assert len({result.observation_id for result in results}) == 1
    assert observation_count(database_path) == 1
    assert delivery_key_count(database_path) == 1
    assert conflict_count(database_path) == 0


@pytest.mark.parametrize("invalid", ["", "a" * 63, "A" * 64, "g" * 64, "a" * 65])
def test_request_digest_must_be_exact_lowercase_sha256_hex(tmp_path, invalid):
    database_path = tmp_path / "digest.db"
    migrate_database(database_path)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        store_observation(
            database_path,
            make_observation("evt-digest"),
            request_digest=invalid,
            retention=DEFAULT_POLICY,
        )
    assert observation_count(database_path) == 0
    assert delivery_key_count(database_path) == 0


def test_track_head_uses_time_then_state_then_binary_event_id_precedence(tmp_path):
    database_path = tmp_path / "heads.db"
    migrate_database(database_path)

    store(database_path, make_observation("evt-A", state="DETECTED"))
    store(database_path, make_observation("evt-a", state="DETECTED"))
    assert query_open_tracks(database_path)[0]["source_event_id"] == "evt-a"

    # State rank outranks event id when source time is equal.
    store(database_path, make_observation("evt-000", state="RESTRICTED_ZONE"))
    store(database_path, make_observation("evt-zzz", state="APPROACHING"))
    assert query_open_tracks(database_path)[0]["state"] == "RESTRICTED_ZONE"
    assert query_open_tracks(database_path)[0]["source_event_id"] == "evt-000"

    # EXITED is retained as the head and closes the materialized open-track view.
    store(database_path, make_observation("evt-exited", state="EXITED"))
    assert query_open_tracks(database_path) == []

    # A later source observation can reopen; an older exit cannot overwrite it.
    later = BASE_TIME + timedelta(seconds=1)
    store(database_path, make_observation("evt-reopen", observed_at=later, received_at=later))
    store(
        database_path,
        make_observation(
            "evt-old-exit",
            state="EXITED",
            observed_at=BASE_TIME - timedelta(seconds=1),
            received_at=later + timedelta(seconds=1),
        ),
    )
    open_tracks = query_open_tracks(database_path)
    assert len(open_tracks) == 1
    assert open_tracks[0]["source_event_id"] == "evt-reopen"


def test_track_isolation_and_unmatched_exit_never_close_another_track(tmp_path):
    database_path = tmp_path / "track-isolation.db"
    migrate_database(database_path)

    store(database_path, make_observation("evt-track-a", track_id="track-a"))
    store(
        database_path,
        make_observation(
            "evt-unmatched-exit",
            track_id="track-b",
            state="EXITED",
            observed_at=BASE_TIME + timedelta(seconds=1),
            received_at=BASE_TIME + timedelta(seconds=1),
        ),
    )

    open_tracks = query_open_tracks(database_path)
    assert len(open_tracks) == 1
    assert open_tracks[0]["track_id"] == "track-a"
    assert observation_count(database_path) == 2
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM track_heads").fetchone()[0] == 2


def test_late_older_detection_cannot_reopen_a_newer_exit(tmp_path):
    database_path = tmp_path / "late-detection.db"
    migrate_database(database_path)
    newer = BASE_TIME + timedelta(seconds=5)

    store(
        database_path,
        make_observation(
            "evt-new-exit", state="EXITED", observed_at=newer, received_at=newer
        ),
    )
    store(
        database_path,
        make_observation(
            "evt-late-old-detection",
            state="DETECTED",
            observed_at=BASE_TIME,
            received_at=newer + timedelta(seconds=1),
        ),
    )

    assert query_open_tracks(database_path) == []
    assert observation_count(database_path) == 2


def test_open_track_state_is_independent_of_history_page_limit(tmp_path):
    database_path = tmp_path / "pagination-independent.db"
    migrate_database(database_path)
    store(database_path, make_observation("evt-open", track_id="track-open"))
    for index in range(5):
        later = BASE_TIME + timedelta(seconds=index + 1)
        store(
            database_path,
            make_observation(
                f"evt-negative-{index}",
                track_id=None,
                state="UNKNOWN",
                result="NEGATIVE",
                classification="NOT_DRONE",
                observed_at=later,
                received_at=later,
            ),
        )

    one_event = query_events(database_path, limit=1)
    assert len(one_event) == 1
    assert one_event[0]["detection_result"] == "NEGATIVE"
    open_tracks = query_open_tracks(database_path)
    assert len(open_tracks) == 1
    assert open_tracks[0]["track_id"] == "track-open"


def test_negative_and_unknown_observations_never_close_a_track(tmp_path):
    database_path = tmp_path / "negative.db"
    migrate_database(database_path)
    store(database_path, make_observation("evt-positive"))
    store(
        database_path,
        make_observation(
            "evt-negative",
            state="UNKNOWN",
            result="NEGATIVE",
            classification="NOT_DRONE",
            observed_at=BASE_TIME + timedelta(seconds=2),
            received_at=BASE_TIME + timedelta(seconds=2),
        ),
    )
    store(
        database_path,
        make_observation(
            "evt-unknown",
            state="UNKNOWN",
            result="UNKNOWN",
            classification="UNKNOWN",
            observed_at=BASE_TIME + timedelta(seconds=3),
            received_at=BASE_TIME + timedelta(seconds=3),
        ),
    )

    open_tracks = query_open_tracks(database_path)
    assert len(open_tracks) == 1
    assert open_tracks[0]["source_event_id"] == "evt-positive"
    assert observation_count(database_path) == 3


def test_retention_prunes_history_but_not_keys_heads_or_legacy(tmp_path):
    database_path = tmp_path / "retention.db"
    migrate_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO incidents (
                event_id, received_at, drone_detected, state, severity,
                raw_payload, is_simulated
            ) VALUES ('legacy', '2020-01-01T00:00:00Z', 0, 'UNKNOWN', 'INFO', '{}', 0)
            """
        )
    policy = RetentionPolicy(
        observation_days=1,
        observation_max_count=1,
        conflict_days=1,
        conflict_max_count=1,
    )
    old = BASE_TIME - timedelta(days=10)
    first = make_observation("evt-old-1", observed_at=old, received_at=old)
    store(database_path, first, policy=policy)
    store(
        database_path,
        make_observation(
            "evt-old-2",
            observed_at=old + timedelta(seconds=1),
            received_at=old + timedelta(seconds=1),
        ),
        policy=policy,
    )
    store(database_path, make_observation("evt-current"), policy=policy)

    assert observation_count(database_path) == 1
    assert query_events(database_path, limit=20)[0]["source_event_id"] == "evt-current"
    assert delivery_key_count(database_path) == 3
    assert legacy_count(database_path) == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM track_heads").fetchone()[0] == 1

    # A pruned observation remains idempotently consumed and is not resurrected.
    retry = make_observation(
        "evt-old-1", observed_at=old, received_at=BASE_TIME + timedelta(seconds=10)
    )
    result = store(database_path, retry, policy=policy, digest_label="old-retry")
    assert result.status == "duplicate"
    assert observation_count(database_path) == 1
    assert delivery_key_count(database_path) == 3


def test_duplicate_delivery_advances_history_retention_without_reopening_key(tmp_path):
    database_path = tmp_path / "duplicate-retention.db"
    migrate_database(database_path)
    policy = RetentionPolicy(
        observation_days=1,
        observation_max_count=100,
        conflict_days=1,
        conflict_max_count=100,
    )
    old_time = BASE_TIME - timedelta(days=10)
    original = make_observation(
        "evt-old-duplicate", observed_at=old_time, received_at=old_time
    )
    store(database_path, original, policy=policy)
    assert observation_count(database_path) == 1

    retry = make_observation(
        "evt-old-duplicate", observed_at=old_time, received_at=BASE_TIME
    )
    result = store(database_path, retry, policy=policy)

    assert result.status == "duplicate"
    assert observation_count(database_path) == 0
    assert delivery_key_count(database_path) == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM track_heads").fetchone()[0] == 1


def test_conflict_retention_is_bounded_and_repeated_digest_is_counted(tmp_path):
    database_path = tmp_path / "conflict-retention.db"
    migrate_database(database_path)
    policy = RetentionPolicy(
        observation_days=30,
        observation_max_count=100,
        conflict_days=30,
        conflict_max_count=2,
    )
    store(database_path, make_observation("evt-conflict", confidence=0.5), policy=policy)
    for index, confidence in enumerate((0.6, 0.7, 0.8), start=1):
        result = store(
            database_path,
            make_observation(
                "evt-conflict",
                confidence=confidence,
                received_at=BASE_TIME + timedelta(seconds=index),
            ),
            policy=policy,
            digest_label=f"conflict-{index}",
        )
        assert result.status == "conflict"
    # Repeat the newest conflicting content; it updates the audit row, not history.
    store(
        database_path,
        make_observation(
            "evt-conflict", confidence=0.8, received_at=BASE_TIME + timedelta(seconds=10)
        ),
        policy=policy,
        digest_label="conflict-repeat",
    )

    assert conflict_count(database_path) == 2
    assert observation_count(database_path) == 1
    assert delivery_key_count(database_path) == 1
    with sqlite3.connect(database_path) as connection:
        counts = sorted(
            row[0] for row in connection.execute("SELECT attempt_count FROM delivery_conflicts")
        )
    assert counts == [1, 2]


def test_event_projection_is_bounded_compatible_and_does_not_leak_storage_fields(tmp_path):
    database_path = tmp_path / "projection.db"
    migrate_database(database_path)
    coordinates = {
        "coordinate_space": "FRAME_NORMALIZED",
        "x": 0.1,
        "y": 0.2,
        "width": 0.4,
        "height": 0.2,
    }
    store(database_path, make_observation("evt-projection", coordinates=coordinates))

    events = query_events(database_path, limit=10_000)

    assert len(events) == 1
    event = events[0]
    assert event["event_id"] == "evt-projection"
    assert event["drone_detected"] is True
    assert event["detection_type"] == "drone"
    assert event["media_url"] is None
    assert event["raw_payload"]["position"] == {"x": 0.3, "y": 0.3}
    assert event["raw_payload"]["coordinate_space"] == "FRAME_NORMALIZED"
    encoded = json.dumps(event, sort_keys=True)
    for forbidden in (
        "request_digest",
        "content_digest",
        "frame_coordinates_json",
        "observation_database_id",
    ):
        assert forbidden not in encoded
    assert len(json.dumps(event["raw_payload"]).encode("utf-8")) < 4_096


def test_legacy_projection_is_quarantined_and_never_parses_raw_data(tmp_path):
    database_path = tmp_path / "legacy-projection.db"
    migrate_database(database_path)
    marker = "VERY_SECRET_LEGACY_MARKER"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO incidents (
                event_id, received_at, detection_type, drone_detected,
                confidence, state, severity, source, media_url,
                raw_payload, is_simulated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                marker,
                "2026-09-07T12:00:00Z" + ("X" * 100),
                "drone",
                1,
                1.0,
                "RESTRICTED_ZONE",
                "HIGH",
                marker,
                f"https://{marker}.example/secret",
                json.dumps({"authorization": marker}),
                1,
            ),
        )

    events = query_legacy_events(database_path, limit=20)

    assert len(events) == 1
    event = events[0]
    assert event == {
        "id": 1,
        "schema_version": "legacy.v0.1.unverified",
        "event_id": "legacy-1",
        "received_at": ("2026-09-07T12:00:00Z" + ("X" * 100))[:64],
        "detection_type": None,
        "drone_detected": False,
        "confidence": None,
        "state": "UNKNOWN",
        "severity": "INFO",
        "source": "LEGACY_UNVERIFIED",
        "media_url": None,
        "raw_payload": {"legacy_unverified": True},
        "is_simulated": True,
    }
    assert marker not in json.dumps(events)
