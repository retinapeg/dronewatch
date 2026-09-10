# Backend and official Codex CLI evidence

## Starting point

- Repository: `https://github.com/retinapeg/dronewatch.git`, baseline `31a32e1`.
- Isolated worktree `dronewatch-backend`, branch `codex/demo-boundary`.
- FastAPI/SQLite app serves the frontend and receives `POST /webhook/viso`.
- Baseline supervisor command `../dronewatch/.venv/bin/python -m pytest -q`: **10 passed**, one dependency deprecation warning, 0.84s.
- Original application ran locally through the new launcher on port 8773; `/` and `/health` returned HTTP 200. This startup smoke precedes the new frontend integration.

## Official Codex contribution

The installed official CLI reported `codex-cli 0.151.0`; `codex exec --help` and `codex login status` were inspected. Login was available through ChatGPT. No credential contents were read, printed, or copied.

The first run inherited a configured model the installed CLI could not execute. It returned: “The 'gpt-6-astra' model requires a newer version of Codex.” That run made no code changes. The retry uses the CLI default through `--ignore-user-config`; the actual resolved model was not emitted and is not inferred.

The successful engineering invocation, from the backend worktree:

```bash
codex exec --ignore-user-config \
  -C "$PWD" -s workspace-write --json \
  -o ../.agent-runs/codex-backend/final-retry.txt \
  - < ../.agent-runs/codex-backend/task.txt \
  > ../.agent-runs/codex-backend/events-retry.jsonl \
  2> ../.agent-runs/codex-backend/stderr-retry.log
```

Raw run logs and prompts are outside Git in the parent `.agent-runs/codex-backend/` directory. The CLI independently inspected the baseline, authored `main.py` changes, `target_schema.py`, and `tests/test_ingestion_boundary.py`, reproduced failing tests before implementation, and responded to supervisor-authored adversarial regressions. It did not commit, push, or edit another worktree.

The CLI's managed sandbox prevents binding a localhost socket. Therefore the original `test_video_range_requests_and_no_directory_access` cannot pass inside that sandbox. The supervisor runs the full suite, including that actual socket test, through the normal task execution environment; it is not skipped in the release gate.

## Reproduced defects and response

- Invalid UTF-8 caused an unhandled HTTP 500. Malformed JSON could be stored as a success. Invalid input now returns HTTP 400 without creating a record.
- JSON NaN/Infinity and extreme exponents were accepted. In this installed FastAPI version these can serialize as null, but Infinity still produced a misleading WARNING. The parser now rejects non-finite JSON numbers and confidence coercion returns null outside a finite 0–1 range (percentages through 100 remain accepted).
- Body size and nested traversal were unbounded. The receiver now bounds streamed bytes at 256 KiB, rejects oversized bodies with HTTP 413, and bounds JSON depth. Traversal is iterative.
- The CLI's first boundary patch did not cover huge valid JSON integers. Supervisor tests reproduced HTTP 500 for confidence/timestamp and a persisted position that broke `/api/targets`. Conversion overflow now becomes unknown/null.
- Original substring matching converted `not_detected`, `not_restricted`, `no_drone_detected`, and “not a drone” into positive alarms. Supervisor regression tests failed before the CLI's semantic fix.
- Coordinate metadata declared as metres must not be relabelled as a normalized frame. The projection rejects conflicting coordinate-system declarations.

The CLI's original focused suite produced **9 failures and 1 pass** before implementation. Supervisor negative-state tests produced **6 failures and 1 pass** before repair; the numeric follow-up produced **4 failures**. The supervisor independently ran the entire Python suite after the first implementation: **34 passed**, one dependency warning, **1.01s**, including the real localhost socket test. Python compilation and `git diff --check` also passed. Commit `4073eff` records this verified stage; subsequent review changes have separate evidence.

## API boundary

`GET /api/targets` returns `schema_version: 1`, a bounded `targets` array, and server response time `received_at`. Canonical targets include:

- `target_id`, `event_id`, source name, and `updated_at` from a validated source-reported timestamp. Missing or invalid source timestamps remain empty, with `timestamp_basis: receipt_time_only`; actual server receipt is stored separately as `ingested_at` and projected as `last_received_at`.
- `source_kind`: `WEBHOOK_EVENT` for unverified deliveries, `TEST_EVENT` for explicit test markers, or `SYNTHETIC_EVENT` for internally simulated/source-marked synthetic records. `SENSOR_EVENT` is reserved for a future verified producer; this unauthenticated receiver cannot substantiate that provenance.
- `status`: `TRACKED`, `UNKNOWN`, `POSSIBLE THREAT`, or `THREAT` from reported event state.
- `status_basis`: `reported_event` or `scenario_authored`.
- Nullable `confidence` and `position`; `velocity` and `heading` remain null because the current receiver has no calibrated movement contract.
- Human-readable `evidence`, `uncertainty`, and `alternative_interpretation`. A reported zone incursion is explicitly not validated evidence of hostile intent.

Only the recognized position form with finite unit-range `x`/`y` is projected as `normalized_frame`; conflicting coordinate-system metadata and ambiguous multiple positions remain null. No radar range, geographic position, speed, heading, or predicted path is invented. The primary frontend keeps sensor frame observations separate from the local synthetic schematic.

Targets with unambiguous explicit tracking identities are deduplicated within the same provenance and source; event IDs are used when identity is ambiguous. SQLite history and `GET /api/events` remain available for the preserved legacy frontend.

`/assets` serves only the assets directory, and `/legacy` serves only `legacy.html`. The repository root is not mounted as a static directory.

## Startup and test scripts

```bash
./scripts/demo.sh
./scripts/test.sh
```

The launcher creates `.venv` if missing and installs pinned Python requirements if runtime imports are unavailable. Initial setup requires internet; subsequent demo runs use local assets and need no Viso or remote API. Default host is loopback `127.0.0.1`, port 8000, with a separate local demo database `.local/demo.db`. Existing database paths can be supplied explicitly.

For a phone on the same trusted Wi-Fi, use `DRONEWATCH_HOST=0.0.0.0 ./scripts/demo.sh` and open the computer's LAN address. This does not make public hosting or raw sensor ingestion safe. `DRONEWATCH_PYTHON` can point at an existing Python environment; `DRONEWATCH_PORT` chooses a port.

`./scripts/test.sh --unit` runs Python tests/compilation and JavaScript unit tests. The default script also runs the complete Playwright browser suite. Node dependencies and browser binaries must first be installed as described in README.

## Remaining limits

- The prototype ingestion and legacy event API are unauthenticated. Raw stored payloads remain exposed through the legacy API for compatibility. Use loopback or an explicitly trusted demo network; production authentication, raw-field redaction, retention and rate limits remain separate work.
- The target API considers at most the latest 200 stored rows. It is an observation projection, not a multi-sensor track-fusion engine.
- No credential-backed Viso delivery, physical Android device, certified classification, real radar calibration, or deployment is claimed by these backend tests.

## Manager and Claude follow-up review

The manager rejected the first canonical projection's `SENSOR_EVENT` wording for unauthenticated posts and its use of fallback receipt timestamps as observation freshness. The second official Codex CLI run implements the response; its prompt and JSONL are `followup-task.txt` and `events-provenance.jsonl` in the same untracked run directory. Before that implementation the manager's provenance/freshness/Unicode suite failed 15 cases and passed the valid emoji case.

Claude Code's independent baseline report at commit `87a6875` supplied additional executable cases: `camera_id` hijacking event identity, `processing_time_ms` hijacking source age, `http_status` becoming a restricted-zone alert, negated/cleared states, and ambiguous multi-object observations. The supervisor converted these into `tests/test_claude_semantics.py`; six failed and three passed before the response. Codex read the tests and repaired the failing behaviors in its independently authored patch.

Two Claude proposals were deliberately not adopted:

- **Receipt-only freshness:** receiving an old observation now does not make that observation current. The selected design carries source and receipt timestamps separately. A source timestamp a year old remains a year old; malformed or missing source time is explicitly unverified. Tests exercise both paths.
- **Maximum drone confidence from mixed detections:** choosing the most confident drone from a list containing multiple objects would manufacture an association to a single target. Until a provider-specific object schema is validated, the canonical projection marks the observation ambiguous with unknown classification/confidence.

A further supervisor regression covers migrated records whose old `received_at` field was manufactured by the earlier fallback. Migration must not promote that timestamp into verified source time. The additive SQLite migration retains old rows and leaves their unknown receipt time null.

Independent full-suite result after the manager/Claude response: **61 passed**, one dependency deprecation warning, **1.18s**. No tests were skipped in this supervisor run. Python compilation and `git diff --check` passed. The official CLI's corresponding sandbox result was 60 passed/1 deselected solely for the local socket bind restriction.
