# DRONEWATCH AUTONOMOUS ENGINEERING REPORT

Date: 10 September 2026. Repository: https://github.com/retinapeg/dronewatch

**Result: the local demo milestone passes its configured release gate.** The default view is a deterministic five-target scenario with 3/5/10 options, touch selection, bounded target focus, clear priority, source disclosure and target detail. The integrated acceptance command passed **78 Python tests, 24 JavaScript tests and 128 browser executions**, with zero failures or retries. All five viewport families have inspected screenshots, no document overflow, no checked controls below 44px and no console/runtime errors.

This is a **local candidate validated with desktop Chromium Android/touch emulation**. It is not physical Android certification, a public production release, real Viso connectivity or a validated threat classifier. Claude Code completed a substantive independent baseline audit; its second candidate pass hit its subscription limit. An independent Codex release review passed, and a bounded Claude follow-up is scheduled for 12:35 Europe/London today.

Application code is frozen at `1ae4335309c45f990efc63c8a9e7bf4e6aa0e062`; the full tested source including additional independent tests is `bd12deae27cb2c160a26a04f8c905f628208f7fd`. Later commits add evidence, handoff documentation and CI compilation coverage, without changing the tested application.

## 1. Starting repository state

- Fresh clone of GitHub main `31a32e1764572837ff43691b50aa3a15bc458714`.
- Verified repository identity, origin, branch and clean status before work. Older local DroneWatch and its separate V0.2 candidate were preserved.
- Python/FastAPI/Uvicorn backend in `main.py`, SQLite history, single vanilla `index.html`; no React/Vue, bundler or separate frontend service.
- Pinned Python requirements installed successfully. Initial Python suite: 10 passed. Initial Node helper suite: 10 passed. One existing Starlette/AnyIO deprecation warning; no broken dependency installation was reproduced.
- Original application was actually started. HTTP /, /health, /api/config and /api/events returned 200 on loopback 8765. An unrelated occupied port was left untouched.
- Existing CI ran Python tests, Node helper tests, dependency audit and compilation. There was no mobile browser gate.
- Viso path: POST /webhook/viso → normalization → SQLite → GET /api/events. Optional file/video helper `demo_feed.py` was separate from that webhook boundary. No live provider credentials or connection were inferred from the README.

## 2. Android/mobile failures reproduced

QA wrote and ran regressions against the original application before the replacement UI. **15 targeted executions failed** across 360×800, 393×873, 412×915, 873×393 landscape and 1440×1000 desktop.

- Phone radar labels rendered around 3–6 screen pixels; at 360px the target label was approximately 5.07px and the state label 3.72px.
- Several visible controls were only 20–33px high, unsuitable for reliable touch use.
- The default page requested a hard-coded 127.0.0.1:8001 video, producing failed resources/console errors. On a phone this address is the phone, not the demo laptop.
- Demo affordances depended on server simulation configuration and did not provide the required obvious small scenario.
- The synthetic badge was clipped in the original layout.

**No ordinary document horizontal overflow or JavaScript exception was reproduced in the original empty-state baseline.** We did not invent those failures. Later, adversarial long sensor identifiers produced actual overflow in the candidate, and that defect was separately fixed and tested.

## 3. Root causes

The old SVG scaled its labels with the whole drawing, while desktop-sized control/layout assumptions survived on small screens. A separate localhost media dependency was unsuitable for same-network phones. Simulation and event details dominated the operator flow.

Backend inspection also found permissive malformed-input handling, substring-based key/state interpretation, unsafe numeric coercion, ambiguous multi-object projection, spoofable source wording and fallback receipt times being treated as observation times.

## 4. Screenshots and evidence

- [Original baseline and measurements](docs/evidence/baseline/README.md)
- [Original 360px scenario](docs/evidence/baseline/android-360-scenario.png)
- [Final 360px five-target view](docs/evidence/release/android-360-default-five.png)
- [Final 393px selected target focus](docs/evidence/release/android-393-selected-focus.png)
- [Final 412px ten-target view](docs/evidence/release/android-412-10-targets.png)
- [Final landscape focus](docs/evidence/release/android-landscape-selected-focus.png)
- [Final desktop](docs/evidence/release/desktop-default-five.png)
- [Final empty sensor view](docs/evidence/release/android-360-empty-sensor.png)
- [QA visual verification and served-asset hashes](docs/evidence/release/QA_VERIFICATION.md)

The final set has 25 full-page captures plus a 393px playback close-up. QA inspected every viewport and state family. The manager independently inspected the six representative final images linked above. Served HTML/CSS/JavaScript SHA-256 hashes matched the frozen tested commit. Paused screenshot scenarios use time 00:00 and reduced motion; the empty sensor response is explicitly mocked.

## 5. Codex's proposed solutions

Codex implemented a small vanilla frontend, retaining the existing server instead of adding a framework or external rendering service. HTML target buttons keep touch area and text size independent of SVG geometry. The default browser producer owns deterministic playback so a Viso/API outage cannot break the synthetic scenario.

The official Codex CLI independently authored the initial ingestion/canonical projection and a second provenance/freshness patch. Supervising Codex engineers supplied adversarial failing tests, reviewed its output and ran the unrestricted full suite, including actual localhost socket tests. Additional frontend, QA and independent review engineers worked in separate physical worktrees.

## 6. Claude's criticisms and actual contribution

The installed official Claude Code 2.1.267 ran non-interactively in `claude/android-review`, using the existing authenticated subscription. Its completed run lasted 872.93 seconds, exited 0 and produced `2f62e63`. The model reported by that run was `claude-fable-5-1`.

The [completed Claude audit](docs/engineering/claude-baseline.md) ranked concrete problems including false positive negated states, key-token hijacking, deeply nested legacy input, large responses, inaccurate source provenance, freshness semantics, polling selection churn and mobile/video failures. It added executable attack probes. Its final baseline attack run had four passes, one skip because /api/targets did not yet exist, and twenty strict expected failures; these are historical defect evidence, **not** current passing release tests.

Claude's second job started on candidate `7083a12`, performed setup and tests, then returned the subscription limit. The runner recorded exit 1 and `model_completed: false`; it did not deliver a completed candidate verdict or patch. Reset was reported for 12:30 London. No paid API fallback was provisioned. The app has a one-run thread follow-up scheduled at 12:35 London to review the latest candidate and fix only demonstrated regressions.

## 7. Competing approaches where relevant

There was no artificial second full frontend. Meaningful alternatives concerned correctness:

| Question | Proposed alternative | Selected implementation |
|---|---|---|
| Does receipt now make an old observation current? | Use receipt-only freshness | Keep validated source time and actual receipt separately; old source observations remain stale |
| Which confidence applies to mixed detections? | Select maximum drone confidence | Treat unresolved object association as unknown; retain the reported alert only as evidence |
| How to fix tiny radar labels? | Keep all labels inside a scaled SVG | SVG geometry plus readable HTML target controls |
| How to protect long IDs? | Truncate visible strings alone | Bound canonical identity with field-scoped digest and reserve its marker; separately bound visible action labels |
| What happens if a feed fails? | Default to a plausible synthetic fallback | Explicit unavailable/cached states; synthetic demo is an intentional separate mode |

## 8. How disagreements were resolved

Executable cases decided the result:

- Before the initial CLI patch, its focused ingestion suite had 9 failures and 1 pass.
- Negative-state regressions had 6 failures and 1 pass; huge-number probes had 4 failures.
- Manager provenance/freshness/Unicode probes initially failed 15 cases.
- Claude-derived key/state/association cases initially failed 6 and passed 3.
- Two more multi-object association cases failed before the conservative fix.
- The final projection-bound suite had 10 failures and 1 pass before its patch, then 11 passes.
- Browser QA first found 8 failures in the replacement; later checks reproduced hidden paths, lost keyboard focus, oversized IDs and split 393px playback words. Those checks now pass.

For example, a source timestamp a year old is still displayed stale after a new receipt; missing timestamps say observation time unverified. A mixed collection cannot acquire the most confident object's identity or intent. This retains useful information without manufacturing certainty. The [backend record](docs/engineering/backend.md) documents each before/after stage.

## 9. Final implementation

- Default five-target, 90-second scenario with 3/5/10 choices, pause/resume/reset and replay after completion.
- Clear first-review banner, priority-ordered register, distinct states and selected-target outline.
- Tap/click target selection and a bounded 1.7× focus camera. Every one of ten targets remains focusable at scenario completion.
- Selected detail includes identity, scenario/reported status, confidence basis, schematic position, course/path when authored, boundary context, update time, evidence, uncertainty and alternative interpretation.
- Actual velocity, physical distance and time-to-impact are not fabricated where no calibrated coordinate system exists.
- A compact observation log explains authored scenario changes.
- Identical source IDs from different sources remain separately selectable with distinguishable accessible names.
- Keyboard focus and expanded detail survive polling; outdated requests cannot overwrite a newer mode generation.
- The original dashboard remains at /legacy, byte-identical to the baseline HTML.

## 10. Architecture changes

`assets/scenario.js` produces deterministic common target fields with synthetic provenance. `assets/operator.js` renders those fields and separately validates canonical sensor responses. `target_schema.py` projects stored webhook observations into the same core representation. This is an observation boundary, not sensor fusion.

POST /webhook/viso and GET /api/events are preserved. GET /api/targets excludes raw payloads, supports nullable unknown quantities and records provenance, source time, receipt time and uncertainty. SQLite gains an additive `ingested_at` column without discarding history. Migrated fallback timestamps are not promoted into verified source time.

Synthetic classifications and confidence are authored fixtures. Unauthenticated Viso-shaped payloads remain WEBHOOK_EVENT; SENSOR_EVENT is reserved for a future verified producer. Camera-frame positions are not drawn as geographic radar measurements.

Malformed UTF-8/JSON, nonfinite values, excessive depth and bodies over 256 KiB are rejected without writes. Normalized exact-key matching replaces token/substring matching. Canonical identities are bounded to 128 UTF-8 bytes with deterministic digest protection; evidence strings to 160 bytes; the entire canonical JSON response to 262,144 bytes, including escaping. A truncation indicator is displayed as a limited window.

## 11. Tests added

Meaningful coverage now includes:

- Malformed JSON/Unicode, negative states, key hijacking, huge numeric values, mixed objects and incompatible coordinates.
- Additive migration, source/receipt freshness, unverified provenance, source-scoped tracking, identity collisions, legacy deep rows and response byte budgets.
- Deterministic scenario bounds, ordering, trajectories, shared shape and absence of fabricated sensor movement.
- Every requested touch viewport, focus/selection, readable labels, minimum controls, overflow, orientation, deep links, refresh, empty/malformed/stale feeds, rapid updates, outage/recovery and mode races.
- Both real HTTP POST → SQLite → canonical API → browser and independent TestClient → disposable SQLite → browser boundary checks.
- Automatic axe checks on the smallest phone and desktop; desktop keyboard and polling focus checks.
- The runner's worktree restrictions, lock lifecycle, process timeout and exit-zero/model-failure handling.

The original ten Node helper assertions remain intact, reading legacy.html.

## 12. Complete test results

Final command: `./scripts/test.sh`. Exact tested commit: `bd12dea`. Exit code **0**.

| Gate | Actual result |
|---|---:|
| Python | 78 passed, no skips, 3.68 seconds |
| JavaScript | 24 passed, no skips |
| Chromium acceptance | 128 passed, 12 intentional skips, 0 failed, 0 flaky, 58.84 seconds |
| Python compilation | Passed, main.py / demo_feed.py / target_schema.py |
| git diff --check | Passed |
| Python dependency audit | No known vulnerabilities |
| npm audit | Zero reported vulnerabilities |
| pip check | No broken requirements |
| Fresh launcher | Successful dependency bootstrap; latest candidate restart and six HTTP route/asset checks returned 200 |

One upstream Starlette/AnyIO deprecation warning remains. Node's NO_COLOR/FORCE_COLOR notices are test-process warnings, not application console failures. No frontend build or typecheck is configured; the shipped vanilla files are exercised in actual Chromium.

[Final machine-readable manifest](docs/evidence/final/manifest.json), [full test log](docs/evidence/final/tests.txt), [browser results](docs/evidence/final/browser-results.json), [clean-start receipt](docs/evidence/final/clean-start.json), [Python audit](docs/evidence/final/pip-audit.json), [npm audit](docs/evidence/final/npm-audit.json).

## 13. Mobile results

| Browser profile | Passed | Deliberate skips | Radar size in default capture | Overflow / undersized controls / console errors |
|---|---:|---:|---:|---|
| 360×800, Android touch | 26 | 2 | 336×336 | 0 / 0 / 0 |
| 393×873, Android touch | 25 | 3 | 359×359 | 0 / 0 / 0 |
| 412×915, Android touch | 25 | 3 | 378×378 | 0 / 0 / 0 |
| 873×393, Android landscape touch | 25 | 3 | 300×300 | 0 / 0 / 0 |
| 1440×1000, desktop | 27 | 1 | 475×475 | 0 / 0 / 0 |

The twelve skips avoid repeating desktop-specific keyboard/focus and selected accessibility coverage in every mobile project, and omit the mobile orientation case on desktop. They are not skipped failing Android regressions.

There was no adb/emulator/Android SDK available. These results use Chromium viewport, Android user-agent and real touch events in emulated mobile contexts. Physical phone, vendor WebView and sustained thermal behavior remain unverified. The priority banner makes the next inspection explicit; no five-second human usability study was performed.

## 14. Performance concerns

The final [ten-target benchmark](docs/evidence/final/performance.json) sampled six seconds per context:

| Measure | 360px touch, 4× CPU throttle | Desktop |
|---|---:|---:|
| Browser task time | 0.118 s | 0.109 s |
| Script time | 0.022 s | 0.021 s |
| Layout time | 0.017 s | 0.015 s |
| Long tasks including load | One, 88 ms | None |
| Runtime errors | 0 | 0 |

Playback renders at a bounded rate and pauses when the page is hidden; histories are bounded. Desktop scripted selections took 18–41 ms. Mobile automation selections took 121–1,452 ms including scroll/actionability overhead, so these are not input-latency measurements. Six seconds and lower sampled heap do not establish absence of a leak or predict phone battery life. A physical lower-end phone soak is the next useful performance gate.

An adversarial 200-record payload returned 184 bounded canonical targets in 261,746 bytes with the truncation flag, rather than an unbounded response. Legacy raw history remains a separate concern.

## 15. Remaining bugs and limits

No unresolved defect was reproduced in the new local demo's acceptance matrix. Known limits remain:

- /legacy retains its original media/mobile and historic state semantics; it is preserved for comparison.
- Sensor data uses the latest bounded observation window, not a persistent multi-sensor track engine. Event idempotency, retention and source-authenticated status lifecycles need a provider contract.
- No PWA/service-worker installation: an already loaded demo survives sensor API loss, but a cold load/reload needs the local web server.
- First dependency installation needs internet. Subsequent demo operation uses only local assets.
- Physical Android and a completed second Claude verdict remain outstanding verification, with the latter scheduled.

## 16. Security concerns

No credentials, tokens, databases or agent transcripts were committed. An independent publication audit inspected all 97 changed paths at bd12dea and 131 new history blobs with presence-only token/private-key/JWT/signed-URL checks: zero hits. JSON fixtures were loopback/QA data; the normalized example is explicitly unverified.

The legacy API intentionally still exposes raw stored records, and webhook ingestion is unauthenticated. Bind loopback by default or use an explicitly trusted local demo network. Public exposure requires authentication/signatures, raw-field protection, retention and rate limits. No public deployment was performed.

The agent runner uses isolated worktrees and bounded processes for collision prevention; an unrestricted same-user model process is not a security sandbox. Paid API key environment variables are removed from job environments. No licence was added; public repository visibility does not establish reuse rights.

## 17. Branches

All implementation branches are recoverable in separate physical worktrees:

- agent/integration — manager candidate.
- codex/android-fix — frontend.
- codex/mobile-regressions — QA.
- codex/demo-boundary — official CLI and supervising backend engineer.
- claude/android-review — completed baseline attack.
- claude/candidate-review — incomplete quota-limited second pass.
- codex/release-review — independent final transition challenges.
- agent/clean-start-check — clean launcher verification.

See [AGENT_BOARD.md](AGENT_BOARD.md) for current handoff. No force push or merge into main occurred.

## 18. Commits

Integration milestones, with original engineering commits retained in their branches:

| Integration commit | Result |
|---|---|
| 18876b8 | Board and official CLI orchestration |
| 8ae0f80 | Failing original mobile regressions and screenshots |
| 2e0a98c | Official Codex ingestion/canonical boundary response |
| bde94da | Simple demo and test launchers |
| 3555aa3 | Independent Claude baseline findings/probes |
| ea34a60 | New deterministic operator view |
| b3023fc | First mobile/accessibility corrections |
| e5eee82 | Provenance, freshness and exact-key response to review |
| 583644e | Conservative ambiguous-object projection |
| 4879f7e | Source tuple identities and long-label bounds |
| b777af2 | Actual HTTP webhook-to-browser acceptance |
| 9a8fa10 | Source names, healthy truncation state and playback wrapping |
| 50d6ce5 | Canonical response/identity bounds and track_id compatibility |
| 1ae4335 | Integrated ingestion evidence and regressions |
| bd12dea | Independent completed-scenario/race/empty-transition tests |
| d198560 | Frozen final screenshot matrix |

`git log --oneline 31a32e1..agent/integration` provides the complete history. Later report/evidence commits do not change the tested application.

## 19. PR and integration status

Draft [PR #1](https://github.com/retinapeg/dronewatch/pull/1) is open from agent/integration to main. The pushed candidate SHA was verified as `56d92d57d0a7d89d1d8dceb9dd3b6a7493f47132`, and [GitHub CI run 34467860351](https://github.com/retinapeg/dronewatch/actions/runs/34467860351) **completed successfully** on that exact head: dependency audit, Python, Node, Android/desktop browser suite and compilation all passed. [The remote receipt](docs/evidence/final/remote-ci.json) records the head SHA and every job step. This report/receipt update is a documentation-only descendant; the tested application is unchanged. Main remains `31a32e1764572837ff43691b50aa3a15bc458714`; no merge, force push or public deployment occurred.

## 20. Exact demo launch command

From this task's checkout:

```bash
cd "/Users/leonardaarons-ditson/Documents/Codex/2026-09-10-you-are-my-autonomous-engineering-manager/dronewatch"
./scripts/demo.sh
```

Open http://127.0.0.1:8000. The manager's inspection server uses http://127.0.0.1:8770 to avoid existing services.

For a fresh candidate checkout after the branch is published:

```bash
git clone --branch agent/integration https://github.com/retinapeg/dronewatch.git
cd dronewatch
./scripts/demo.sh
```

For a phone on the same trusted Wi-Fi, set `DRONEWATCH_HOST=0.0.0.0` when launching and open the computer's LAN IP, not 127.0.0.1, on the phone. Prerequisites and troubleshooting are in [README.md](README.md).

## 21. Exact test commands

One-time browser setup, after the demo has bootstrapped the Python environment:

```bash
npm ci
npx playwright install chromium
```

Complete suite:

```bash
./scripts/test.sh
```

Mobile only: `npm run test:mobile`. Backend and Node only: `./scripts/test.sh --unit`. Playwright starts its own disposable local server by default; using DRONEWATCH_BASE_URL intentionally targets an already-running instance.

## 22. Next five highest-value improvements

1. Complete the scheduled final-candidate Claude attack and record a verdict; reproduce any finding before assigning a fix.
2. Run the same flow on physical mid-range and lower-end Android phones, including a 30-minute foreground/background and rotation soak.
3. Validate a real Viso provider contract and signed/authenticated delivery, then add source-aware lifecycle/idempotency tests without fabricating geographic motion.
4. Protect any future public deployment with authentication, raw-record redaction, retention, rate limits and appropriate host configuration.
5. Test the first five seconds with a few unfamiliar users; use observed errors to refine priority wording, target detail and scroll transitions while retaining the small deterministic scenario.

## Release gate receipt

| Requested criterion | Evidence / disposition |
|---|---|
| Frontend and backend run cleanly | Fresh launcher and HTTP checks; no runtime/resource errors |
| Desktop, 360, 393 and 412px Android/mobile | Full Chromium touch matrix passed; physical device scope explicitly unverified |
| Important controls by touch, no overflow, resizing radar | Regression suite and five-state geometry matrix |
| 3–10 synthetic targets, deterministic replay | Scenario units and full 90-second ten-target browser challenge |
| Immediate hierarchy and understandable selected detail | First-review banner, inspected screenshots, source/uncertainty drilldown |
| Target selection/focus/zoom | Touch tests and every-target completion focus checks |
| Real-event boundary remains intact | Actual POST/SQLite/API/browser and separate TestClient integration |
| Automated and Android regression tests | 78 Python + 24 Node + 128 browser passed |
| Screenshots inspected | Independent QA plus manager review; asset hashes frozen |
| README/startup works | Fresh environment and latest app launch receipt |

The release gate here authorises a credible local synthetic demonstration. It does not authorise public production deployment, calibrated military use or automatic merging of the candidate.
