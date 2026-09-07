# V0.2 repository release candidate record

`V0.2 REPOSITORY RELEASE CANDIDATE — EXTERNAL VISO ACCEPTANCE PENDING`

Status date: 7 September 2026.

This document separates repository-local implementation from external provider
acceptance. It is not a V0.2 release note and does not authorize a push, merge,
account change, media upload, tunnel, or tag.

## Source identity

- Repository: `https://github.com/retinapeg/dronewatch`
- Verified V0.1 base: `31a32e1764572837ff43691b50aa3a15bc458714`
- Candidate branch: `codex/dronewatch-v0.2`
- Candidate commit: report with `git rev-parse HEAD` after the focused local
  commit. A commit cannot reliably embed its own SHA in its contents, so the
  release handoff is the authoritative candidate-SHA record.
- Protected frontend Git blob:
  `35af3f056e905b802669e3720a7362626426ff2a`
- Protected frontend SHA-256:
  `e1d9be772509789c925ebe30b62a41e1642d5d8f250afa5d1edf484571a0b293`

The release handoff must also give the actual worktree path, branch/upstream,
base/candidate SHAs, exact staged paths, and proof that `index.html` is absent
from the diff.

## Evidence status matrix

| Area | Status | Evidence boundary |
| --- | --- | --- |
| V0.1 baseline | Verified before candidate edits | 10 Python tests and 10 dashboard tests passed; exact commands/results remain in the implementation handoff. |
| Provider-neutral contract | Repository-local candidate | Strict Python model and checked-in JSON Schema; synthetic tests are not Viso evidence. |
| Migration/persistence | Repository-local candidate | Additive transactional migration, atomic delivery keys, conflict audit, retained legacy quarantine, and materialized track heads. |
| Receiver security | Repository-local candidate | Local bearer enforcement, streamed body limit, strict JSON, sanitization, and retention are locally testable; no public-deployment claim. |
| Replay runner | Repository-local candidate | Finite, manifest-checked atomic local copying and redacted run record; no Drive/Viso/webhook claim. |
| Halmstad fixture selection | Repository-local verified manifest inputs | Six selected source/label identities pinned to commit `442d0c6750708cc221636f7a1fd31cbd8cb0aeb8`, CC0, hashes/bytes recorded, media external. |
| Genuine Viso delivery | Not present | No redacted body/header evidence was found. |
| Viso adapter | Fail-closed | Disabled until a genuine account delivery establishes exact paths and semantics. |
| Viso inbound authentication | Not account-tested | Local receiver requires bearer; connector capability is unknown. Viso OAuth remains blank/external and is not evidence of webhook authentication. |
| Supervised end-to-end run | Not performed | No Google Drive → Viso Now → DroneWatch transport evidence or latency measurement exists. |
| V0.2 release/tag | Not authorized/not created | Requires every external gate, exact-commit CI, matching local/remote SHA, and explicit user approval. |

## Repository-local completion scope

The candidate is designed to provide:

- `dronewatch.event.v1` identity, timing, provenance, delivery-mode,
  classification, lifecycle, confidence, and optional frame-coordinate rules;
- server-owned internal observation ID and `received_at`;
- first/duplicate/conflict outcomes governed by a database unique key;
- deterministic scoped-track ordering and matching `EXITED` closure;
- history pagination independent of `open_count`;
- strict authenticated JSON reception with a 64 KiB default streamed cap;
- no complete raw-body retention or raw provider projection;
- 30-day/10,000-row canonical history and 7-day/1,000-row conflict defaults,
  without pruning delivery keys, current track heads, or legacy rows;
- finite replay from 1 through 20 copies, with manifest/hash checks, atomic
  no-clobber publication, no retries, cleanup, and a machine-readable record; and
- a checked-in CC0 six-clip selection manifest with source bytes outside Git.

This list describes the bounded implementation target. The final handoff must
attach exact command output/counts before claiming repository-local verification
complete.

## Clean-candidate verification record

Before the local commit, run and inspect all of the following from the candidate
worktree:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
node --test tests/dashboard.test.cjs
.venv/bin/python scripts/export_schemas.py --check
.venv/bin/python scripts/verify_replay_artifacts.py
.venv/bin/python scripts/verify_frontend.py
.venv/bin/python scripts/http_smoke.py
.venv/bin/python -m compileall -q .
.venv/bin/pip-audit -r requirements.txt
bash -n start-drive-copy.command
git diff --check
git status --short
git diff --name-only
git hash-object index.html
shasum -a 256 index.html
```

Also run a real local Uvicorn HTTP smoke test with a temporary database and a
non-secret test token. Inspect behavior and database state, not only exit codes:

1. health/config reports non-secret effective settings;
2. missing authentication is rejected without storage;
3. one canonical observation is accepted;
4. its exact retry is acknowledged without a second logical row;
5. a matching `EXITED` observation closes the track;
6. `open_count` is zero even with history limit one;
7. event output contains only the sanitized compatibility projection;
8. an oversized streamed request is rejected without storage; and
9. captured logs contain neither the token, complete body, nor database path.

The final handoff must record exact Python and Node test counts, schema/compile/
shell/diff results, dependency audit findings, all nine smoke observations,
frontend hashes, and the exact staged path set.

## External acceptance still required

The precise next user-assisted step is to follow
`VISO_ACCEPTANCE.md`: configure/inspect a non-sensitive Viso Now test output,
leave account/API OAuth blank, determine separately whether the output connector
can emit DroneWatch's bearer header, and provide a reviewed redacted request body
plus relevant non-secret header names and configuration date.

After that evidence exists, DroneWatch can implement the exact strict mapping
and run one explicitly authorized finite Halmstad scenario. Preserve its actual
result—even a miss, negative, unknown, or false positive—and label it
`REPLAYED_REAL` plus `NEAR_REAL_TIME_FILE_REPLAY`.

## Claim boundary

Repository-local tests and an atomic-copy run can demonstrate software behavior
under controlled local conditions. They do not demonstrate Google Drive sync,
Viso processing, a live feed, radar, detection accuracy, calibrated tracking,
general reliability, operational effectiveness, or certified defence use.
