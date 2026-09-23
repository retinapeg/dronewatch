# Autonomous Engineering Board

Shared blackboard for Claude Code (lead) and OpenAI Codex (peer engineer).
Read this before substantial work. Git commits and executable tests are the
ultimate source of truth — this file is a summary, not an authority.

## Mission
DroneWatch (github.com/retinapeg/dronewatch): a counter-UAS operator demo.
Make the primary demo clear and reliable, with Android usability treated as
release-blocking. No giant rewrites.

## Current Objective
R1: resolve the incident-state correctness dispute with executable evidence.
R2: reproduce the Android/mobile failure at 360x800, 393x873, 412x915.

## Task Queue
- [x] Prove Codex CLI connectivity (CODEX_CONNECTED_OK)
- [x] Reproduce Codex's incident-state bug over real HTTP
- [ ] Round 2: Claude criticism -> Codex defends/revises
- [ ] Decide read-side vs write-side fix on evidence
- [ ] Mobile QA at three Android viewports, screenshots + regression test
- [ ] Implement winning incident-state fix
- [ ] Both engineers propose mobile fix; compare; implement better one

## Claude Findings
- Codex's bug is REAL. Reproduced end-to-end over HTTP (not in-memory):
  POST /webhook/viso DETECTED(evt-drone-7) then EXITED(evt-drone-7)
  -> GET /api/events returns status=ALERT, open_count=1, open states ['DETECTED'].
- Retry inflation also REAL: 3 identical deliveries of one event_id -> 3 open rows.
- Root cause is a read-side derivation: main.py:426 filters EXITED/UNKNOWN rows
  out of a raw event log instead of reducing to latest-state-per-incident.
- Server is running and healthy on 127.0.0.1:8010 (detached, PPID 1).
- Mobile has NOT yet been tested. Codex did not start the app or run the suite.

## Codex Findings
(Codex, gpt-6-astra, CLI 0.154.0, session 0.151->0.154 upgraded)
- Project: FastAPI/SQLite incident-awareness prototype + synthetic tracking and
  operator demo. Two distinct data paths: legacy incident store, and the newer
  preview/tracks pipeline.
- Highest-priority problem: incident-state correctness at the ingestion/storage
  boundary. main.py:420 filters EXITED rows but leaves earlier DETECTED rows open;
  schema lacks a unique event constraint; ingestion inserts every delivery.
- Proposed increment: source-scoped event identity, idempotent storage, separate
  observation/receipt timestamps, lifecycle state updated by newer matching events.
- Also flags: legacy /webhook/viso is unauthenticated and unbounded; /api/events
  returns raw payloads. Protecting only the v2 route does not protect the app.
- Self-reported limits: did not run the test suite, did not start the application.

## Disagreements
D1 (OPEN) Priority. Codex ranks incident-state highest. Claude disagrees: the
   product owner designated Android usability release-blocking, and Codex ranked
   priority without starting the app or looking at the UI.
D2 (OPEN) Fix scope. Codex proposes a write-side schema migration (unique
   constraint, idempotent storage, lifecycle updates). Claude argues the operator-
   visible symptom is a read-side derivation bug fixable at main.py:426 by
   reducing to latest-state-per-incident, with no migration and no write-path
   risk, fixing BOTH the exit bug and retry inflation. Burden on Codex to show
   what the heavier approach buys that the read-side fix does not.

## Proposed Solutions
S1 (Codex): write-side. Unique index on (source, event_id); upsert; lifecycle
   column updated by newer matching events; observation vs receipt timestamps.
S2 (Claude): read-side. In api_events, group rows by incident key and keep the
   latest by primary key, then apply the open/closed filter to that reduction.
   Append-only log preserved for audit. No migration.

## Test Evidence
- E1 tests/test_incident_state.py (to be written) must fail on main and pass on
  the fix: DETECTED then EXITED -> status SAFE, open_count 0.
- E2 retry idempotence: 3 identical deliveries -> open_count 1, not 3.
- E3 ordering: out-of-order delivery (EXITED arrives before DETECTED by receipt
  but is older by observation time) must not reopen a closed incident.

## Decision
(pending Round 3 evidence)

## Current Branches
- feat/operator-demo-v0.2  @ 2aebda2  (integration base, Claude)
- claude/mobile-qa         (Claude: Android reproduction + regression test)
- codex/incident-state     (Codex: its own implementation, isolated worktree)

## Known Bugs
- B1 CONFIRMED: exited drone still reported as an open incident (status ALERT).
- B2 CONFIRMED: duplicate webhook deliveries inflate open_count.
- B3 REPORTED by Codex, unverified: legacy /webhook/viso unauthenticated/unbounded.
- B4 UNKNOWN: Android/mobile failure — not yet reproduced.

## Blockers
- None. Codex CLI was 0.151.0 and rejected gpt-6-astra; upgraded to 0.154.0.

## Next Actions
1. Codex answers the D2 challenge with a defence, revision, or third option.
2. Claude reproduces the mobile failure and writes the regression test.
3. Winner of D2 implemented on a branch with E1-E3 passing.

## 2026-09-10 Camera demo frontend (Codex)
- Added `/camera` interface in `camera.html`: real HTML video replay, media
  selection/downloads, Google Drive submission state, and separately polled
  authenticated callback results. Added a prominent Camera + Viso preview link.
- Empty probes and explicitly synthetic webhook senders never become displayed
  Viso incident results. Unknown callback shapes remain visibly unmapped.
- No boxes or coordinates are inferred. The sender's own Summary is presented
  with its full text available; all callback strings use `textContent`.
- Verified camera/operator Node tests pass, and inspected desktop/mobile browser
  screenshots. Actual callback returned a long narrative without boxes; UI now
  surfaces its own summary and source instead of burying them below the report.
- Added the same actual evidence to a collapsible `/preview` inset with a 2D
  sensor video, sender labels/confidences, and explicit scenario association.
  `/preview?demo=viso` starts the existing radar-loss demo at T+35 at 2x.
- Inset time synchronisation uses manifest scenario context, replay time and
  video duration. It pauses before/after the source interval, with simulation
  pause, and for other scenarios. The standalone evidence page remains a replay.
- Browser smoke at 1440x900 confirmed autoplay, H.264 media readyState 4, actual
  Viso label rendering, and no JavaScript errors. A header fit issue was found
  visually and fixed so all 3/6/10 contact choices remain available.
- Added selected-contact reference artwork with Long-wing, Delta-wing and FPV
  examples. Choices are presentation preferences per contact and do not assign
  a military model or alter tracker evidence. Raster sprite loads from the exact
  `/assets/drone-types.png` route; vector silhouettes cover asset unavailability.
  Browser verified all three choices, visible selected artwork and preserved
  metadata with no JavaScript errors; inspected the final screenshot at 1440x900.


## Event camera demo — 10 September 2026 (Codex)
- Isolated branch: `codex/viso-camera-demo`, based on GitHub main c079626.
- Verified live receiver accepted two authenticated empty Viso connection tests; no visual-analysis incident had arrived before implementation.
- Added camera media replay and bounded actual webhook-result evidence in parallel with a deterministic synthetic-camera renderer. Synthetic pixels are input to Viso; generator truth and generated result payloads must not become Viso detections.
- Found existing private Google Drive folder `DroneWatchIngest` with last week's drone MP4s. Preparing a bounded synthetic media batch for this input, while user checks the Viso application's input configuration.
- Public tunnel forwards only POST /v2/webhook/viso to the local authenticated receiver. Dashboard and camera media remain local.
- Validation and end-to-end result pending below.

### Event demo verified — final state
- Real Drive→Viso→authenticated webhook deliveries observed for clip-02.mp4, schematic-01.mp4 and schematic-02.mp4. Returned schema includes sender labels, confidence/zone fields and narrative. No fake feed script was run.
- User requested simple labelled2D symbols; schematic02 uses existing observation pipeline and exact stable cue schedule. Original uploaded schematic01 assets restored byte-for-byte from Drive; corrected versions have separate filenames.
- Fixed hash(track_id) process randomness with crc32 so renderer and server cues match across Python processes; cross-process regression passes.
- /preview?demo=viso starts atT+35 at2x, shows source-correlated nonspatial Viso evidence and synchronized2D clip. Existing synthetic tracker estimates positions; real Viso callbacks do not supply positional updates.
- Clicking a contact shows generated reference art with long-wing/delta-wing/FPV example selection. It is explicitly reference artwork, not a detected aircraft identification.
- Validation:242 Python tests passed;60 Node tests passed. Desktop1440x960 and mobile393x873 browser QA: no page errors or horizontal overflow, playable synchronized H264, all3 reference choices inspected.
- Local app127.0.0.1:8020 remains running; authenticated webhook tunnel unchanged. Private callback evidence and feed state remain in this thread work directory.
