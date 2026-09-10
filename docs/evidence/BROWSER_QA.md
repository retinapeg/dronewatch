# Independent browser QA

The original baseline is recorded under `baseline/`, including 15 failing executable regressions and screenshots. The replacement frontend was then exercised through a separate static server at `http://127.0.0.1:8013`, using real Chromium with Android user agent, viewport and touch emulation. Sensor responses were mocked through Playwright's network routing. Backend ingestion and an integrated server release run are separate checks.

## Development review results

| Run | Passed | Failed | Intentionally skipped | Elapsed |
|---|---:|---:|---:|---:|
| Original mobile regressions | 0 | 15 | 0 | See baseline JSON |
| First replacement-frontend pass | 59 | 8 | 8 | 35.9 s |
| Second replacement-frontend pass | 78 | 0 | 12 | 35.6 s |

The replacement was under active development during these two passes. These reports prove the identified failures and subsequent passing behaviours; the release gate must additionally run against a stable integrated commit. The frontend engineer subsequently identified `2d8652e` as the stable candidate, following `a7dfee3`.

The first replacement pass found three remaining issues:

- Radar north/corner annotations still rendered at 7–9px. They now have a 10px minimum.
- Landscape pause/reset buttons were only 29.59px and 30.25px wide. They now meet a 44px minimum width.
- Panel-index labels had a measured contrast ratio of 4.32:1. Their colour was adjusted, and the automated WCAG A/AA scan passed at 360px and desktop.

Independent screenshot and geometry review found two further usability defects:

- The highest-priority target's original 15-second projected path was only 11.54 screen pixels at 360px. Both endpoints lay beneath the selected marker's 50 × 54px opaque background. The revised interface shows the **remaining authored scenario route to 01:30**, labels it as scripted, and rotates direction arrows to the authored course. A regression now proves the route extends beyond the selected marker.
- A focused sensor-detail summary lost keyboard focus on the next poll: the active element changed from `SUMMARY` to `BODY` while the panel remained expanded. The rendering fix preserves focus and expansion; the regression waits for a second actual mocked API response before checking both.

The roster also claimed priority ordering while placing priority 4 before priority 3. The fixture producer now returns the authored priority order.

## Covered behaviour

The final suite schedules 90 project/test combinations across 360 × 800, 393 × 873, 412 × 915, 873 × 393 landscape and 1440 × 1000 desktop. It executes 78 checks with 12 deliberate skips: axe runs only at 360px and desktop; keyboard focus checks run only on desktop; orientation runs only for mobile projects.

Coverage includes readable radar geometry, document overflow, touch areas, normal console/resource cleanliness, five-target selection, actual bounded 1.7× focus, pause/reset/resume determinism, three/ten-target scenarios, rotation, external-internet failure, page reload, visible authored routes, sensor empty state, stale event time despite a fresh server response, malformed payloads, backend outage/recovery preserving selection, late response cancellation after a mode change, supported `?mode=sensor` deep links, and keyboard focus during updates.

```sh
npm ci
npx playwright install chromium
npm run test:browser
# Against an already running application:
DRONEWATCH_BASE_URL=http://127.0.0.1:8000 npm run test:browser
```

The checked-in JSON reports retain individual results and errors. Generated traces/screenshots live under `test-results/`; the generated browser report lives under `playwright-report/`.

This is **desktop Chromium Android emulation, not physical Android verification**. It does not establish real-phone GPU/thermal behaviour, Android browser UI effects, or OS-level network policy. Local offline testing blocks external requests while keeping the local application server reachable; it does not claim the app loads when that server is unreachable.
