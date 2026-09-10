# Claude independent baseline review of DroneWatch 31a32e1

Reviewer: Claude Code (branch `claude/android-review`, worktree `dronewatch-claude`).
Scope: original `main.py`, `index.html`, `tests/`, the Viso ingestion boundary, and the
emerging Codex designs in `../dronewatch-backend` (only `scripts/demo.sh` and
`scripts/test.sh` exist so far; `main.py` and tests are byte-identical to baseline) and
`../dronewatch-mobile` (no changes yet). One note on the backend scripts: `test.sh` runs
`npm test` and compiles `target_schema.py`, and neither `package.json` nor that module exists
in that worktree yet, so the script fails until integration supplies both.
Every claim below was executed against a throwaway SQLite database or a throwaway
uvicorn on port 8899. Nothing was sent to the running services on 8765 or 8011.
This is a software-only schematic demonstration; nothing here concerns engagement.

## Ranked findings

| # | Sev | Area | Finding | Evidence | New vs Codex list |
|---|-----|------|---------|----------|-------------------|
| 1 | High | API robustness | A 300-deep JSON body is accepted (200) and then makes `GET /api/events` return 500 for every reader until the row is deleted. | `main.py:420,344`; `test_moderately_nested_payload_must_not_poison_the_events_api` | Partly listed; the persistent read-side poisoning is new |
| 2 | High | State semantics | `_normalize_state` substring matching inverts negated/cleared states: `no_drone_detected` becomes DETECTED, `exited_restricted_zone` becomes RESTRICTED_ZONE and API status CRITICAL. | `main.py:203-220`; `test_negated_or_cleared_states_never_raise_alert_level` | New |
| 3 | High | Provenance | Any anonymous POST with `appId`+`incidentId`+fresh `timestamp` lights VISO ONLINE, "Genuine event < 2 min", LIVE PIPELINE and "VISO / SENSOR EVENT" on the dashboard. | `index.html:66,102,125-127`; UI probe | New |
| 4 | High | Provenance | `received_at` stores the sender's timestamp; no server receipt time exists. Freshness, ordering labels and Codex's planned `updated_at` all rest on a sender-controlled value. | `main.py:198-200,277`; `test_server_receipt_time_is_recorded_independently_of_sender_timestamp` | New |
| 5 | High | Frontend state | Selecting a historical observation is silently undone by the next 2 s poll. Pinned mode lasts under 2 seconds. | `index.html:171,155`; UI probe | New |
| 6 | Med | Provenance | `find_first` token matching lets unrelated keys win by dict order: `camera_id` becomes the event id, `processing_time_ms: 42` becomes 1970-01-01T00:00:42, `callback_url` becomes media, `http_status` becomes the zone state, first list element shadows a drone at 0.99. | `main.py:73-100`; `test_unrelated_status_key_does_not_supply_zone_state`, `test_explicit_event_id_wins_over_camera_id`, `test_processing_time_field_does_not_become_event_time`, `test_callback_url_is_not_treated_as_media`, `test_multi_label_payload_prefers_drone_detection` | New |
| 7 | Med | Privacy | The operator's browser fetches any `mediaLink` URL supplied by a webhook poster when the evidence panel is opened. On Android that leaks the phone's IP to the poster. | `index.html:99,145`; UI probe | New |
| 8 | Med | Mobile cost | Every event is serialised twice per response; 50 events of 50 KB give 5.1 MB per 2 s poll, 200 events of 200 KB give 80 MB. The page also rebuilds all 200 log rows with `JSON.stringify` each poll. | `main.py:403-410`, `index.html:154-156,161`; `test_legacy_events_feed_duplicates_every_event` | New |
| 9 | Med | API semantics | Airspace status depends on the `limit` query: `limit=1` says SAFE while `limit=200` says ALERT for the same DB; an old DETECTED never closes. | `main.py:391-401`; `test_airspace_status_is_independent_of_page_size` | New |
| 10 | Med | API robustness | Invalid UTF-8 body returns 500; 100k-deep body returns 500; body size unbounded (20 MiB accepted in 0.18 s). | `main.py:415-422`; `test_very_deep_payload_is_rejected_not_500`, `test_invalid_utf8_body_is_rejected_with_4xx` | Confirmed from Codex list |
| 11 | Med | Confidence | `1e400`/`NaN` do **not** crash the API on the pinned stack (pydantic serialises them as null), contrary to Codex's task premise. But infinite confidence still yields severity WARNING; 150 stays 150 and yields WARNING; 1.5 becomes 0.015. | `main.py:121-123,230`; `test_non_finite_confidence_does_not_crash_events_api_on_pinned_stack`, `test_infinite_confidence_must_not_raise_severity`, `test_out_of_range_confidence_becomes_null_not_warning` | Premise corrected; bounds new |
| 12 | Low | Idempotency | Three deliveries of the same `event_id` create three open incidents. | `test_redelivered_event_is_not_counted_three_times` | New |
| 13 | Low | Ingestion | Non-JSON bodies are stored as `source=VISO` events and flip WEBHOOK RECEIVED. | `main.py:422-425`; `test_non_json_body_is_not_stored_as_a_viso_event` | Adjacent to Codex list |
| 14 | Low | Android UI | Track marker has no tabindex, role or handler; callout box renders 63 by 20 px with a 5 px id; 45 leaf text nodes are 8 to 10 px; "SHOW THIS OBSERVATION" is 167 by 27 px; the 8001 video retry fires every 5 s forever. | UI probe; `index.html:21,135,193` | Extends QA measurements |

Codex's four listed defects (non-finite confidence, invalid UTF-8, deep nesting, unbounded
body) were independently verified. Three reproduce as described. The non-finite case does
not reproduce as an API failure on this dependency set; see finding 11.

## Commands run and results

Baseline suites, unchanged code:

```
$ ../dronewatch/.venv/bin/python -m pytest -q
10 passed, 1 warning in 0.78s
$ node --test tests/dashboard.test.cjs
ℹ tests 10 / pass 10 / fail 0
```

Adversarial suite (new file, isolated `tmp_path` database):

```
$ ../dronewatch/.venv/bin/python -m pytest -q tests/claude_attack_test.py -rxX -p no:warnings
4 passed, 1 skipped, 20 xfailed in 1.04s
$ ../dronewatch/.venv/bin/python -m pytest -q -p no:warnings
14 passed, 1 skipped, 20 xfailed in 1.28s
```

Every `xfail` is `strict=True`. When a defect is fixed the test flips to XPASS and fails
the run until its marker is removed, so the suite cannot silently pass against broken code.

Android-emulated UI probe (`docs/engineering/claude-ui-probe.cjs`, Chromium with Pixel 7
user agent, 360 by 800, touch, against a throwaway uvicorn on 127.0.0.1:8899 seeded with
three spoofed webhook posts):

```
$ DRONEWATCH_DB_PATH=/tmp/dw-ui/ui.db ../dronewatch/.venv/bin/python -m uvicorn main:app --port 8899 &
$ for i in 1 2 3; do curl -s -X POST http://127.0.0.1:8899/webhook/viso -H 'content-type: application/json' \
    -d '{"appId":"spoof-app","incidentId":"inc-'$i'","incidentNumber":"ITM-000'$i'","label":"drone","state":"detected",
         "timestamp":"<now>","mediaLink":"http://127.0.0.1:8898/beacon-'$i'.mp4","fileType":"mp4"}'; done
$ NODE_PATH=../dronewatch-qa/node_modules node docs/engineering/claude-ui-probe.cjs
{
  "spoofedProvenance": { "visoStatus": "ONLINE", "visoNote": "Genuine event < 2 min",
    "pipeline": "RECENT VISO EVENT", "pipelineActive": "true", "provenanceBadge": "VISO OBSERVATION",
    "displayMode": "VISO / SENSOR EVENT", "webhook": "RECEIVED" },
  "beaconRequests": [ "http://127.0.0.1:8898/beacon-3.mp4" ],
  "showObservationButton": { "w": 167, "h": 27 },
  "pinnedImmediately":  { "contactEvent": "EVENT 1", "modeMessage": "Historical observation selected", "returnHidden": false },
  "pinnedAfterOnePoll": { "contactEvent": "EVENT 3", "modeMessage": "Actual sensor event / approximate visual position", "returnHidden": true },
  "marker": { "hasTabIndex": false, "role": null, "w": 92, "h": 33 },
  "calloutPx": { "boxW": 63, "boxH": 20, "idFontPx": 5.07 },
  "smallText": { "8": 3, "9": 15, "10": 27 },
  "pollsIn10s": 5, "videoRetriesIn10s": 2, "eventsResponseBytes": [ 3495, 3495, 3495 ]
}
```

The throwaway server was stopped afterwards; port 8765 was verified still owned by the
original process.

## Findings in detail

### 1. Moderately nested payload poisons the read path (High)

`main.py:420` parses the body with `json.loads`, which tolerates several hundred levels.
`walk_nodes` (`main.py:63-70`) recurses through it, and `_write_incident` stores it verbatim.
`_row_to_dict` (`main.py:344`) reloads it and FastAPI serialises `raw_payload` through
pydantic, which fails from depth 253 (bisected) with
`PydanticSerializationError: Circular reference detected (depth exceeded)`.

Measured thresholds (POST status, GET `/api/events` status):

| depth | 252 | 253 | 300 | 800 | 990 | 5000 |
|---|---|---|---|---|---|---|
| POST | 200 | 200 | 200 | 200 | 500 | 500 |
| GET  | 200 | 500 | 500 | 500 | 200 | 200 |

The dangerous band is 253 to roughly 980: the write succeeds and every subsequent read fails, for
every client, at every `limit`. Codex's plan bounds depth on ingest, which is necessary.
It is not sufficient: rows already stored, rows written by a future ingest path, or a
schema drift will hit the same serialiser. Proposed alternative: a read-side projection
that never returns `raw_payload` in list endpoints (return a size-bounded summary plus a
per-event detail route), and a depth check on ingest well below the serialiser's limit.
Falsify: insert a 300-deep `raw_payload` row directly with sqlite3 and call the new
`/api/targets`; it must return 200.

### 2. State normaliser inverts negated and cleared states (High)

`_normalize_state` (`main.py:203-220`) checks `"restricted" in s`, then `"exit"`, then
`"approach"`, then `"detect" or "drone"`. Results from `/tmp/dw_probe.py`:

```
state='exited_restricted_zone'        -> RESTRICTED_ZONE  api status=CRITICAL
state='left restricted zone'          -> RESTRICTED_ZONE  api status=CRITICAL
state='no_drone_detected'             -> DETECTED         api status=ALERT
state='undetected'                    -> DETECTED         api status=ALERT
state='DRONE_ZONE_INTRUSION_CLEARED'  -> DETECTED         api status=ALERT
state='not approaching'               -> APPROACHING      api status=WARNING
```

`DATA_SOURCES.md` says Viso webhook JSON is customer-configured and the existing test
suite already contains the string `No DRONE_ZONE_INTRUSION event emitted`, so
negated and cleared phrasings are realistic, not contrived. This is my sharpest dispute
with the backend plan: `/api/targets` is specified to map `status` from the existing
reported state, so an exit message would project as THREAT. Alternative: exact-token
allowlist after normalisation (`detected`, `approaching`, `restricted_zone`, `exited`),
everything else UNKNOWN, and carry `reported_state_raw` in the projection so the operator
sees what the sensor actually said. Falsify: post `{"state":"exited_restricted_zone"}` and
check that `/api/targets` reports UNKNOWN or TRACKED with the raw string attached, never
THREAT.

### 3. Dashboard provenance is spoofable by any anonymous POST (High)

`DW.kind` (`index.html:69`) classifies an event as VISO when `raw_payload.appId` and
`incidentId` exist. `DW.recent` (`index.html:102`) trusts `received_at`, which is the
sender's timestamp (finding 4). The UI probe above shows every trust indicator lit by
curl. `TACTICAL_UI.md` already says this is "payload provenance, not authentication", but
the rendered strings say "Genuine event" and "Actual sensor event". Alternative: rename
to "Viso-shaped payload" until a shared secret or signature is verified, and compute
freshness from a server receipt time. Falsify: repeat the three curl posts against the
integrated candidate and assert none of the four indicators reads ONLINE, Genuine,
RECENT VISO EVENT, or SENSOR EVENT.

### 4. No server receipt time (High)

`_extract_received` (`main.py:198-200`) returns the payload's timestamp, and
`_normalize_incident` stores it as `received_at` (`main.py:277`). Probe results:

```
timestamp='2019-01-01T00:00:00Z'  -> received_at 2019-01-01T00:00:00+00:00
timestamp='2999-01-01T00:00:00Z'  -> received_at 2999-01-01T00:00:00+00:00
timestamp=0                       -> received_at 1970-01-01T00:00:00+00:00
timestamp='garbage'               -> received_at <now>, no flag that it was discarded
```

Codex proposes `updated_at = existing event.received_at`. I dispute that: the projection
needs both `reported_at` (sender) and `received_at` (server), and every freshness or
ordering decision must use the server value. Falsify: post a payload with a timestamp one
year ahead and assert the projection's `received_at` is within seconds of wall clock.

### 5. Historical selection is undone within 2 seconds (High, frontend)

`refresh()` at `index.html:171` runs `displayed=observation; pinned=false` on every poll
unless a browser-only demo is active. The comment directly above it (`index.html:169-170`)
says "Always follow the API latest record ... Only an explicitly running browser-only
scenario can overlay the contact view", while the "SHOW THIS OBSERVATION" handler at
`index.html:155` sets `pinned=true` and shows "Historical observation selected" plus a
RETURN TO SENSOR button. The two intentions contradict each other in the same file, so
this cannot be waved off as by design: either pinning is dead UI or the poll is wrong.
The UI probe shows the view revert from EVENT 1 to EVENT 3 with the return button hidden
after one poll. On a touch device this reads as
a tap that did nothing. The proposed new UI adds touch selection and focus; the same
polling loop will erase it unless selection state is explicitly preserved across refreshes.
Falsify: in the candidate, select a track, wait three poll intervals, assert the selection
survives and only an explicit deselect or a new event for that track changes it.

### 6. Key-token capture in `find_first` (Medium)

`find_first` (`main.py:73-100`) accepts a key if any of its tokens matches a candidate,
and the candidate lists contain bare `id`, `type`, `time`, `url`, `status`. The first
match in dict order wins, at any depth. Probe results:

```
{"camera_id":"cam-7","event_id":"evt-1"}          -> event_id cam-7
{"processing_time_ms":42, "timestamp":"2026-..."} -> received_at 1970-01-01T00:00:42+00:00
{"callback_url":"https://evil.example/beacon"}    -> media_url https://evil.example/beacon
{"http_status":"restricted","label":"bird"}       -> state RESTRICTED_ZONE
{"meta":{"id":"nested-id"}}                       -> event_id nested-id
{"labels":[{"label":"bird","confidence":0.2},{"label":"drone","confidence":0.99}]}
                                                  -> detection_type bird, drone_detected false
```

Codex's `target_id` rule ("explicit tracking_id/target_id only when unambiguous else
event_id") inherits a corrupted `event_id`. Alternative: exact-key lookup with an ordered
preference list and no token matching; for arrays of labels, pick the maximum-confidence
drone label explicitly. Falsify: the six payloads above through `/api/targets`.

### 7. Webhook-supplied media URL becomes a browser fetch (Medium)

`DW.media` (`index.html:99-100`) accepts any absolute http(s) `mediaLink`, and
`renderEvidence` (`index.html:145`) sets it as a video or image `src`. The probe recorded
the browser requesting `http://127.0.0.1:8898/beacon-3.mp4`, a URL chosen by the poster.
Alternative: allowlist hosts (`now.viso.ai` and configured media origins) or proxy media
through the backend. Falsify: post a `mediaLink` on an unlisted host and assert no
request leaves the browser.

### 8. Response volume and per-poll DOM rebuild (Medium, Android)

`api_events` (`main.py:403-410`) returns `events`, `open_incidents` (the same rows again)
and `latest` (a third copy), each with full `raw_payload`. The dashboard requests
`limit=200` every 2 s (`index.html:161`) and rebuilds every log row including a
`JSON.stringify` of each raw payload (`index.html:154-156`). Measured:

| stored | response | per 2 s poll |
|---|---|---|
| 3 small events | 3.5 KB | trivial |
| 50 events of 50 KB | 5.1 MB | 2.5 MB/s |
| 200 events of 200 KB | 80.3 MB | 40 MB/s |

Alternative: `/api/targets` must omit raw payloads and be bounded in bytes, with a
`since` cursor or ETag so an unchanged feed returns 304. The legacy `/api/events` contract is
preserved by board decision, so `test_legacy_events_feed_duplicates_every_event` records the
cost as a measurement rather than an xfail. `test_targets_projection_is_bounded_for_mobile_polling`
is the acceptance criterion for the new route: under 1 MB with 50 stored 50 KB events and no
embedded `raw_payload`. It skips until `/api/targets` exists.

### 9. Status depends on page size and never closes (Medium)

`api_events` (`main.py:391-401`) computes status over the last `limit` rows and treats any
non-EXITED row as open. One DETECTED followed by five EXITED for other ids gives SAFE at
`limit=1` and ALERT at `limit=200`. There is no per-track closure, so a single old DETECTED
keeps the banner in ALERT until 200 newer rows push it out. Codex's dedupe by provenance
plus identity helps only if identity is trustworthy (finding 6).

### 10. Malformed bodies: 500s and unbounded size (Medium, confirmed)

Invalid UTF-8 returns 500 because `main.py:420` only catches `JSONDecodeError`, not
`UnicodeDecodeError`. A 100k-deep body returns 500 from `RecursionError` in `json.loads`.
A 20 MiB JSON body is accepted in 0.18 s and the next `limit=1` read returns 63 MB.
Codex's 256 KiB bound and depth limit address this. I support 4xx for undecodable bodies
with two conditions: nothing is stored on 4xx, and valid JSON of any shape (empty object,
array, scalar) still returns 200 because Viso expects 2xx and `test_webhook_empty_json`
depends on it. `test_valid_empty_and_list_json_still_acknowledged` guards that condition and passes today. It covers the empty object and array shapes Codex committed to. I did not assert the bare scalar case (`"drone"`), which today returns 200; if the integrated candidate rejects scalars that is a contract choice to record, not a regression.

### 11. Non-finite confidence: premise correction and real effect (Medium)

Codex's task states that `NaN`, `Infinity` or `1e400` cause a later API JSON failure.
On the pinned stack this does not happen: both endpoints are annotated `Dict[str, Any]`,
so FastAPI builds a response field and pydantic's `serialize_json` emits `null` for
non-finite floats. A plain `JSONResponse` would raise `Out of range float values are not
JSON compliant`, so any new endpoint that returns a `JSONResponse` directly, or drops the
annotation, reintroduces the crash. `test_non_finite_confidence_does_not_crash_events_api_on_pinned_stack` pins the current safe behaviour.

The real effect is semantic: `coerce_float` (`main.py:121-123`) stores `inf`, and
`_normalize_severity` (`main.py:230`) then reports WARNING. Bounds are also wrong for
finite values:

```
confidence=150  -> 150.0  severity=WARNING
confidence=1.5  -> 0.015  severity=INFO
confidence=-0.5 -> -0.5   severity=INFO
```

Codex's "finite 0..1 or null" rule is right. Note that `1.5` must become null, not 1.5 %.

### 12 and 13. Idempotency and garbage-as-VISO (Low)

Three posts with `event_id=evt-dup` create three open incidents (`open_count` 3).
`DATA_SOURCES.md` records that Viso retries are undocumented, so duplicates are plausible.
A body of `hello world` is stored as `source=VISO`, `state=UNKNOWN` and flips the
WEBHOOK RECEIVED indicator. Both are covered by strict xfail tests (`test_redelivered_event_is_not_counted_three_times`, `test_non_json_body_is_not_stored_as_a_viso_event`).

### 14. Android interaction details beyond the QA list (Low)

QA's `measurements.json` already documents rendered SVG labels of 3 to 5 px and controls
of 25 to 33 px. Additional measurements from the probe at 360 px: the marker callout box
is 63 by 20 px with a 5.07 px id string; the marker has no `tabindex`, `role` or
handler, so the proposed touch selection has no starting point in the current markup;
45 leaf text nodes render at 8, 9 or 10 px (`index.html:21` sets 8 and 9 px under 480 px);
the hard-coded 8001 video (`index.html:46`) retries on a 5 s interval forever
(`index.html:193`), producing two failed requests per 10 s on a phone where 127.0.0.1 is
the phone itself. `color-mix`, `100dvh` and `AbortSignal.timeout` need Chromium 111 or
newer; older Android WebViews drop the zone fill and stroke silently.

## Design choices I dispute, with falsification

1. **Building `/api/targets` on the unfixed normaliser.** Finding 2. Falsify with
   `{"state":"exited_restricted_zone"}` through the new route.
2. **`updated_at` equals sender `received_at`.** Finding 4. Falsify with a future timestamp.
3. **`target_id` falls back to `event_id`.** Finding 6. Falsify with `camera_id` ordered
   before `event_id`.
4. **Two synthetic paths.** The frontend plan runs the five-track scenario in the browser;
   the backend plan derives `SYNTHETIC_EVENT` only from stored `is_simulated` rows, which are
   produced by `/dev/simulate` and hidden by default. The default demo therefore never
   exercises the canonical envelope. Alternative: ship the deterministic scenario as a
   backend fixture served in the same `/api/targets` shape (for example a scenario file
   loaded when `DRONEWATCH_SCENARIO` is set), and have the UI render synthetic and real
   tracks through one code path. Falsify: grep the candidate UI for a second data shape or
   renderer; if the scenario objects lack `source_kind`, `status_basis` and `uncertainty`
   fields, the contract is untested by the default demo.
5. **Selection survives polling.** Finding 5. The new UI must hold selection in state that
   `refresh()` does not overwrite. Falsify by selecting, waiting three polls, checking.
6. **Raw payloads in list responses.** Findings 1 and 8. `/api/targets` should never embed
   `raw_payload`; expose it per event on demand with a byte cap.
7. **Freshness wording.** Finding 3. "Genuine" and "Actual sensor event" are overclaims
   without authentication; the board itself forbids claiming verified Viso connectivity.

Choices I support: strict JSON envelope with 4xx for undecodable bodies (with the two
conditions in finding 10), preserving `POST /webhook/viso` and `GET /api/events`,
null velocity and heading, `check_dir=False` assets mount, one-command local demo, and
keeping real events free of invented positions.

## Files in this commit

- `docs/engineering/claude-baseline.md` (this report)
- `docs/engineering/claude-ui-probe.cjs` (Android-emulated probe; needs Playwright, run
  with `NODE_PATH` pointing at an installed `@playwright/test`)
- `tests/claude_attack_test.py` (25 tests: 4 pass, 1 skip until `/api/targets` exists, 20 strict xfail on 31a32e1)

Not committed: `AGENT_BOARD.md` (manager-owned copy), `/tmp/dw_probe.py` (exploratory
script whose results are reproduced by the committed tests).
