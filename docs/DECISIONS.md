# Decisions

## 2026-10-04T10:50:14+00:00 — Audit-only scope

Context: the overarching request describes integration and cleanup, but THIS STEP authorizes an audit and backlog with no feature code. ROADMAP.md supplies evidence/provenance rules and freezes index.html; its release/push process conflicts with the explicit prohibition on Git mutations.

Decision: inspect and test the existing implementation, consult only public vendor documentation, and append audit logs plus a testable backlog. Defer integration, dependency changes, ignore-rule edits and README corrections to future sessions; do not commit, push or change branches.

Alternatives considered: implement the overarching integration immediately; follow the historical release checklist. Both exceed this step or violate explicit hard rules.

Consequences: existing weaknesses remain documented rather than repaired; tests must use local scratch paths and no credentials. Preserve all existing source, tests and index.html bytes.

## 2026-10-04T10:54:07+00:00 — Preserve contract evidence and expose migration blockers

Context: tests/test_main.py explicitly expects unauthenticated, empty and malformed POST /webhook/viso requests to return 200 and store an incident. tests/test_preview_api.py::test_legacy_webhook_keeps_its_v1_behaviour also pins that contract; the V0.2 roadmap M3 requires compatibility. The requested future strict, disabled-by-default legacy endpoint contradicts those requirements.

Decision: leave both routes unchanged in this audit. The backlog may improve configuration, offline interfaces, the protected /v2 route and contract documentation; changing the legacy acceptance contract is a separate unresolved release gate, not an unattended-ready checklist item.

Alternatives considered: silently repoint old tests, special-case tests, or claim the protected /v2 route secures /webhook/viso. Each would hide the actual compatibility or security issue.

Consequences: the overall Viso integration is not complete and the legacy application remains local-only; no production-readiness claim is justified. Existing fixtures demonstrate local compatibility only, not an official vendor schema or real delivery.

## 2026-10-04T10:55:01+00:00 — Vendor evidence boundary

Context: the [official product page](https://viso.ai/viso-now/) identifies Viso Now and links [its documentation](https://docs.now.viso.ai/). It now advertises camera connectivity as well as files. The public documentation sitemap includes webhook-api, custom-output-messages, media-processing-model and camera-connectors, but the fetched article HTML supplies only a JavaScript-rendered shell. No authoritative payload, signing/header contract or outbound file/video endpoint specification was recovered in this audit.

Decision: identify the intended vendor as viso.ai and product as Viso Now; do not adopt the owner's spelling "visnow.ai" as an API host. Distinguish the repository's recorded-file-only integration from product-wide capability claims. Record unresolved wire contracts and keep future outbound transport disabled until verified. Existing appId/incidentId-style fixtures are local examples, not proof of an official schema.

Alternatives considered: reuse a similarly named vendor's API, infer endpoints from an application backend, or treat marketing claims as an API specification. None establishes an authorized documented integration contract.

Consequences: no key/header/base URL or undocumented payload field is invented. A future API key by itself is not enough to establish compatibility; official contract evidence remains a release gate. Documentation review makes no external service call and uploads no media.

## 2026-10-04T10:55:01+00:00 — Non-destructive hygiene review

Context: git ls-files contains no Python bytecode, local SQLite databases, MP4s or bulk datasets. Existing ignore rules already cover .venv, Python caches, *.db, *.db-*, *.sqlite3, data/generated and data/viso_synthetic. Potential gaps include *.sqlite and SQLite WAL/SHM sidecars. Committed docs/results summaries, UI images and data/synthetic/README.md have documented purposes and are not demonstrated clutter.

Decision: propose local cleanup only, make no removals or ignore-rule changes in this audit, and retain reproducible evidence and runtime assets. Future hygiene work should test both exclusion of local artifacts and inclusion of fixtures/manifests.

Alternatives considered: remove all results/data paths or blindly ignore every JSON/image. Those would remove evidence or hide legitimate fixtures.

Consequences: no tracked removal is proposed. All paths below remain for owner review; presence was checked by filename only, without opening local databases or data files.

## Proposed removals

Recorded 2026-10-04T10:55:01+00:00. These are optional local removals, not commands executed by this run. None of the following paths is tracked in Git.

| Path | Reason and review condition |
| --- | --- |
| `.DS_Store` | Machine-local Finder metadata; already ignored. |
| `dronewatch.db` | Local runtime SQLite state; already ignored. Owner must decide whether its history is still needed; contents were not inspected. |
| `__pycache__/` | Reproducible root-module bytecode; already ignored. |
| `dronewatch/__pycache__/` | Reproducible package bytecode; already ignored. |
| `dronewatch/api/__pycache__/` | Reproducible API bytecode; already ignored. |
| `dronewatch/domain/__pycache__/` | Reproducible domain bytecode; already ignored. |
| `dronewatch/ingest/__pycache__/` | Reproducible adapter bytecode; already ignored. |
| `dronewatch/synthetic/__pycache__/` | Reproducible generator bytecode; already ignored. |
| `dronewatch/tracks/__pycache__/` | Reproducible tracker bytecode; already ignored. |
| `.pytest_cache/` | Ignored local test cache and retained audit scratch. Preserve audit results until reviewed; includes the failed tempfile probe moved from `oennyynz` without deleting it. |

`data/viso_synthetic/` is present and ignored, but its contents, provenance and continued usefulness were not inspected. No removal is proposed on filename alone. No evidence establishes that tracked artifacts are stale. System temporary directories are outside this audit's permitted cleanup scope.

## 2026-10-04T11:01:59+00:00 — Preserve tests while enforcing audit filesystem constraints

Context: `test_observations_can_be_loaded_without_touching_ground_truth` explicitly unlinks its generated ground-truth file. The run prohibits file deletion and test weakening. Ordinary pytest file-descriptor capture also creates anonymous temporary files using unlink. A complete unmodified test invocation therefore has operations incompatible with this audit's filesystem policy.

Decision: run every test with original assertions, sys capture, explicitly assigned repository-local tempfile storage, retained pytest artifacts and a Python audit hook rejecting file removal. Report any resulting restriction-induced test failure separately from an application regression. Do not patch the test, replace unlink with a fake success, skip it or claim an unrestricted green baseline.

Alternatives considered: ordinary pytest with default temporary paths; deselecting the deletion-dependent test; runtime monkeypatching its filesystem action. These either violate the filesystem boundary or change the evidence being measured.

Consequences: the report can contain a policy-blocked test even if the underlying loader is correct. Initial harness setup failures and possible out-of-repository tempfile probes are recorded in ERROR_LOG.md; those attempts are not represented as successful isolation. Later runs explicitly set tempfile.tempdir before starting pytest and keep the complete test selection.


## 2026-10-04T11:05:36+00:00 — Automatically include JavaScript suites in CI

Context: CI currently invokes only tests/dashboard.test.cjs, leaving camera, diagnostics and operator regression suites outside the gate. Item 1 requires future root-level tests/*.test.cjs files to join automatically.

Decision: use the shell-expanded node --test tests/*.test.cjs invocation and add Python offline contract tests for the active workflow run steps, retaining the Python suite, compilation and dependency-audit commands and dependency installation. Use standard-library text inspection of the existing simple workflow layout without adding a YAML dependency.

Alternatives considered: enumerate the four current filenames (future suites could be omitted), use unconstrained recursive discovery (broader than the requested test location), or add a YAML parser dependency for a small static contract.

Consequences: every matching test file is automatically selected by CI; the contract runs with the existing Python suite and requires an explicit update if the workflow is reorganised. Existing tests and frozen dashboard remain unchanged. Full-suite verification uses the previously documented repository-local/no-deletion harness; the known deletion conflict is not bypassed or treated as a green run.


## 2026-10-04T11:14:54+00:00 — Item 2: explicit local-artifact boundary

Context: existing rules exclude Python caches, local environments, *.db / *.db-*, *.sqlite3 and designated generated-data directories. The missing SQLite forms are *.sqlite and WAL/SHM/rollback-journal sidecars for .sqlite and .sqlite3. Filename-only inspection found no prohibited tracked artifacts; tests/__pycache__/ is an additional local cleanup candidate.

Decision: add exactly those seven missing SQLite patterns. Add tests/test_repository_hygiene.py using NUL-delimited git check-ignore --no-index and git ls-files. Use an independent filename classifier to reject tracked local caches/environments, bytecode/logs/Finder metadata, SQLite files and designated generated-data paths, including force-added artifacts. Disable user-wide Git excludes in checks. Tests exercise prohibited names even when the real index is clean, and positively protect fixtures, manifests, licences/checksums, result summaries, runtime images and index.html from broad exclusions. No artifact contents are inspected.

Alternatives considered: blanket data/JSON/media ignores (would hide legitimate evidence/assets); relying only on ignore rules (does not catch tracked/force-added artifacts); opening files to guess dataset provenance (unnecessary and cannot prove provenance).

Consequences: existing generated-data exclusions remain unchanged; put fixtures/manifests outside designated bulk-output paths, e.g. tests/fixtures or data/manifests. This metadata guard checks known artifact locations and suffixes, not the provenance of arbitrary files. Tests run in the existing Python CI gate with no new dependency. Nothing is removed, and no additional scope/dependency/vendor change is included.

### Proposed removals — 2026-10-04T11:14:54+00:00 additions

| Path | Reason and review condition |
| --- | --- |
| `tests/__pycache__/` | Newly observed reproducible Python test bytecode; untracked and already ignored. Owner may remove after review. No files were opened or removed. |

Earlier candidates under “Proposed removals” remain unchanged. Retain `.pytest_cache/` verification evidence until reviewed; no tracked artifact has been established as clutter.


## 2026-10-04T11:20:35+00:00 — Item 3: targeted compatibility update and retained installation evidence

Context: Starlette 1.6.0 emits an AnyIO BlockingPortal deprecation in the current suite. Official Starlette 1.7.0 notes explicitly fix deprecated imports for AnyIO 4.15. FastAPI 0.141.1 metadata accepts starlette>=0.46.0. The six direct pins need fresh installation evidence while .venv must remain intact and deletion is forbidden.

Decision: update only Starlette to 1.7.0, subject to full regression checks. Retain FastAPI 0.141.1, Uvicorn 0.52.4, pytest 9.1.1, Pydantic 2.13.5 and HTTPX2 2.12.0; document newer releases and reasons in docs/DEPENDENCY_REVIEW.md. Add an offline TestClient import/lifespan/request regression with deprecations treated as errors. Create .pytest_cache/item3-dependencies/.venv without ensurepip cleanup and copy only pip 26.2.1 from the original environment as the bootstrap installer; resolve/install every application and test dependency fresh from PyPI.

Alternatives considered: update every package merely because a release exists; reuse the populated .venv; run default venv/pip cleanup; suppress dependency warnings. These add unrelated changes, fail isolation, violate no-deletion rules, or hide the observed incompatibility.

Consequences: an ignored installation helper retains pip temporary directories and enforces a filesystem audit guard; all package installation uses --no-cache-dir, wheel-only resolution and no personal pip config, keyring or netrc. No dependency implementation or test assertion is patched. Store the resolved inventory and reports, keep the existing .venv unchanged, and report the known deletion-policy failure separately. CI security auditing remains mandatory but is not executed locally under this run’s network restriction.


## 2026-10-04T11:28:58+00:00 — Item 4: separate contract evidence from local compatibility

Context: the official Viso Now product page links docs.now.viso.ai, but direct documentation reads recover only page metadata and an application shell. Existing tests fabricate appId/incidentId and incidentUrl examples; they are not captured vendor deliveries. Current product marketing mentions live feeds while processing-page metadata describes discrete files. Neither supplies a verified HTTP processing contract.

Decision: create docs/VISO_INTEGRATION.md with dated official sources, limited verified facts and four explicit unresolved wire contracts. Put four small fabricated payloads and their SHA-256 manifest in tests/fixtures/viso; keep SYNTHETIC provenance in the sidecar, outside the simulated wire payload, to avoid inventing vendor fields. The manifest records empty supported mappings for unresolved contracts, independently of expected local adapter outcomes. Offline tests pin safe example values, hashes, evidence fields and conservative adapter/webhook behaviour. No runtime or existing test changes.

Alternatives considered: infer an API from marketing, reuse local examples as vendor schema, mark synthetic delivery as LIVE, or require credentials merely to document uncertainty. These would overstate evidence or unnecessarily block item 4.

Consequences: item 4 can finish without account access, but vendor compliance and real delivery remain unverified. A future evidence revision must date its sources and update tests deliberately. Original .venv is retained; full verification will use the requested interpreter and separately the compatible item-3 environment to distinguish an inherited environment mismatch from new failures. No dependency, configuration or legacy-route migration is part of this item.


## 2026-10-04T11:43:16.037766+00:00 — Item 5: independent Viso configuration and receipt evidence

Context: the protected webhook reads DRONEWATCH_WEBHOOK_SECRET directly, while /health reports only liveness. A future outbound key must neither enable inbound ingestion nor imply a working vendor connection. Official wire contracts remain unresolved in the item-4 evidence matrix.

Decision: introduce a small immutable configuration reader for VISO_API_KEY, VISO_WEBHOOK_SECRET and the explicit legacy DRONEWATCH_WEBHOOK_SECRET alias. Normalize whitespace; empty values are absent. Equal nonempty inbound aliases are accepted; conflicting aliases produce a fixed, secret-free configuration error and disable protected ingestion. Keep outbound configuration independently visible. Exclude credentials from configuration repr. Read settings on demand without loading any .env file. Extend /health with providers.viso, preserving status and received_at; report not configured, configured but unverified, processed authenticated delivery, or configuration error. No state claims a verified vendor connection. Preserve existing preview state strings and keys; use ERROR for conflicts and add an explicit configuration_error field.

Alternatives considered: sharing an API key with inbound authentication (conflates trust directions); silently preferring one conflicting alias (hides misconfiguration); treating any configured key or local callback as verified Viso connectivity (unsupported).

Consequences: the legacy environment name, custom header and query-token transport remain compatible. Status evidence is process-local, excludes legacy-route traffic and synthetic playback, and cannot establish sender identity, payload compliance, live coverage or outbound operation. Malformed JSON does not establish a processed delivery. Removing configuration suppresses operational readiness without erasing historical receipt counters. The original unauthenticated route and outbound client remain separate backlog work.


## 2026-10-04T11:45:37.564490+00:00 — Item 5: preserve camera credential hygiene across aliases

Context: inspection found camera status and evidence scrubbing also directly read the legacy secret. Introducing the new inbound name without migrating these consumers would show contradictory readiness and could expose the new secret in sender text.

Decision: use the same configuration reader for camera readiness and redact both effective inbound and outbound credentials from camera text, longest first to handle overlapping values. Add a synthetic camera-response and stored-evidence regression. Keep the local sender CLI explicit legacy/--secret contract documented; it does not configure the receiver.

Alternatives considered: limiting changes to /health and authorization (inconsistent camera status and weaker credential protection), or refactoring the entire sender pipeline (unnecessary scope). Consequences: camera responses remain compatible and secret-safe for the new settings; no vendor schema, new transport or processing capability is inferred.


## 2026-10-04T11:50:13.662827+00:00 — Wrap-up validation and handoff scope

Context: this final step requests verification and documentation, while the original .venv still differs from requirements.txt and an existing test deletes its generated ground-truth fixture. The hard rules forbid deletion and test weakening.

Decision: run full discovery in both existing environments through the retained-scratch guard, keep both failures visible, and document completed backlog items separately from unresolved overall integration goals. Update only documentation and ignored validation evidence in this step.

Alternatives considered: upgrade the original environment through an uninstall (violates no deletion), suppress the failing test (weakens coverage), or implement remaining integration features (outside wrap-up scope). Consequences: the result may remain non-green; the reviewer receives exact commands, reports and limitations rather than a false completion claim.
