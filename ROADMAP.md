# DroneWatch delivery roadmap

Status date: 7 September 2026.

The shortest credible route is synthetic-first and evidence-led: stabilize the
prototype, freeze a source contract, replay licensed real sensor recordings,
then add a genuine current source only when its semantics and rights are proven.
The existing frontend remains unchanged until the upstream data model is stable.

## Non-negotiable rules

- Every observation must say whether it is `SYNTHETIC`, `REPLAYED_REAL`, or
  `LIVE`, and must name the actual modality (`VISUAL`, `RADAR`, `RF`, `ADS_B`, or
  `REMOTE_ID`).
- Replayed real radar is real recorded radar data, but it is not live radar.
- ADS-B and Remote ID may be live telemetry, but they are not radar and do not
  detect a non-cooperative aircraft.
- Malformed or conflicting input is rejected; only an explicit schema-valid
  `UNKNOWN` observation is retained. Narrative text alone cannot create a drone
  detection.
- No model accuracy, range, bearing, speed, heading, latency, or reliability
  claim is made without a dated, reproducible measurement.
- Dataset files stay outside Git. Git stores manifests, licences, checksums,
  converters, fixtures, and result summaries.
- No classified, export-controlled, customer-confidential, operational-site, or
  otherwise sensitive defence media is uploaded to a cloud vision service.
- `index.html` remains frozen through V0.4 unless a proven data-contract gap
  requires an earlier decision by the project owner.

## Target data path

```text
licensed image / short clip
            |
            v
    Viso Now file analysis -----> Viso webhook adapter -----> VisualObservation

recorded or synthetic radar ----> radar adapter ------------> TrackObservation
live cooperative telemetry ----> telemetry adapter --------> TrackObservation
                                                               |
                                                               v
                                                     correlation / fusion
                                                               |
                                                               v
                                              stable API -> frozen dashboard
```

Viso Now is the visual-analysis component only. Current product documentation
does not establish a continuous live Viso Now video stream or a radar input.

## V0 — recovered concept prototype

Reference: remote commit `b9d3df6`.

Implemented:

- FastAPI webhook receiver and SQLite history.
- Dashboard polling and tactical presentation.
- Browser-only scenario and stored simulation controls.
- Local MP4 playback and repeated Google Drive file-copy helper.

Not proven:

- A trained DroneWatch model or licensed training corpus.
- A current end-to-end Viso Now delivery from a clean setup.
- Live visual, radar, RF, ADS-B, or Remote ID data.
- Sensor fusion, calibrated tracking, or performance metrics.
- Authentication, idempotency, incident closure, or safe public deployment.

## V0.1 — truthful, reproducible foundation

Goal: make the existing backend a clean engineering baseline without changing
the frontend.

Deliverables:

- Portable clone, launcher, setup, and root-level test commands.
- Exact direct dependency versions on a current FastAPI/Starlette line.
- GitHub CI for Python, dashboard, compilation, and dependency-audit checks.
- FastAPI lifespan startup instead of the deprecated startup hook.
- Remove the whole-payload `"drone"` substring false positive.
- Reject structured objects where scalar source/type/media fields are expected.
- Disable stored simulation by default.
- Stop returning the local database path and stop printing raw webhook payloads.
- Record the Viso Now constraints, source shortlist, release gates, and known
  limitations.

Exit gate:

- Fresh environment installs from `requirements.txt`.
- All 10 Python and 10 dashboard tests pass from the repository root.
- Dependency audit reports no known vulnerability in declared dependencies.
- `index.html` is byte-for-byte unchanged from V0.
- No user-specific absolute path remains in tracked runtime instructions.
- `main` and the `v0.1.0` tag resolve to the verified release commit.

V0.1 is still local/supervised only. Its webhook and raw event API remain
unauthenticated and must not be left on a persistent public endpoint.

## V0.2 — canonical observations and bounded Viso Now replay

Current status: **repository release candidate; external Viso acceptance
pending**. No `v0.2.0` release or tag is justified yet.

Goal: replace heuristic ambiguity with a stable contract and prove one bounded,
reproducible file-in/webhook-out run.

Repository-local phase implemented in the candidate tree:

- Versioned `dronewatch.event.v1` Python model and JSON Schema separating the
  source event ID, internal observation ID, `observed_at`, server-owned
  `received_at`, source scope, track, modality, provenance, delivery mode, and
  simulation status.
- Provider-neutral validation independent of the Viso mapper. Synthetic
  contract fixtures cannot claim Viso provenance.
- Atomic delivery keys scoped by source system, source scope, and source event
  ID, with deterministic content digests and digest-only conflict evidence.
- Historical observations and materialized effective track heads. A matching
  newer `EXITED` state closes a track; negative and `UNKNOWN` observations do
  not open one.
- Authenticated and streamed-size-limited receiver, with no default credential,
  no query-string fallback, no complete raw-body retention, and a sanitized
  dashboard compatibility projection.
- Transactional, repeatable V0.1 SQLite migration with legacy rows retained as
  `LEGACY_UNVERIFIED` rather than reinterpreted as Viso observations.
- Finite replay command with explicit scenario/run/fixture IDs, manifest and
  hash validation, a hard count limit, atomic copies, interruption cleanup, and
  a machine-readable local run record.
- Manifest-controlled six-clip Halmstad selection pinned to upstream commit
  `442d0c6750708cc221636f7a1fd31cbd8cb0aeb8` under CC0. Media remains outside
  Git and the selection was fixed before any Viso result was available.

Deliberately pending external phase:

- An actual redacted delivery from the configured Viso account, including the
  exact body shape and relevant non-secret header names.
- Proof of what authentication method that account can emit. If it cannot emit
  the required bearer header, an authenticated relay requires a separate design
  and explicit authorization.
- Strict Viso field mapping based only on that captured evidence. Until then,
  the Viso route returns `503 viso_adapter_unavailable` without storing input.
- A supervised Google Drive → Viso Now → DroneWatch run with fixture hash,
  configuration date, transport response, source/receipt timestamps, explicit
  latency definition, and redacted evidence.

Remaining release exit gate:

- Record the exact repository-local verification results against the candidate
  commit and confirm the protected frontend hashes.
- Complete every item in `VISO_ACCEPTANCE.md` using the actual account.
- Label the run `REPLAYED_REAL` plus `NEAR_REAL_TIME_FILE_REPLAY`, never live
  video, radar, general model validation, or operational detection proof.
- Obtain explicit user approval before push, merge, account changes, media
  upload, tunnel exposure, or creation of `v0.2.0`.

## V0.3 — deterministic radar/RF replay and synthetic fusion

Goal: add a compelling multimodal story without depending on demo-day network
or unavailable live counter-UAS radar.

Deliverables:

- Provider-neutral `TrackObservation` contract with source time, receipt time,
  coordinate system, uncertainty, track ID, modality, and provenance.
- Seeded synthetic radar scenario generator with reproducible trajectories,
  noise, dropouts, clock skew, and false contacts.
- Real Doppler RAD-DAR replay labelled `REPLAYED_REAL_RADAR`.
- Optional KTH radar and Tampere RF replay adapters.
- Explicit run/track correlation between the visual fixture and synthetic track.
- No derived schematic coordinate is represented as a measured sensor value.

Exit gate:

- Same seed produces byte-equivalent event sequences.
- Dropout, conflict, stale-event, clock-skew, and false-association tests pass.
- The API distinguishes raw sensor confidence, any model score, and fused score.
- An offline one-command scenario completes without external services.
- Frontend remains unchanged while the API contract is validated.

## V0.4 — evaluation and synchronized fusion evidence

Goal: produce results a technical defence audience can interrogate.

Deliverables:

- Dataset manifest with source URL, version, licence, hashes, splits, modality,
  acquisition conditions, limitations, and permitted use.
- Visual evaluation across drone, bird, aircraft/helicopter, background, distant
  target, low-light, and occlusion fixtures.
- Radar evaluation on KTH and a deliberately small TSMS-Drone subset.
- Metrics appropriate to the component: precision/recall, false alarms per
  minute, missed detections, latency, track continuity, classification confusion,
  and fusion association error.
- Dated results tied to exact code, prompt/agent setup, inputs, and environment.

Exit gate:

- Train/validation/test separation is by source sequence or measurement trial,
  not random near-duplicate frames.
- Negative controls are first-class and reported even when they hurt the score.
- Results reproduce from manifests and scripts without redistributing large data.
- Claims are limited to the tested conditions and distances.

## V0.5 — verified current source and demo hardening

Goal: add a genuinely current layer without mislabelling its technology.

Possible sources, in order of practicality:

1. Local UK Direct Remote ID from an owned/compliant drone, labelled live
   cooperative telemetry.
2. ADSB.lol ambient aircraft data, labelled live cooperative aircraft telemetry.
3. Partner-provided radar or Viso Suite edge/camera feed after written access,
   data-flow, licensing, and security review.

Deliverables:

- Preflight checks for source reachability, credentials, clock skew, database,
  Viso credits/agent state where applicable, and recorded fallback.
- Authentication, rate limiting, deduplication, structured logs, retention,
  reconnect/backoff, sanitized APIs, and failure-state reporting.
- Clean-start and 30-minute soak evidence plus disconnect/recovery tests.
- No secret, sensitive location, personal data, or controlled media in evidence.

Exit gate:

- A current provider- or hardware-backed run is captured and clearly labelled.
- Legal/display rights and source terms are recorded in the manifest.
- Failure or loss of a source degrades honestly rather than silently switching
  provenance.

## V0.6 — frontend integration and defence-demo polish

Only after the upstream contracts pass their gates:

- Display visual-only, track-only, and fused state separately.
- Make source modality, provenance, uncertainty, and age immediately visible.
- Preserve explicit `SYNTHETIC`, `REPLAYED_REAL`, and `LIVE` badges.
- Add presentation and technical-evidence modes.
- Validate the actual laptop, browser, display/projector, and intended remote
  access path separately.

## V1 — real sensor pilot

V1 requires an owned or partner-provided physical sensor, a lawful test site,
calibration, field data, documented ground truth, and measured operational
performance. Until those exist, DroneWatch remains a prototype and must not be
described as a deployed or certified counter-UAS system.

## Push and release discipline

Each stage is one bounded release on `main`:

1. Fetch and prove local `main` matches `origin/main` before editing.
2. Change only the stage's owned files; preserve unrelated work.
3. Run all baseline and stage-specific gates.
4. Review the exact staged path set and diff.
5. Create a focused local candidate commit after verification.
6. Stop at the authorization gate. Do not push, merge, expose a tunnel, change
   a provider account, upload media, or create a release tag without the user's
   explicit approval for that action.
7. After approval, push the intended commit and verify the remote branch SHA
   equals the local commit.
8. Wait for CI and satisfy the milestone's external acceptance gates before
   requesting approval for an annotated version tag.
9. Start the next stage only after the previous SHA, CI, external evidence, and
   tag are confirmed.
