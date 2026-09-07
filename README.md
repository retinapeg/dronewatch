# DroneWatch

DroneWatch is an evidence-aware prototype for receiving visual observations,
retaining an auditable history, deriving effective track state, and presenting
incident awareness through the existing tactical dashboard.

`V0.2 REPOSITORY RELEASE CANDIDATE — EXTERNAL VISO ACCEPTANCE PENDING`

This is not a released V0.2, a calibrated radar, a certified counter-UAS
system, or evidence of operational airspace coverage.

The frontend is intentionally frozen. V0.2 changes the provider-neutral event
contract, receiver, persistence, replay tooling, and evidence controls without
changing `index.html`.

## What V0.2 implements locally

- A strict `dronewatch.event.v1` observation contract in Python and JSON Schema.
- Distinct source `observed_at` and server-assigned `received_at` timestamps.
- Authenticated, size-limited JSON ingestion at `POST /webhook/canonical`.
- Atomic idempotency by source system, source scope, and source event ID.
- Conflict evidence when one delivery key is reused with different content.
- Historical observations plus deterministic materialized track heads; a
  matching `EXITED` observation closes the effective track.
- A transactional, repeatable V0.1 SQLite migration that preserves legacy rows
  without treating them as verified canonical observations.
- A sanitized compatibility projection at `GET /api/events` for the unchanged
  dashboard.
- A finite, manifest-checked file-replay runner and machine-readable run record.
- A six-clip, CC0 Halmstad fixture manifest; all media remains outside Git.

The Viso-specific adapter is deliberately fail-closed. No genuine redacted
delivery or account-tested outbound authentication evidence was available when
this candidate was prepared. `POST /webhook/viso` therefore authenticates and
validates the request boundary, then returns `503 viso_adapter_unavailable`
without storing the body. It will be enabled only from evidence captured from
the user's configured Viso account. See [VISO_ACCEPTANCE.md](VISO_ACCEPTANCE.md).

## Truthful data labels

These values are not interchangeable:

| Provenance | Delivery mode | Meaning |
| --- | --- | --- |
| `SYNTHETIC` | `LOCAL_SIMULATION` | A generated DroneWatch test/demo observation. It is not sensor evidence. |
| `REPLAYED_REAL` | `NEAR_REAL_TIME_FILE_REPLAY` | Licensed recorded footage copied as a discrete file and processed later. It is not a live stream. |
| `LIVE` | `DIRECT` | A current direct observation from a proven source. V0.2 has no accepted Viso evidence for this path. |

Viso Now is the intended visual field for this milestone. It is not radar. No
radar, RF, ADS-B, Remote ID, sensor fusion, geolocation, model training, or
calibrated range/bearing/speed/heading is implemented in V0.2. Frame
coordinates, when present, are normalized image coordinates only.

## Install and run locally

Python 3.11+ is required. Node.js is required for the frozen-dashboard tests.

```bash
git clone https://github.com/retinapeg/dronewatch.git
cd dronewatch
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Configure a unique, non-production test token in the environment. It must have
at least 32 visible ASCII characters; there is no default or fallback token.

```bash
DRONEWATCH_WEBHOOK_TOKEN="$(openssl rand -hex 32)"
export DRONEWATCH_WEBHOOK_TOKEN
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The server creates or migrates the configured
SQLite database at startup. Do not expose this development process publicly.

The checked-in [.env.example](.env.example) lists every backend setting. The
application reads process environment variables directly; it does not
automatically load `.env` files.

### Receiver routes

- `POST /webhook/canonical`: provider-neutral contract/testing route. It
  rejects reserved `source_system: "VISO"` so synthetic contract fixtures
  cannot be mistaken for provider evidence.
- `POST /webhook/viso`: reserved provider route, currently fail-closed pending
  the Viso evidence gate.
- `GET /api/events`: public, sanitized dashboard projection. It never returns a
  complete inbound request.
- `GET /api/legacy/events`: authenticated, sanitized view of preserved V0.1
  rows labelled `LEGACY_UNVERIFIED`.
- `GET /health` and `GET /api/config`: non-secret health and effective-limit
  information.
- `POST /dev/simulate`: disabled by default and authenticated when explicitly
  enabled with `DRONEWATCH_SIMULATION=1`.

Example canonical request shape:

```json
{
  "schema_version": "dronewatch.event.v1",
  "source_event_id": "contract-test-event-001",
  "source_system": "CONTRACT_TEST",
  "source_scope": "local-lab",
  "track_id": "track-001",
  "scenario_id": "schema-demo",
  "run_id": "schema-demo-001",
  "observed_at": "2026-09-07T12:00:00Z",
  "modality": "VISUAL",
  "provenance": "SYNTHETIC",
  "delivery_mode": "LOCAL_SIMULATION",
  "simulation": true,
  "lifecycle_state": "DETECTED",
  "detection_result": "POSITIVE",
  "classification": "DRONE",
  "confidence": 0.83
}
```

`received_at` and the internal `observation_id` are server-owned fields and
must not appear in the inbound object. The example above is a
`SYNTHETIC_CONTRACT_FIXTURE`; it is not a Viso payload.

## Bounded visual-file replay

The replay command requires an explicit scenario, run, fixture, manifest,
source file, existing watched directory, and finite copy count. The hard
maximum is 20 copies. A successful run proves only local manifest validation and
atomic file copying.

```bash
.venv/bin/python demo_feed.py replay \
  --scenario-id perimeter-demo \
  --run-id perimeter-demo-001 \
  --fixture-id halmstad-v-drone-001 \
  --manifest fixtures/halmstad-selection.v1.json \
  --source /path/to/V_DRONE_001.mp4 \
  --watch-dir /path/to/existing/watched-folder \
  --count 3 \
  --interval 25
```

The runner publishes each completed file atomically without replacing an
existing basename, retains completed copies, removes an unfinished `.part`
file on failure/interruption, and writes a redacted run record under the
ignored `run-records/` directory.
It does not prove Google Drive sync, Viso processing, webhook delivery, or
detection performance. Use `demo_feed.py serve` for loopback-only video
playback; serving creates no copies. Full details are in
[DEMO_FEED.md](DEMO_FEED.md).

## Verification

Run the reproducible repository checks from the repository root:

```bash
.venv/bin/python -m pytest -q
node --test tests/dashboard.test.cjs
.venv/bin/python scripts/export_schemas.py --check
.venv/bin/python scripts/verify_replay_artifacts.py
.venv/bin/python scripts/verify_frontend.py
.venv/bin/python scripts/http_smoke.py
.venv/bin/python -m compileall -q .
bash -n start-drive-copy.command
git diff --check
.venv/bin/pip-audit -r requirements.txt
```

The release handoff must separately record the exact test counts, HTTP smoke
observations, dependency-audit result, candidate commit, and protected frontend
hashes. CI reproduces the listed checks except the explicitly local-only
`scripts/http_smoke.py` run. It does not exercise a Viso account, Google Drive
sync, a public tunnel, or the supervised end-to-end run.

The two observation schemas include their portable cross-field contract rules.
The three replay/manifest/evidence schemas define portable structure; their
cross-field and pack-level rules are normatively enforced by
`replay_artifacts.py` and `scripts/verify_replay_artifacts.py`.

## Configuration and retention defaults

| Variable | Default | Boundary |
| --- | --- | --- |
| `DRONEWATCH_WEBHOOK_TOKEN` | none | Required for all webhook writes and legacy access; minimum 32 visible ASCII characters. |
| `DRONEWATCH_DB_PATH` | `dronewatch.db` | SQLite path; relative paths resolve from the repository. |
| `DRONEWATCH_WEBHOOK_MAX_BYTES` | `65536` | Streamed request cap; configurable from 1 KiB through 1 MiB. |
| `DRONEWATCH_MAX_FUTURE_SECONDS` | `60` | Maximum accepted source-clock lead; configurable from 0 through 3600 seconds. |
| `DRONEWATCH_OBSERVATION_RETENTION_DAYS` | `30` | Canonical-history age limit; 1 through 3650 days. |
| `DRONEWATCH_OBSERVATION_MAX_COUNT` | `10000` | Canonical-history count limit; 1 through 1,000,000. |
| `DRONEWATCH_CONFLICT_RETENTION_DAYS` | `7` | Digest-only conflict-evidence age limit; 1 through 365 days. |
| `DRONEWATCH_CONFLICT_MAX_COUNT` | `1000` | Digest-only conflict-evidence count limit; 1 through 100,000. |
| `DRONEWATCH_SIMULATION` | `0` | Enables the authenticated development simulation route only when explicitly truthy. |

Full inbound bodies are not retained. Retention never removes the permanent
delivery-key ledger, materialized track heads, or preserved legacy records.
See [SECURITY.md](SECURITY.md) and [MIGRATION.md](MIGRATION.md).

`start-drive-copy.command` additionally reads the non-secret launcher inputs
`DRONEWATCH_SCENARIO_ID`, `DRONEWATCH_RUN_ID`, `DRONEWATCH_FIXTURE_ID`,
`DRONEWATCH_FIXTURE_MANIFEST`, `DRONEWATCH_DEMO_SOURCE`,
`DRONEWATCH_DRIVE_FOLDER`, `DRONEWATCH_COPY_COUNT`,
`DRONEWATCH_COPY_INTERVAL`, `DRONEWATCH_RUN_RECORD_DIR`, and
`DRONEWATCH_PYTHON`. Their prompt/default behavior is documented in
[DEMO_FEED.md](DEMO_FEED.md). No Viso/Drive/OAuth credential variable is
invented or loaded by DroneWatch; Viso account/API OAuth stays blank for the
V0.2 acceptance run.

## Repository and release boundaries

- Fixture media, run records, SQLite databases, credentials, and unredacted,
  sensitive, credential-bearing, or machine-local account evidence are
  intentionally excluded from Git. A reviewed sanitized Viso fixture or result
  summary may be committed only after the acceptance review.
- The repository has no software licence. Public visibility alone does not
  grant reuse rights.
- Viso workflow configuration, account state, connector credentials, and any
  sensitive URLs remain outside this repository.
- No tunnel, media upload, account change, push, merge, or release tag is part
  of repository-local verification.
- Do not create `v0.2.0` until every gate in
  [VISO_ACCEPTANCE.md](VISO_ACCEPTANCE.md) and
  [RELEASE_CANDIDATE.md](RELEASE_CANDIDATE.md) is satisfied and the user
  explicitly approves the release action.
