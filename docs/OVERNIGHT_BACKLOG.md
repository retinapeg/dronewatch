# Overnight backlog

## Current state

Historical audit snapshot, 2026-10-04, before implementation sessions.
See **Overnight results** below for the final state; statements in this snapshot
about health, CI coverage and installed pins describe the initial audit only.

- Working coverage: FastAPI/SQLite incidents, seeded synthetic scenarios, Kalman
  tracking, lost-contact containment, camera cueing, preview APIs and browser
  helpers. No real sensor or Viso account was connected.
- Baseline: **241 Python tests passed, 1 failed (242 total; none skipped)**;
  **60 JavaScript tests passed**. The sole Python failure is the no-deletion
  guard blocking generated-fixture removal in `test_synthetic.py:308`, before
  the loader assertion; this is not an unrestricted green baseline. Compilation
  and dependency consistency checks passed. Python 3.11.5,
  Node 26.8.1; CI uses Node 24. Installed direct pins match `requirements.txt`;
  latest-version/security status and fresh installation remain unverified.
- The protected `/v2/webhook/viso` and preview status already disable ingestion
  without a secret. **The original `/webhook/viso` remains unauthenticated**,
  `/api/events` exposes raw payloads, `/health` is liveness-only and no outbound
  processing client exists. Legacy compatibility tests conflict with the
  requested strict original route. Idempotency and matching-event closure remain
  roadmap gaps.
- Intended vendor: **Viso Now by viso.ai**, confirmed by its
  [official product page](https://viso.ai/viso-now/) linking its
  [documentation](https://docs.now.viso.ai/). Its webhook/authentication/outbound
  contracts were not recovered from the documentation shell. Repository fixtures
  are local examples, not verified vendor deliveries.
- CI runs only 10 of the 60 JavaScript tests. Historical roadmap counts are
  stale. No tracked cache/database/bulk-data clutter was found; optional local
  removals are listed in [DECISIONS.md](DECISIONS.md#proposed-removals).

## Ordered sessions

Each unchecked item is one 30–60 minute session. Work in this order: preserve
regression coverage and hygiene, validate dependencies, establish evidence,
then improve the disconnected integration and its documentation. Tests use
fabricated fixtures and deterministic fakes; no credentials, real datasets,
paid APIs, deployment or Viso account calls are required. Keep `index.html`
byte-for-byte frozen. Append start/end entries and outcomes to the three logs.

- [x] **1. P0 — Close the JavaScript CI coverage gap (30 minutes; V0.1 gates).** Change the workflow to execute all four `tests/*.test.cjs` files, preserving Python, compilation and dependency-audit jobs. Add a small offline workflow contract check so newly added JavaScript test files cannot silently fall outside CI.
  Evidence (2026-10-04): changed `.github/workflows/ci.yml`, `tests/test_ci_workflow.py`, this checklist and appended `docs/BUILD_LOG.md`, `docs/DECISIONS.md`, `docs/ERROR_LOG.md`; `test_ci_runs_all_javascript_test_files`, `test_ci_retains_python_validation_gates` (3 cases), `test_ci_installs_requirements_and_audit_tool`, and existing `test_index_html_is_byte_identical_to_the_committed_version` pass. All 60 JavaScript tests pass; full Python suite: 246 passed, 1 existing deletion-policy failure, 0 skipped (details in ERROR_LOG.md); compilation and pip consistency pass.
  Verification: `node --test tests/*.test.cjs` passes all 60 existing tests; a new workflow test verifies the all-files invocation and retained gates; the existing `test_index_html_is_byte_identical_to_the_committed_version` passes.

- [x] **2. P0 — Make artifact exclusions testable (30 minutes; dataset and frontend rules; after 1).** Extend `.gitignore` only for missing local SQLite forms/sidecars and any demonstrated generated artifacts. Add a metadata-only tracked-artifact guard. Keep fixtures, manifests, result summaries and runtime images eligible for Git. Append any newly discovered removal candidates and reasons to `DECISIONS.md`; remove nothing.
  Evidence (2026-10-04): changed `.gitignore`, `tests/test_repository_hygiene.py`, this checklist; appended `docs/DECISIONS.md`, `docs/ERROR_LOG.md`, `docs/BUILD_LOG.md`. New tests `test_local_sqlite_files_and_sidecars_are_ignored` (12 cases), `test_caches_and_generated_data_are_ignored`, `test_fixtures_manifests_summaries_and_runtime_images_remain_includable`, `test_tracked_artifact_policy_detects_prohibited_paths` (28 cases), and `test_git_tracks_no_prohibited_artifacts` all pass (43 total). Full Python suite: 289 passed, 1 existing no-deletion-policy failure, 0 skipped; all 60 JavaScript tests and existing frozen-index check pass. No files removed; one additional optional cache removal is documented.
  Verification: a new hygiene test uses `git check-ignore --no-index` on representative `*.sqlite`, `*.sqlite3-wal`, `*.sqlite3-shm`, caches and generated data, confirms fixtures/manifests remain includable, and verifies `git ls-files` contains no prohibited artifacts.

- [x] **3. P0 — Verify compatible dependency pins in an isolated environment (45–60 minutes; V0.1 reproducibility; after 2).** Review official release notes for the existing six direct dependencies, retain current compatible pins or update only justified ones, and install into a new ignored repository-local environment with `pip --no-cache-dir`. Preserve the existing `.venv`. Record exact versions and whether each pin changed; keep the CI audit gate. Do not claim a vulnerability scan passed if it was not run.
  Evidence (2026-10-04): changed `requirements.txt` (Starlette 1.6.0 -> 1.7.0 only), `tests/test_dependency_compatibility.py`, `docs/DEPENDENCY_REVIEW.md`, `docs/results/dependency_review_20261004.json`, this checklist; appended all three logs. Fresh ignored `.pytest_cache/item3-dependencies/.venv` installed with pip --no-cache-dir; original `.venv` preserved. `test_testclient_import_lifespan_and_request_without_deprecations` passes on 1.7.0 and detects the old 1.6.0 warning in a negative control; existing `test_ci_retains_python_validation_gates`, `test_health_endpoint`, `test_index_html_is_byte_identical_to_the_committed_version` and all other regressions pass except the documented deletion-policy test. Full Python: 290 passed, 1 known policy failure, 0 skipped/errors; JavaScript: 60 passed; pip consistency/compilation/whitespace pass. Official six-pin review and exact resolved versions recorded; no vulnerability scan or hosted CI run claimed.
  Verification: the new environment's `python -m pip --no-cache-dir check`, full Python suite and all JavaScript tests run, with pip/JavaScript/compilation checks passing; report the documented deletion-guard failure separately and require no additional failures rather than skipping tests or claiming the full suite is green.

- [x] **4. P0 — Establish a dated Viso contract evidence matrix (45 minutes; V0.2 strict-adapter gate; after 3).** Start `docs/VISO_INTEGRATION.md` with official source URLs, access date and verified/unresolved entries for payload shape, webhook authentication, file/video submission and processing-result retrieval. Record unresolved contracts explicitly if the documentation remains inaccessible. Add a tiny manifest identifying fabricated/redacted local fixtures as `SYNTHETIC`; never describe them as captured vendor deliveries or invent endpoint fields.
  Evidence (2026-10-04): added `docs/VISO_INTEGRATION.md`, `tests/fixtures/viso/{manifest,identified_incident,incident_url,narrative_negative,unknown_payload}.json`, `tests/test_viso_evidence.py`; changed this checklist and appended all three logs. `test_manifest_identifies_only_fabricated_synthetic_fixtures`, `test_fixture_hash_origin_and_safe_identifiers` (4 cases), `test_contract_evidence_is_dated_official_and_has_no_unverified_mapping`, `test_synthetic_compatibility_fixtures_never_infer_detection` (4 cases), and `test_manifest_fixtures_through_protected_webhook` (4 cases) pass. Existing `test_narrative_text_never_produces_a_positive_result`, `test_an_unknown_payload_is_quarantined_not_turned_into_a_detection`, and `test_webhook_does_not_infer_detection_from_narrative_or_stringify_source` pass. Vendor identity confirmed from official links; four wire contracts remain explicitly unresolved with no claimed supported mapping. Full Python: original .venv 303 passed/2 inherited failures; pinned item-3 environment 304 passed/1 existing deletion-policy failure; 0 skipped/errors in either. All 60 JavaScript tests and frozen-index check pass. No runtime change, deletion or vendor API call.
  Verification: a new offline manifest test checks fixture hashes, synthetic origin, required evidence/status fields and absence of real account/media identifiers; existing narrative-negative and unknown-payload tests continue to pass. Unresolved vendor fields must have no claimed supported mapping.

- [x] **5. P0 — Separate configuration from proof of connection (45 minutes; V0.2 ingestion and V0.5 honest status; after 4).** Introduce one small configuration reader distinguishing outbound `VISO_API_KEY` from the inbound webhook secret, both absent by default. Retain the documented legacy secret as an explicit compatibility alias if introducing `VISO_WEBHOOK_SECRET`; reject conflicting non-empty aliases. Add a provider summary to `/health` that says `Viso: not configured` with no credentials and distinguishes configured-but-unverified from a received delivery. Keep existing liveness keys and preview-state contracts.
  Evidence (2026-10-04): added `dronewatch/config.py`, `tests/test_viso_config.py`; changed `main.py`, `dronewatch/api/preview.py`, `dronewatch/api/camera.py`, `docs/VISO_INTEGRATION.md`, this checklist and appended all three logs. New tests `test_configuration_and_health_never_claim_connection` (13 cases), `test_inbound_aliases_preserve_authentication_transports` (6), `test_conflicting_aliases_reject_both_secrets_without_writes` (3), `test_receipt_is_local_evidence_not_vendor_verification` (2), `test_bad_auth_malformed_json_and_legacy_route_do_not_verify_connection`, `test_new_credentials_are_redacted_from_camera_evidence`, and `test_synthetic_preview_and_process_reset_preserve_honest_status` pass (27 total). Full Python: original .venv 330 passed/2 inherited failures; pinned environment 331 passed/1 inherited deletion-policy failure; no skips/errors. All 60 JavaScript tests, compilation, pip consistency and existing frozen-index regression pass. No connection, vendor-contract, or unrestricted green-suite claim.
  Verification: new parametrised API tests cover unset, empty, whitespace-only, inbound-only, outbound-only and conflicting settings; secrets never appear in response/log output and setting a key alone never reports a successful connection.

- [ ] **6. P1 — Add a disconnected outbound processing interface (45 minutes; recorded-file boundary; after 5).** Define a small file/video processing client interface and deterministic fake using project-owned request/result types. The stub refuses operation without an API key before reading media or invoking transport. With a dummy key but no verified vendor API contract, return an explicit unsupported/unverified-contract error. Do not guess a base URL, upload field, authentication header or polling route; do not add automatic network discovery.
  Verification: new unit tests inject a transport that fails on any call, prove zero calls for missing configuration and unresolved contracts, and show the deterministic fake produces identical results and explicit failures for fixed inputs without real media.

- [ ] **7. P1 — Tighten the existing metadata recogniser without claiming vendor compliance (45–60 minutes; V0.2 strictness; after 6).** Use the fixture manifest to test the local compatibility adapter in `dronewatch/ingest/viso.py`. Require scalar identifiers and exact-host HTTPS incident URLs, reject deceptive/credential-bearing URLs and structured or conflicting metadata, and preserve `UNKNOWN` classification and absent positions. Treat these as local compatibility rules; an official schema remains unverified until item 4 has evidence. Keep the outbound stub disabled.
  Verification: new adapter cases cover hostile host suffixes, non-HTTPS URLs, user-info URLs, nested identifier values, conflicts, missing metadata and prose-only drone mentions; recognised existing fixtures still pass without fabricated coordinates, confidence or detections.

- [ ] **8. P1 — Complete malformed-input coverage on the protected ingress (45–60 minutes; V0.2 request boundary; after 7).** Harden `/v2/webhook/viso` for invalid UTF-8, excessive JSON nesting and streamed oversized bodies without trusting Content-Length. Ensure rejected deliveries do not write incidents or become mapped camera evidence. Reuse the existing secret check and adapter; leave the incompatible original-route migration explicitly blocked rather than silently changing its tests.
  Verification: new in-process ASGI tests exercise invalid bytes, deeply nested JSON, exact body limit, limit-plus-one and oversized chunked bodies without Content-Length; assert bounded 4xx responses, unchanged incident/mapped counts and no raw-body/secret leakage, alongside existing authentication/quarantine tests.

- [ ] **9. P1 — Add explicit data-origin labels to synthetic API observations (45 minutes; ROADMAP non-negotiable labels; after 8).** Add a stable `data_mode: SYNTHETIC` label to each generated observation and track projection, keeping the existing modality and local-coordinate fields. Define the allowed project modes `SYNTHETIC`, `REPLAYED_REAL` and `LIVE` without importing hidden ground truth. Do not infer real/live provenance from a Viso-looking payload, receipt time or configured secret; undocumented external origin remains unknown and outside accepted labelled observations.
  Verification: new response tests require `SYNTHETIC` on every synthetic observation/track, reject unsupported modes at the new validation boundary and prove synthetic Viso fakes never acquire `LIVE` or `REPLAYED_REAL`; existing ground-truth exclusion, deterministic replay and frozen-dashboard tests remain unchanged and pass.

- [ ] **10. P1 — Finish the disconnected integration runbook and README alignment (45 minutes; V0.1 truthfulness and V0.2 handoff; after 9).** Update the README and `docs/VISO_INTEGRATION.md` to match implemented settings, endpoint behaviour and all-suite CI commands. State exactly what remains to verify when a key arrives, distinguish inbound and outbound setup, and explain that a key cannot supply a missing vendor contract. Scope recorded-file claims to this integration; retain synthetic-only evidence and prototype limitations. Do not overwrite historical roadmap milestones or claim the legacy-route release gate is resolved.
  Verification: a new offline runbook smoke test compares documented setting names and endpoint paths with the configuration/OpenAPI surface, starts a test app with all Viso settings unset, checks the advertised status and stub refusal, and confirms synthetic preview plus all existing regression suites still work.

## Release gates outside these unattended sessions

The guarded baseline also cannot be described as fully green while the existing
ground-truth test requires deletion. Preserve that test and report the restriction;
do not bypass it or weaken its assertion. Full-suite verification throughout this
backlog must distinguish this documented environment restriction from new failures.

The overall request is **not complete** until the original webhook's compatibility
conflict has a documented resolution, official payload/authentication/outbound
contracts are evidenced, and any future real delivery has its own authorised,
redacted record. No session above requires those credentials or fabricates that
record. Idempotent ingestion and matching-track `EXITED` closure should follow
once the canonical event key/lifecycle contract is established. Nothing here
unfreezes `index.html`, adds weapon-control interfaces or establishes measured
real-world detection performance.


## Overnight results

Wrap-up dated **2026-10-04**. Items **1–5** are checked; **6–10 remain unchecked**.
The overall Viso integration goal is incomplete. No real sensor/account was
connected, no external processing API was called, and no files were deleted.

| Ticked item | Delivered change | Evidence |
| --- | --- | --- |
| 1 — CI coverage | CI runs every JavaScript test file and retains Python, compilation and audit gates. | `.github/workflows/ci.yml`; `tests/test_ci_workflow.py` (5 cases); final JavaScript suite 60/60. Hosted CI was not run. |
| 2 — Artifact exclusions | SQLite/sidecar exclusions and metadata-only tracked-artifact checks; owner-reviewed removal proposals, no removals. | `.gitignore`; `tests/test_repository_hygiene.py` (43 cases); [Proposed removals](DECISIONS.md#proposed-removals). No prohibited tracked artifacts found. |
| 3 — Dependency review | Starlette 1.6.0 → 1.7.0; other five direct pins retained with reasons. Fresh isolated installation and strict TestClient regression. | [Review](DEPENDENCY_REVIEW.md), [resolved inventory](results/dependency_review_20261004.json), `tests/test_dependency_compatibility.py`. All six pins match the isolated environment; original `.venv` remains stale. No vulnerability audit claimed. |
| 4 — Viso evidence | Official identity recorded as viso.ai / Viso Now; four unresolved wire-contract areas, manifest and four fabricated `SYNTHETIC` fixtures. | [Integration record](VISO_INTEGRATION.md); `tests/test_viso_evidence.py` (14 cases), fixture hashes and protected-webhook regressions. Fixtures are not real redacted deliveries. |
| 5 — Configuration/status | Separate inbound/outbound settings, fail-closed alias conflicts, honest `/health` provider state and credential-safe camera/preview consumers. | `dronewatch/config.py`, `main.py`, preview/camera API changes; `tests/test_viso_config.py` (27 cases). No-key message is `Viso: not configured`; `connection_verified` always false. |

### Blocked or left

- Official payload, webhook authentication, file/video submission and result
  retrieval contracts remain unresolved after the earlier official-docs review.
  A key alone cannot resolve these gaps or prove a working integration.
- No outbound processing interface/stub/fake exists yet (item 6). Metadata
  strictness, malformed-input boundary coverage and per-observation origin
  labels remain items 7–9.
- The original `POST /webhook/viso` remains unauthenticated; `/api/events` returns
  raw payloads. A strict original-route migration conflicts with existing
  compatibility assertions and needs an explicit release decision. No public
  deployment readiness is claimed.
- Item 10 remains unchecked: this wrap-up aligns README with implemented
  behaviour, but the final stub/runbook smoke test and full integration setup
  instructions depend on unfinished work.
- The original environment has Starlette 1.6.0, while requirements pin 1.7.0.
  A generated-fixture deletion in `test_synthetic.py:308` is forbidden by this
  unattended run. Neither full Python suite is green; see final results below.
- Hosted CI, vulnerability auditing, real Viso delivery, idempotent ingestion and
  matching-event closure remain unverified or unfinished. Historical roadmap
  counts and source-research claims must be read with the dated integration record.

### Recommended next three items

1. **Restore a verifiable green baseline under an appropriate execution policy.**
   Use the already-installed compatible environment (or update the normal
   environment when allowed), then run the unchanged full suite in an owner
   session that permits its generated-fixture cleanup. Do not weaken assertions
   or silently bypass the deletion guard in this run. Complete the retained CI
   and vulnerability-audit gates before treating the branch as release-ready.
2. **Item 6: implement the disconnected outbound interface and deterministic fake.**
   Refuse missing credentials before media access; with a dummy key, refuse an
   unresolved contract before transport. Assert zero network calls. No invented
   vendor URL, field or authentication format.
3. **Item 7: tighten the local metadata recogniser.** Validate scalar identifiers
   and exact-host HTTPS URLs, reject ambiguous/hostile metadata, preserve UNKNOWN
   and non-spatial evidence. Vendor compliance remains blocked on official
   account-applicable contracts and an authorised redacted delivery.

The recommended sequence prioritizes the failed verification gate, then resumes
ordered items 6 and 7. Items 8–10 and the original-route migration remain required
follow-on work. Review details and complete commands are in
[the handoff](OVERNIGHT_HANDOFF_2026-10-04.md).


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
