# Frozen-build visual verification

Captured on 10 September 2026 from `http://127.0.0.1:8770` at **`bd12deae27cb2c160a26a04f8c905f628208f7fd`**. Repository HEAD remained at that revision after capture. SHA-256 hashes of the served HTML and all three frontend assets match that exact commit; see `source-verification.json`.

The matrix contains 25 full-page screenshots: five viewports, each showing the default five-target scenario, selected target focus, three targets, ten targets and a mocked empty sensor feed. Scenario screenshots are paused at `00:00`, with reduced motion enabled for stable capture. No application files were changed.

| Viewport | Default radar size | States captured | Horizontal overflow | Controls below 44px | Console/runtime errors |
|---|---:|---:|---:|---:|---:|
| 360 × 800 | 336 × 336 | 5 | 0 | 0 | 0 |
| 393 × 873 | 359 × 359 | 5 | 0 | 0 | 0 |
| 412 × 915 | 378 × 378 | 5 | 0 | 0 | 0 |
| 873 × 393 landscape | 300 × 300 | 5 | 0 | 0 | 0 |
| 1440 × 1000 desktop | 475 × 475 | 5 | 0 | 0 | 0 |

Visual inspection covered every viewport family and every state family: `android-360-default-five.png`, `android-393-selected-focus.png`, `android-412-10-targets.png`, `android-landscape-selected-focus.png`, `desktop-default-five.png`, `android-360-empty-sensor.png` and `desktop-3-targets.png`. The target hierarchy, authored routes, selected-target detail and focus controls are visible and coherent. The empty feed has zero targets and does not substitute synthetic positions.

The previously broken 393px playback labels are corrected. `android-393-playback-controls.png` provides a close-up; the measured `Resume` and `Reset` labels each occupy exactly one text line (`playback-label-verification.json`).

`measurements.json` retains geometry, selected target IDs, counts, scenario time and errors for every captured state. The manager is running the complete merged test suite separately; no duplicate full-suite run was performed for this capture task.

These captures use **desktop Chromium with Android viewport, user-agent and touch emulation**, not a physical Android device. They do not establish Android hardware/GPU/thermal performance.

Reproduction from the application checkout:

```sh
DRONEWATCH_BASE_URL=http://127.0.0.1:8770 DRONEWATCH_EVIDENCE_DIR=docs/evidence/release DRONEWATCH_CANDIDATE=bd12dea node scripts/capture-operator-evidence.cjs
```
