# Overnight handoff — 4 October 2026

Branch: `codex/overnight-1004`  
Base HEAD: `efd82372466cea4fe3b3390a06cb22f2a1057a5e`  
State: uncommitted working tree; no commit, push, deployment or branch change.

## Outcome

Backlog items 1–5 are implemented with offline evidence. The overall integration
is **incomplete**, and the full Python suite is **not green** under this run's
constraints. Viso is not connected. There is no outbound processing stub yet,
and the original webhook remains unauthenticated. All 60 JavaScript tests pass.
No real detection, live coverage, production readiness or vendor-compliant
payload/authentication contract is established.

Earlier sessions broadened JavaScript CI coverage, added artifact exclusion
checks, pinned Starlette 1.7.0 in a separately installed environment, recorded
Viso contract evidence and fabricated fixtures, and added separate Viso inbound
and outbound settings with honest status reporting. This wrap-up changes only
README, backlog and handoff documentation, appends logs and retains ignored
verification evidence. No runtime feature or test assertion changed here.

## Review first

1. Read the failed Python results below before accepting any green-suite claim.
   The original `.venv` does not match the selected Starlette pin; the compatible
   environment isolates that problem but still encounters forbidden fixture
   deletion. Neither failure was skipped, xfailed or weakened.
2. Review `dronewatch/config.py`, `/health` in `main.py`, and the preview/camera
   changes with `tests/test_viso_config.py`. No key means `Viso: not configured`;
   a key or authenticated delivery does not verify the vendor connection.
3. Read [VISO_INTEGRATION.md](VISO_INTEGRATION.md) before enabling ingestion.
   Only `/v2/webhook/viso` is protected. `/webhook/viso` remains unauthenticated,
   `/api/events` exposes raw payloads, and four vendor wire contracts remain
   unresolved. The fixtures are explicitly fabricated `SYNTHETIC` examples,
   not captured/redacted vendor traffic.
4. Inspect requirements/CI and the dependency review, then the proposed removals
   in [DECISIONS.md](DECISIONS.md#proposed-removals). No file was removed; no
   prohibited tracked artifact was found. Hosted CI and vulnerability auditing
   remain unrun locally.

## Complete review file list

This list includes prior overnight changes already present at wrap-up start.
`STATE.md` is pre-existing runner bookkeeping, not authored by this wrap-up.
Ignored caches, environments and report artifacts are excluded from this list.

- `.github/workflows/ci.yml`
- `.gitignore`
- `README.md`
- `STATE.md`
- `docs/BUILD_LOG.md`
- `docs/DECISIONS.md`
- `docs/DEPENDENCY_REVIEW.md`
- `docs/ERROR_LOG.md`
- `docs/OVERNIGHT_BACKLOG.md`
- `docs/OVERNIGHT_HANDOFF_2026-10-04.md`
- `docs/VISO_INTEGRATION.md`
- `docs/results/dependency_review_20261004.json`
- `dronewatch/api/camera.py`
- `dronewatch/api/preview.py`
- `dronewatch/config.py`
- `main.py`
- `requirements.txt`
- `tests/fixtures/viso/identified_incident.json`
- `tests/fixtures/viso/incident_url.json`
- `tests/fixtures/viso/manifest.json`
- `tests/fixtures/viso/narrative_negative.json`
- `tests/fixtures/viso/unknown_payload.json`
- `tests/test_ci_workflow.py`
- `tests/test_dependency_compatibility.py`
- `tests/test_repository_hygiene.py`
- `tests/test_viso_config.py`
- `tests/test_viso_evidence.py`

## Validation commands and environment

Python 3.11.5; macOS arm64; Node v26.8.1. CI targets Ubuntu, Python 3.11 and
Node 24, so local results do not establish hosted CI success.

Commands actually used for full Python discovery:

```sh
.venv/bin/python -B .pytest_cache/wrapup-runner.py
.pytest_cache/item3-dependencies/.venv/bin/python -B .pytest_cache/wrapup-runner.py
```

The inspected retained runner invokes `pytest.main` with `-q --capture=sys`, a
new repository-local `--basetemp`, `tmp_path_retention_policy=all`, and log/JUnit
paths. It clears inherited Viso/DroneWatch settings without printing their values,
disables plugin autoload and bytecode writes, and installs an audit hook rejecting
file deletion and filesystem writes outside the repository. It runs full discovery
without selectors, skips, xfails or changed assertions. It is retained as ignored
local evidence, not an application feature. Its fresh scratch directories and
JUnit reports are listed below. Subprocesses inherit local scratch/bytecode
settings; the strict dependency regression intentionally starts a fresh interpreter.

Other commands:

```sh
node --test tests/*.test.cjs > .pytest_cache/wrapup-javascript-results.txt
.venv/bin/python -B -m pip --isolated --no-cache-dir --disable-pip-version-check check
.pytest_cache/item3-dependencies/.venv/bin/python -B -m pip --isolated --no-cache-dir --disable-pip-version-check check
git diff --check
```

An inline `.venv/bin/python -B` check compiled 54 sources from `main.py`,
`demo_feed.py`, `dronewatch/**/*.py` and `tests/**/*.py` in memory, avoiding cleanup
or bytecode artifacts. It compared `index.html` bytes with `git show HEAD:index.html`
and recorded versions/hash in `.pytest_cache/wrapup-checks.json`. A separate
metadata check verified all six direct pins match the item-3 environment.

For an ordinary owner/CI session permitting generated-fixture cleanup, the
repository's standard full commands remain `python -m pytest -q` and
`node --test tests/*.test.cjs`, after installing `requirements.txt` in that
environment. Do not use an unguarded test invocation in this no-deletion run.
`pip check` checks installed dependency constraints; it is not a vulnerability
audit or a comparison against the requirements file.

## Final wrap-up results

Measured on 2026-10-04; both Python runs collected **332 tests**, with **zero
skips/errors** and exit code 1. Counts below are final wrap-up measurements,
not copied from earlier sessions.

| Check | Result | Retained evidence |
| --- | --- | --- |
| Full Python, original `.venv` / Starlette 1.6.0 | **330 passed, 2 failed**, 1 warning, 117.36 s | `.pytest_cache/wrapup-20261004T115019247415Z/python-results.xml` |
| Full Python, compatible item-3 environment / Starlette 1.7.0 | **331 passed, 1 failed**, no warnings, 117.71 s | `.pytest_cache/wrapup-20261004T115019247109Z/python-results.xml` |
| JavaScript, all four files | **60 passed**, 0 failed/skipped/cancelled, 137.38 ms | `.pytest_cache/wrapup-javascript-results.txt` |
| Dependency consistency | Both environments pass `pip check`; only item-3 matches all six requirements pins | Version check and `.pytest_cache/wrapup-checks.json` |
| Source compilation | **54 files passed**, compiled in memory | `.pytest_cache/wrapup-checks.json` |
| Frozen frontend | Byte-identical to HEAD | `.pytest_cache/wrapup-checks.json`; SHA-256 above/in handoff |
| Documentation and whitespace | Local link targets exist; `git diff --check` passed | README/backlog/handoff path checks |

The original environment fails
`test_testclient_import_lifespan_and_request_without_deprecations` because
Starlette 1.6.0 imports the deprecated AnyIO `BlockingPortal` alias. That test
passes in the compatible environment. Both environments fail
`test_observations_can_be_loaded_without_touching_ground_truth` because the
no-deletion guard rejects generated-fixture unlinking before its loader assertion.
There are no other failures. All new CI, hygiene, Viso evidence and configuration
cases pass. Neither full Python result is green. No test was removed, weakened,
skipped or xfailed. JUnit counts were independently parsed and checked; summary:
`.pytest_cache/wrapup-python-summary.json`.

Reports, logs, runner and generated test fixtures remain in ignored local scratch
for owner review; they are not committed evidence artifacts. No deletion was used
for cleanup. Hosted CI and vulnerability auditing remain unverified.

## Known issues and remaining work

- Original `.venv`: Starlette 1.6.0 remains installed, while requirements and
  `.pytest_cache/item3-dependencies/.venv` use 1.7.0. It was not upgraded through
  a deleting uninstall. Other direct pins are FastAPI 0.141.1, Uvicorn 0.52.4,
  pytest 9.1.1, Pydantic 2.13.5 and HTTPX2 2.12.0. See
  [DEPENDENCY_REVIEW.md](DEPENDENCY_REVIEW.md) for the dated compatibility review;
  this is not a claim that all packages are the newest or security-audited.
- `test_observations_can_be_loaded_without_touching_ground_truth` explicitly
  unlinks its generated ground-truth fixture at `tests/test_synthetic.py:308`.
  The audit guard rejects this before the loader assertion. Preserve the test;
  rerun under an owner execution policy allowing fixture cleanup. It remains a
  real failed test result here, not proof of a loader defect or of success.
- Viso Now by viso.ai is the intended product. The earlier official-docs review
  could recover identity and page metadata, but not implementable webhook,
  authentication, submission or retrieval contracts. This wrap-up made no network
  calls and does not claim new documentation verification.
- Backlog items 6–10 remain unfinished: outbound stub/fake, stricter recogniser,
  malformed-input coverage, per-observation origin labels and final runbook smoke
  test. README alignment here does not complete item 10's dependent requirements.
- The original webhook migration still conflicts with legacy compatibility tests.
  Idempotency, matching-event closure and public-deployment gates remain open.
  No real-media upload, real Viso receipt or source integration was performed.
- Hosted CI and vulnerability auditing were not executed. CI retains its audit
  gate; allowed network access here was restricted to documentation/installations.
  Historical roadmap numbers are milestone records, not current test counts.

Next three priorities: restore a demonstrably green baseline under an appropriate
execution policy; implement backlog item 6's refusing outbound interface/fake;
then item 7's strict local metadata validation. Details, evidence and all remaining
checkboxes are in [OVERNIGHT_BACKLOG.md](OVERNIGHT_BACKLOG.md#overnight-results).

## Preserved boundaries

`index.html` matches HEAD byte-for-byte; SHA-256:
`e1d9be772509789c925ebe30b62a41e1642d5d8f250afa5d1edf484571a0b293`.
No dataset was added to Git. No secrets, personal data, account calls, paid API
calls, publication, deletion or prohibited Git mutation occurred. Local synthetic
fixtures cannot establish `LIVE` or `REPLAYED_REAL` provenance. All changes remain
available for owner review.
