# Independent candidate release review

Verdict: **no additional release-blocking defect reproduced** in this bounded review. The candidate passes the three added state-transition challenges across all five configured browser projects. This is an independent Codex review; it is not a completed second Claude Code review.

## Identity and scope

- Tested application commit: `1ae4335309c45f990efc63c8a9e7bf4e6aa0e062`.
- Branch: `codex/release-review`; isolated physical worktree `dronewatch-release-review`.
- Verified origin: `https://github.com/retinapeg/dronewatch.git`; initial worktree clean.
- Read frontend/backend engineering evidence, Claude's baseline criticisms, actual application source, and the change set from `31a32e1`.
- No application code changed. This commit adds acceptance tests, their execution report, two inspected screenshots, and this verdict.

The manager is responsible for the final integrated release gate and clean-start verification. This pass independently tests selected transitions and executes the complete Python/Node suites; it does not claim to repeat every earlier browser check.

## Challenges and executable outcome

| Challenge | Risk tested | Result |
|---|---|---|
| Run all 90 seconds with ten targets, focus each target, then replay | Completion could freeze playback; a newly selected target could remain offscreen in an old focus camera; replay could lose selection | Passed on all five projects. All ten selected markers were visible and geometrically contained in the radar. Zero document overflow. Replay advanced to 00:01 while preserving DW-10. No page errors. |
| Sensor → demo → sensor while the original request is held | An old request might overwrite a newer sensor generation or leave Refresh disabled | Passed on all five projects. CURRENT remains selected after OBSOLETE is released, Refresh is enabled, and a receipt-only record says Observation time unverified. |
| Empty response after selecting and expanding an observation | Removed observation or evidence might linger, or the priority action might silently point at stale data | Passed on all five projects. Record and evidence disappear, priority action is disabled, empty-state guidance appears, and switching back to demo restores five synthetic targets. |

The scenario test uses Playwright `clock.runFor`, executing every timer callback. `fastForward` would skip intermediate callbacks and would not exercise the production playback loop faithfully. The sensor races use controlled HTTP responses; they do not represent credential-backed Viso service calls.

Relevant implementation inspected: `assets/operator.js:235` request generation guards, `assets/operator.js:264` completion replay, `assets/operator.js:282` bounded playback, and `target_schema.py:164` canonical projection fields. The shared contract retains source kind, unknown physical quantities and separate observation/receipt time.

## Commands and actual results

Server, started in this isolated worktree with a throwaway SQLite database:

```bash
DRONEWATCH_DB_PATH=/tmp/dronewatch-release-review.sqlite3 \
  ../dronewatch/.venv/bin/python -m uvicorn main:app \
  --host 127.0.0.1 --port 8816
```

Checks:

```bash
npm ci
../dronewatch/.venv/bin/python -m pytest -q
npm test
DRONEWATCH_BASE_URL=http://127.0.0.1:8816 \
  npx playwright test tests/browser/release-transitions.spec.cjs --workers=3
git diff --check
```

- Dependency installation: succeeded, zero npm audit vulnerabilities reported.
- Python: **78 passed**, one existing Starlette/AnyIO deprecation warning, 4.24 seconds. No skips.
- JavaScript: **24 passed**, zero failures or skips.
- Browser: **15 passed**, zero failures or skips, 18.3 seconds. Projects: Android touch emulation at 360×800, 393×873, 412×915, 873×393, and desktop at 1440×1000.
- Whitespace check: passed.

Raw browser results: [`browser-results.json`](../evidence/release-review-1ae4335/browser-results.json).

Manually inspected the completed ten-target DW-10 focus screenshots at [360px](../evidence/release-review-1ae4335/android-360-completed-focus.png) and [landscape](../evidence/release-review-1ae4335/android-landscape-completed-focus.png). The selected target, focus label, completion controls, selected detail, synthetic provenance and full ten-target register are present. The full page scrolls normally; focus intentionally hides out-of-view markers while preserving every target in the register.

## Findings and limits

No new high, medium or low production defect was demonstrated by these checks. There is no invented disagreement, failed-before claim, or production patch in this review.

Known scope boundaries remain: Chromium Android/touch emulation is not physical-handset proof; this review does not benchmark sustained handset CPU/GPU use or older WebViews. Canonical ingestion is a local prototype boundary with unverified webhook provenance; public authentication, raw-payload protection on legacy routes, real Viso delivery, calibrated airspace coordinates and certified classification remain outside the local demo acceptance. No public deployment, main merge or push was performed.
