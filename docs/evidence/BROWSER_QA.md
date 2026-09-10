# Independent browser QA

The original baseline is recorded under `baseline/`, including 15 failing executable regressions and screenshots. The replacement frontend was then exercised through a separate static server at `http://127.0.0.1:8013`, using real Chromium with Android user agent, viewport and touch emulation. Sensor responses were mocked through Playwright's network routing. Backend ingestion and an integrated server release run are separate checks.

## Development review results

| Run | Passed | Failed | Intentionally skipped | Elapsed |
|---|---:|---:|---:|---:|
| Original mobile regressions | 0 | 15 | 0 | See baseline JSON |
| First replacement-frontend pass | 59 | 8 | 8 | 35.9 s |
| Second replacement-frontend pass | 78 | 0 | 12 | 35.6 s |
| Integrated candidate on port 8770 | 88 | 0 | 12 | 39.0 s |

The replacement was under active development during these two passes. These reports prove the identified failures and subsequent passing behaviours; the release gate must additionally run against a stable integrated commit. The frontend engineer subsequently identified `2d8652e` as the stable candidate, following `a7dfee3`.

The first replacement pass found three remaining issues:

- Radar north/corner annotations still rendered at 7–9px. They now have a 10px minimum.
- Landscape pause/reset buttons were only 29.59px and 30.25px wide. They now meet a 44px minimum width.
- Panel-index labels had a measured contrast ratio of 4.32:1. Their colour was adjusted, and the automated WCAG A/AA scan passed at 360px and desktop.

Independent screenshot and geometry review found two further usability defects:

- The highest-priority target's original 15-second projected path was only 11.54 screen pixels at 360px. Both endpoints lay beneath the selected marker's 50 × 54px opaque background. The revised interface shows the **remaining authored scenario route to 01:30**, labels it as scripted, and rotates direction arrows to the authored course. A regression now proves the route extends beyond the selected marker.
- A focused sensor-detail summary lost keyboard focus on the next poll: the active element changed from `SUMMARY` to `BODY` while the panel remained expanded. The rendering fix preserves focus and expansion; the regression waits for a second actual mocked API response before checking both.

The roster also claimed priority ordering while placing priority 4 before priority 3. The fixture producer now returns the authored priority order.

The integrated pass additionally tested 256-character identifiers, long source text and literal HTML in evidence without overflow or script execution. It sent mocked Viso-shaped payloads through **real FastAPI TestClient ingestion, temporary SQLite storage and canonical target normalization**, then displayed the actual normalized responses in Chromium. Missing source timestamps stayed unverified, old explicit timestamps stayed stale, zero frame coordinates were preserved, and unauthenticated webhook metadata remained labelled `WEBHOOK_EVENT`. This isolated test makes no writes to the running server's database.

After that passing run, screenshot review found `Resume` and `Reset` splitting across lines at 393px. The existing playback test was strengthened and failed on the pre-fix integrated candidate; see `integrated-validation/transport-before.json`. The frontend engineer supplied fix `622a55c`. The final integrated run must include that fix and the new assertion before claiming completion.

## Covered behaviour

This QA branch's current suite schedules 100 project/test combinations across 360 × 800, 393 × 873, 412 × 915, 873 × 393 landscape and 1440 × 1000 desktop. It executes 88 checks with 12 deliberate skips: axe runs only at 360px and desktop; keyboard focus checks run only on desktop; orientation runs only for mobile projects. Other engineers' separately owned integration/source-identity tests add to the complete merged suite.

Coverage includes readable radar geometry, document overflow, touch areas, normal console/resource cleanliness, five-target selection, actual bounded 1.7× focus, pause/reset/resume determinism, three/ten-target scenarios, rotation, external-internet failure, page reload, visible authored routes, sensor empty state, stale event time despite a fresh server response, malformed payloads, backend outage/recovery preserving selection, late response cancellation after a mode change, supported `?mode=sensor` deep links, and keyboard focus during updates.

```sh
npm ci
npx playwright install chromium
npm run test:browser
# Against an already running application:
DRONEWATCH_BASE_URL=http://127.0.0.1:8000 npm run test:browser
```

The checked-in JSON reports retain individual results and errors. Generated traces/screenshots live under `test-results/`; the generated browser report lives under `playwright-report/`.

The 25 screenshots in `candidate-7083a12/` show default five-target mode, selected focus, three targets, ten targets and an explicitly mocked empty sensor response at every viewport. The frontend was `2d8652e`; backend integration advanced while the capture ran, so these are candidate visual evidence, not a frozen release build. Their measurements show document width equal to viewport width at every captured state, no controls below 44px, and no console/runtime errors. Visual inspection covered the 360px overview, 393px focus, 412px ten-target view, landscape three-target view, desktop overview and 360px empty sensor view. The 393px screenshot is the evidence for the later playback-label fix.

Regenerate the complete screenshot matrix with:

```sh
DRONEWATCH_BASE_URL=http://127.0.0.1:8000 DRONEWATCH_EVIDENCE_DIR=test-results/operator-evidence node scripts/capture-operator-evidence.cjs
```

When running this harness from a separate QA worktree, set `DRONEWATCH_SOURCE_ROOT` to the application checkout and `DRONEWATCH_PYTHON` to its Python executable so isolated ingestion tests exercise that exact source.

This is **desktop Chromium Android emulation, not physical Android verification**. It does not establish real-phone GPU/thermal behaviour, Android browser UI effects, or OS-level network policy. Local offline testing blocks external requests while keeping the local application server reachable; it does not claim the app loads when that server is unreachable.
