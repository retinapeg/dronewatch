# Viso Now external acceptance gate

## Current evidence status

As of 7 September 2026:

- no genuine redacted request body from the user's configured Viso account was
  present in the repository or inspected local evidence;
- no provider header or retry/ordering/signing evidence was present;
- Viso's ability to emit DroneWatch's required inbound bearer header was not
  account-tested;
- Viso account/API OAuth is intentionally blank and remains external;
- the strict Viso mapper is disabled and fail-closed; and
- no supervised Google Drive → Viso Now → DroneWatch run occurred.

Accordingly, the repository is a **V0.2 repository release candidate with
external Viso acceptance pending**, not a completed or released V0.2. Do not
create `v0.2.0` from synthetic contract fixtures or local copy evidence.

## Safety and authorization gate

The repository workflow does not authorize an account change, media upload,
public/tunnel exposure, OAuth connection, external message, push, merge, or
release tag. The user performs or explicitly authorizes each external action at
the time it is needed.

Use only a manifest-listed public/CC0 clip or other footage the user is clearly
authorized to process. Never upload classified, controlled, customer,
operational-site, personal, ITAR/export-controlled, or otherwise sensitive
defence media.

All OAuth/Viso/Drive credentials, connector tokens, authorization values, and
sensitive endpoint URLs stay local and uncommitted. Leave Viso account/API OAuth
blank for this V0.2 acceptance run. Any later OAuth integration would be a
separate evidenced and explicitly authorized change.

## A. Capture the actual output contract

The user should configure or inspect one non-sensitive test output in their own
Viso Now account. Before enabling the adapter, capture all of the following:

- [ ] Viso product/account surface used (`Viso Now`, not an inferred Viso Suite
  feature).
- [ ] Workflow/agent name or redacted stable identifier.
- [ ] UTC configuration date and, if exposed, workflow/agent revision.
- [ ] Input connector type and its configured polling interval.
- [ ] Output connector type and exact custom-output configuration/export.
- [ ] The **exact raw JSON request body** from one manifest-listed test run,
  preserving paths, key case, arrays, nulls, primitive types, and timestamp
  formats.
- [ ] A redacted copy of that body in which only sensitive values are replaced,
  plus a short redaction map identifying which paths were redacted. Do not rename
  fields or normalize types while redacting.
- [ ] Relevant received HTTP header **names** and their multiplicity. Do not
  retain authorization/cookie values or sensitive URL/query values.
- [ ] The actual `Content-Type` and encoding behavior.
- [ ] Any provider delivery/event ID observed, including its exact field/header
  location and whether repeated delivery preserves it.
- [ ] Exact source timestamp field, timezone format, and documented/account-
  observed semantics. If there is no source observation time, record that fact;
  never substitute receipt time.
- [ ] Exact track identity behavior, if the configured output supplies one. Do
  not collapse a delivery/event ID into track identity.
- [ ] Exact positive, negative, unknown, and exit values the configured output
  can emit. Narrative text is not a lifecycle signal.
- [ ] Whether normalized frame coordinates are actually supplied and what their
  coordinate convention means. Omit coordinates if this is not evidenced.
- [ ] Actual HTTP response status shown by Viso for the test delivery.
- [ ] Any retry, ordering, timeout, or signing behavior actually observed or
  documented for this account configuration. Mark unknowns `NOT_ESTABLISHED`;
  do not infer them.

Store the redacted fixture only after review confirms it contains no secret,
authorization header, sensitive URL, customer/account data, local absolute
path, or controlled media/reference. Name it as a genuine Viso fixture only
when it came from that account run. All fabricated provider-neutral examples
must remain labelled `SYNTHETIC_CONTRACT_FIXTURE`.

## B. Establish inbound authentication capability

DroneWatch requires one `Authorization: Bearer <token>` header and has no query-
string or unauthenticated fallback. Account evidence must answer:

- [ ] Can this Viso output connector set an HTTP `Authorization` header?
- [ ] Can it emit the `Bearer` scheme with an operator-supplied secret?
- [ ] Is the header applied to the webhook delivery itself, rather than to a
  separate Viso API/OAuth connection?
- [ ] Are secret values masked in the account UI/logs and excluded from output
  previews/exports?
- [ ] Does one supervised request reach DroneWatch with the correct header and
  receive the expected acknowledgement?
- [ ] Does a request with the header omitted receive `401` without storage?

Record only capability, UI field names, configuration date, route type, and
test outcome. Never record the credential value or authorization header.

Viso account/API OAuth and the outbound webhook bearer capability are distinct.
OAuth must remain blank for the V0.2 acceptance run even if the webhook
connector supports a header. Do not invent OAuth environment variables or treat
blank OAuth as evidence that the webhook is authenticated. Any later OAuth work
is a separate evidenced and explicitly authorized change.

If the account cannot emit the required bearer header, stop. Do not weaken
DroneWatch. Record `DIRECT_BEARER_NOT_SUPPORTED` with evidence, then design an
authenticated relay as a separate bounded change only after user authorization.

## C. Implement and verify the strict adapter

After A and B provide real evidence:

- [ ] Map each canonical field from one exact documented JSON path; no recursive
  search, fuzzy aliasing, narrative keyword inference, or universal Viso schema.
- [ ] Record, beside each mapping, the redacted fixture ID and Viso configuration
  date that establish it.
- [ ] Require stable source event identity; reject a delivery that lacks it.
- [ ] Require a separately evidenced source scope and track ID for positive
  lifecycle events.
- [ ] Restrict the Viso path to modality `VISUAL`.
- [ ] Assign `REPLAYED_REAL` plus `NEAR_REAL_TIME_FILE_REPLAY` for the licensed
  recorded fixture run; never surface it as `LIVE`.
- [ ] Keep DroneWatch `received_at` server-owned.
- [ ] Reject missing/malformed identities, timestamps, classes, lifecycle
  values, provenance/mode conflicts, and unknown extra shapes without a write.
- [ ] Add the redacted genuine-delivery fixture and negative mutation tests.
- [ ] Demonstrate first delivery, exact retry, conflicting retry, lifecycle
  close, and sanitized API behavior through the provider route.

Only the fields proven by the captured delivery may be mapped. If the output
does not provide a value, change the configured DroneWatch-owned custom message
or reject the delivery; do not fabricate it in the adapter.

## D. Run one supervised finite scenario

Preflight:

- [ ] Record the exact tested Git commit and confirm it is the intended
  candidate.
- [ ] Re-run all repository checks and dependency audit against that commit.
- [ ] Confirm `index.html` has Git blob
  `35af3f056e905b802669e3720a7362626426ff2a` and SHA-256
  `e1d9be772509789c925ebe30b62a41e1642d5d8f250afa5d1edf484571a0b293`.
- [ ] Choose one fixture from `fixtures/halmstad-selection.v1.json` and verify
  its basename, byte count, and SHA-256 locally.
- [ ] Choose unique scenario/run IDs and an explicit finite copy count (maximum
  20).
- [ ] Confirm the receiver token is set locally but will not enter logs,
  commands retained as evidence, screenshots, or files.
- [ ] Confirm system clocks and UTC recording; note any known clock uncertainty.
- [ ] Confirm the destination is the intended existing watched folder and that
  run records are outside it.

Run, with explicit user action/authorization where external state changes:

- [ ] Start DroneWatch against the intended local/test database and capture
  sanitized logs.
- [ ] Start a temporary endpoint/tunnel only if explicitly authorized. It must
  expose only authenticated `POST /webhook/viso` through a route-scoped proxy;
  deny the UI plus every GET, config, legacy, canonical, and development route.
  Treat its URL as sensitive and do not commit or publish it. If that exact
  route restriction is unavailable, stop for a separate public-read
  access-control review rather than exposing the development process.
- [ ] From outside the host, verify the proxy rejects `/`, `/health`,
  `/api/config`, `/api/events`, `/api/legacy/events`, `/webhook/canonical`, and
  `/dev/simulate`; retain only the route-block outcomes, never the sensitive
  endpoint URL or credentials.
- [ ] Configure the account webhook/output using the proven authentication route.
- [ ] Run `demo_feed.py replay` for the chosen finite scenario.
- [ ] Retain its machine-readable local copy record.
- [ ] Observe Drive synchronization separately; do not infer it from local copy.
- [ ] Observe Viso processing separately; retain the actual result even if it is
  a miss, negative, unknown, or false positive.
- [ ] Observe the authenticated webhook acknowledgement and query sanitized
  DroneWatch state.
- [ ] Stop the temporary exposure and test processes immediately after capture.
- [ ] Do not delete source media, copied watched-folder files, database rows, or
  local run evidence as part of the runner.

## E. Complete the redacted evidence record

Copy `evidence/viso-run-template.v1.json` to a local evidence workspace and
complete it under its checked-in structural JSON Schema and the normative
cross-field validation in `replay_artifacts.py` and
`scripts/verify_replay_artifacts.py`. A genuine retained record must include:

- [ ] exact tested Git commit;
- [ ] non-secret Viso agent ID, configuration ID, and UTC configuration date;
- [ ] scenario/run and fixture IDs;
- [ ] exact manifest `derived_sha256` for the bytes replayed (equal to the
  source hash for this untransformed selection);
- [ ] local atomic-copy completion timestamp;
- [ ] provider-observed timestamp, only if supplied with established semantics;
- [ ] DroneWatch server `received_at`;
- [ ] response status;
- [ ] exact redacted request digest;
- [ ] authentication route description without a credential;
- [ ] provenance `REPLAYED_REAL`;
- [ ] delivery mode `NEAR_REAL_TIME_FILE_REPLAY`;
- [ ] actual classification/detection/lifecycle result, including any miss,
  negative, unknown, or false positive;
- [ ] an explicit latency name, endpoints, clock basis, formula, units, and
  calculated value; and
- [ ] limitations and unproven claims.

The schema makes endpoints, formula, unit, and value explicit:

- `latency_basis: RECEIPT_MINUS_PROVIDER_OBSERVED` means
  `latency_ms = (dronewatch_received_at - provider_observed_at)` in
  milliseconds. Use it only when the provider timestamp semantics and clock
  basis are established. Label it provider-observation-to-receipt latency for
  this one run.
- `latency_basis: RECEIPT_MINUS_LOCAL_COPY_COMPLETED` means
  `latency_ms = (dronewatch_received_at - local_copy_completed_at)` in
  milliseconds. Label it local-copy-to-receipt elapsed time.

Do not call either value model inference time. If the clocks cannot be compared
defensibly, stop the evidence completion and document the clock blocker rather
than inventing a latency.

The retained evidence must contain no authentication/OAuth value, authorization
header, secret URL, unredacted provider body, customer/account information,
controlled media, or machine-specific absolute path.

## F. Release exit gates

All items below must be true before requesting approval for `v0.2.0`:

- [ ] Genuine redacted Viso delivery exists and passed sensitive-data review.
- [ ] Strict adapter is based only on that delivery/configuration evidence.
- [ ] Account-tested authentication route is demonstrated.
- [ ] Six-fixture licence/provenance manifest validates at the pinned revision.
- [ ] Supervised Drive → Viso Now → DroneWatch evidence run is complete.
- [ ] Result and limitations are reported without live/radar/accuracy claims.
- [ ] Frontend hashes match the protected values.
- [ ] Local checks and current CI pass against the exact intended release commit.
- [ ] Intended local and remote release SHAs match after an authorized push.
- [ ] No unrelated files, secrets, media, databases, caches, logs, local evidence,
  or absolute machine paths are staged.
- [ ] User explicitly approves the final release/tag action.

Until every box is supported by evidence, keep the status:

`V0.2 REPOSITORY RELEASE CANDIDATE — EXTERNAL VISO ACCEPTANCE PENDING`

A successful single transport run proves authenticated file-in/webhook-out
delivery under the recorded conditions. It does not establish live video,
model validation, measured accuracy, general reliability, operational detection,
or certified defence use.
