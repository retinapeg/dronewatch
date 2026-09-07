# V0.1 to V0.2 SQLite migration

DroneWatch applies the V0.2 schema migration during FastAPI lifespan startup.
The operation is transactional, repeatable, and additive. It does not delete or
rewrite V0.1 incident rows.

The database is created or tightened to owner read/write permissions (`0600`).
SQLite WAL, shared-memory, and rollback-journal sidecars inherit or are
tightened to the same private mode.

## Supported starting states

The migration handles:

- a fresh database with no tables;
- the exact V0.1 `incidents` schema, with or without existing rows;
- an already migrated V0.2 database; and
- a repeat startup after a transaction was interrupted before commit.

SQLite uses `BEGIN IMMEDIATE`, so schema checks, table creation, the migration
record, and `PRAGMA user_version = 2` commit together. SQLite rolls back an
uncommitted transaction. Running startup again is the recovery action for a
compatible interrupted attempt.

DroneWatch refuses to proceed if the existing `incidents` table or any V0.2
table has incompatible column names, types, nullability, primary-key order, or
defaults; if required full binary-collated ascending uniqueness is absent; or if
the database reports a future schema version. Partial unique indexes do not
satisfy the postcondition. It fails visibly rather than guessing how to
reinterpret the database.

## V0.2 storage layout

| Table | Purpose | Retention |
| --- | --- | --- |
| `incidents` | Preserved V0.1 rows. New canonical observations are not written here. | Never pruned by V0.2 retention. |
| `schema_migrations` | Applied migration identifiers and UTC application time. | Permanent. |
| `delivery_keys` | Permanent composite idempotency ledger keyed by source system, source scope, and source event ID. | Never pruned; prevents a retained key from being accepted again after history expires. |
| `observations_v1` | Canonical `dronewatch.event.v1` history with normalized and exact-request SHA-256 digests. | Default 30 days and 10,000 rows. |
| `track_heads` | Current effective state per source system/scope/track. | Never pruned by history retention. |
| `delivery_conflicts` | Digest-only audit of conflicting reuse of one delivery key. | Default 7 days and 1,000 rows. |

Full request bodies are not persisted. `request_digest` proves byte identity of
the accepted request without retaining the request, while `content_digest`
covers deterministic normalized source content and excludes the server-created
observation ID and receipt time.

## Legacy quarantine

Existing V0.1 rows are preserved byte-for-byte in `incidents`; they are not
promoted into `observations_v1`, used as current track state, or labelled as
authenticated Viso evidence.

The ordinary `GET /api/events` response reports only
`legacy_unverified_count`. An authenticated operator can use
`GET /api/legacy/events` to obtain a fixed projection marked
`LEGACY_UNVERIFIED`. This projection forces unknown/non-detection semantics and
does not parse or return the historical `raw_payload`, media URL, source string,
or event identifier. This is a compatibility/quarantine path, not provenance
verification.

## Idempotency and conflict behaviour

Insertion begins by atomically reserving this unique key:

```text
(source_system, source_scope, source_event_id)
```

- First valid delivery: reserves the key and stores one canonical observation
  in the same transaction.
- Identical retry: returns the original observation ID with a duplicate
  acknowledgement and creates no second history row.
- Same source event ID in another scope: remains a distinct delivery.
- Same composite key with different normalized content: leaves the original
  untouched, returns a conflict, and stores only the existing/attempted digests,
  timestamps, and attempt count in `delivery_conflicts`.

There is no race-prone read-before-insert decision. `BEGIN IMMEDIATE` plus the
database unique constraint governs sequential and concurrent deliveries.

## Effective track state

Validated positive `DRONE` observations with a track ID can update
`track_heads`. State is scoped by source system, source scope, and track ID.
Explicit negative and `UNKNOWN` observations remain in history but never open or
close a track. An unmatched `EXITED` head is retained as closed state and never
appears in `open_incidents`.

The deterministic ordering is:

1. later `observed_at` wins;
2. at the same time, `EXITED` > `RESTRICTED_ZONE` > `APPROACHING` > `DETECTED`;
3. if time and state are equal, lexicographically larger `source_event_id` using
   SQLite binary collation wins; and
4. if those also match, the lexicographically larger normalized content digest
   wins.

Consequently, a late older detection cannot reopen a track after a newer exit,
and an older exit cannot close a newer detection. Future observations beyond
the configured receipt-time tolerance are rejected before storage. Open state
comes from `track_heads`, independent of event-history pagination and retention.

## Safe upgrade procedure

1. Stop every process writing to the database.
2. Record the current application commit and configured database location.
3. Make a recoverable SQLite backup while the database is quiescent. If the
   `sqlite3` utility is available, use its `.backup` command so WAL state is
   captured consistently; otherwise copy the database plus any associated
   `-wal` and `-shm` files only while all writers are stopped.
4. Start the V0.2 candidate once with the intended environment.
5. Confirm `/health`, `/api/config`, legacy count, migration version, canonical
   ingestion, duplicate behaviour, and effective track closure against a test
   database before operating on important local data.
6. Keep the backup until the supervised acceptance run and rollback window are
   complete.

Do not put a database, backup, WAL file, or machine-specific path in Git.

## Rollback and recovery

There is intentionally no destructive down-migration. To roll back application
code:

1. stop all DroneWatch writers;
2. retain the V0.2 database and backup;
3. run the prior V0.1 commit against a copied database first; V0.1 ignores the
   additive V0.2 tables and still sees the preserved `incidents` table; and
4. restore the pre-upgrade backup only if the operator explicitly chooses to
   discard **all post-backup V0.2 canonical events**.

Never use `DROP TABLE`, blanket deletes, `git clean`, or a guessed manual schema
repair as a rollback. If startup reports an incompatible/partial schema, stop
writers, preserve the failed database for diagnosis, and restore a verified
backup to a new file. Re-running migration is appropriate only when the schema
is compatible and the prior attempt failed before its transaction committed.
