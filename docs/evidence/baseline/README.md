# Original application: independent mobile baseline

Captured 10 September 2026 from unmodified `31a32e1764572837ff43691b50aa3a15bc458714`, branch `codex/mobile-regressions`, repository `https://github.com/retinapeg/dronewatch.git`. The QA worktree was clean before adding this harness. The original application ran through the integration worktree's Python virtual environment:

```sh
../dronewatch/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8011
npm ci
npx playwright install chromium
npm run test:baseline
DRONEWATCH_BASE_URL=http://127.0.0.1:8011 DRONEWATCH_TEST_REPORT=docs/evidence/baseline/regression-results.json npx playwright test mobile-regressions
```

Runtime: Node 26.8.1, npm 11.19.0, Playwright 1.63.0, Chromium 153.0.8010.12 on macOS ARM64. Android tests emulate viewport, Android Chrome user agent and touch input. They do **not** represent a physical Android device, Android GPU, thermal performance, or installed Chrome version.

The first screenshot at each size uses the original application and its real empty SQLite database, with `simulation_enabled=false`. Subsequent `controls` and `scenario` captures override only the `/api/config` response to expose the existing browser scenario for touch auditing. Those scenario events stay in the browser. The source code and ingestion data are unmodified.

## Confirmed results

| Viewport | Document width | Initial page height | Scenario target ID rendered size | Scenario state rendered size | Regression result |
|---|---:|---:|---:|---:|---|
| 360 × 800 | 360 | 1656 | 5.07 px | 3.72 px | 3 failed |
| 393 × 873 | 393 | 1630 | 5.56 px | 4.08 px | 3 failed |
| 412 × 915 | 412 | 1627 | 5.85 px | 4.29 px | 3 failed |
| 873 × 393 landscape | 873 | 680 | 6.66 px | 4.89 px | 3 failed |
| 1440 × 1000 desktop | 1440 | 1000 | 12.32 px | 9.03 px | 3 failed |

All **15 regression tests fail on the original application**, with no retries. The failures are actual existing defects, not merely absent proposed features:

1. **Unreadable radar labels.** The fixed `viewBox="0 0 1000 520"` scales 9–15px SVG fonts to roughly 3–6 screen pixels on phones. Measuring `getComputedStyle(...).fontSize` alone conceals the failure; tests multiply font size by the SVG screen transform. The mobile target and boundary labels are visibly microscopic.
2. **Undersized touch controls.** The evidence summary is 25–26px high, feed retry 33px, demo controls summary 20–21px and scenario buttons 33px. These fail the agreed 44px hit-area requirement. Existing controls could be tapped in automation when enabled, but the hit areas remain too small for normal touch use.
3. **Failed media dependency.** Every viewport requests `http://127.0.0.1:8001/mq9-reaper.mp4`, receives `net::ERR_CONNECTION_REFUSED`, logs a console error and displays DEMO VIDEO UNAVAILABLE. On a remotely viewing phone, this address refers to the phone itself. The ordinary app startup does not serve this resource.

Additional visual findings: the 360px scenario log clips the SIMULATED / LOCAL badge at the panel's right edge; landscape displays the live-pipeline badge across part of the feed retry button; the fixed-height contact panel requires its own nested scrolling to reach evidence. The default app hides the only local scenario controls behind the server simulation flag, so an unconfigured clean start shows no targets and no available demo entry point. The old scenario shows one contact, not the requested small swarm, and has no tap-to-select radar target or focus control.

**No document horizontal overflow was reproduced at any tested size. No JavaScript runtime exception or event API failure was observed in this clean baseline.** The missing media generated resource/console errors. These distinctions matter: the root causes are not a blanket absence of CSS breakpoints.

## Evidence

`measurements.json` retains widths, heights, transformed font sizes, touch-control dimensions, failed request URLs and console messages. `regression-results.json` is the full machine-readable failed run. `*-initial.png`, `*-controls.png` and `*-scenario.png` cover all five viewports. The 360px scenario, 393px initial, 412px controls, landscape scenario and desktop scenario screenshots were visually inspected.

The capture script intentionally targets the old baseline. For the new operator interface use `npm run test:browser`; its screenshots and traces are written under `test-results/`, and the HTML report under `playwright-report/`. Browser regressions retain the original three failure checks and add touch operator flows and failure cases.


## Claude independent baseline probes

`claude_attack_baseline.py` preserves Claude Code's exact baseline-oriented adversarial tests from `2f62e63` (originally `tests/claude_attack_test.py`). Run it explicitly only against the original `31a32e1` checkout. Its original expectations and strict expected-failure markers document that baseline; they are not part of the current release test suite. Accepted fixes have ordinary passing regression tests under `tests/`, including `test_claude_semantics.py`. The full independent findings and final baseline counts are in `docs/engineering/claude-baseline.md`.
