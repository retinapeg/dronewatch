# Independent Codex follow-up probes

10 September 2026. Reviewed application/report candidate `f9c59adb92efd8ce4c088c508bf9e973cfddc62a` from clean isolated branch `codex/followup-check`, origin `https://github.com/retinapeg/dronewatch.git`. The board, report and existing browser tests were read first. No production code was changed and no defect was reproduced in these two additional probes.

## Executable results

`scripts/probe-followup-transitions.cjs` exited **0**, with two passing probes and no page runtime errors:

1. **An observation ages while selected and expanded.** At a fixed clock start, an unchanged source observation was 118 seconds old and displayed Recent observation. After running six seconds of browser timer callbacks, a second identical response left the same `FOLLOWUP-AGE` target selected and its Source & interpretation panel expanded, while the displayed freshness changed to Stale observation. The response receipt timestamp stayed constant. This extends the existing static-stale and polling-persistence checks with an actual age-threshold transition.
2. **Playback crosses real browser visibility states.** An isolated Chromium tab at 360px selected DW-03, expanded Source & interpretation and enabled 1.7x focus. A second tab generated a real `hidden` visibility event at scenario `00:00`. The scenario remained `00:00` after 3.5 seconds hidden. Returning to the first tab generated `visible` at `00:00`, and the scenario reached `00:01` after 1.25 seconds. Selection, expansion and focus survived. A subsequent CDP touch on Show all targets returned the view to OVERVIEW. Runtime errors: zero.

The first normal Playwright tab attempt kept both pages visible because Playwright enables focus emulation. Sending a false focus override through an additional CDP session did not undo the primary session's override. Those attempts were **harness limitations, not application failures**. The successful probe uses an independent Chromium process/profile with `connectOverCDP({noDefaults:true})` on its default context. The installed Playwright types explicitly document that this option disables its focus override. `document.hidden` is not replaced or mocked. A headed exploratory attempt also closed before completing; no product conclusion was drawn from it. The final reproducible command runs headless Chromium with actual visibility events and checks their values before testing playback.

These are browser-level checks, not physical Android, OS suspension, battery or long-duration soak evidence. The second probe uses 360px Chromium plus a real CDP touch event after returning; it does not assert that an Android app switch was performed.

## Reproduction

From this worktree, install the already-pinned Node dependencies with `npm ci`. The manager's Python environment was reused read-only:

```bash
DRONEWATCH_DB_PATH=/tmp/dronewatch-followup-check-8828.sqlite3 DRONEWATCH_SIMULATION=0 \
  ../dronewatch/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8828
```

In another terminal, from the same worktree:

```bash
node scripts/probe-followup-transitions.cjs
```

`DRONEWATCH_BASE_URL` can select another loopback-only local server. The age-transition response is intercepted with an explicit review fixture; the script does not insert observations into the server database. Chromium diagnostics go to the ignored `.runtime/visibility-chromium.stderr`. The final verified stdout and stderr are in this worktree's ignored `.runtime/followup-final.jsonl` and `.runtime/followup-final.stderr`. The owned 8828 server was stopped after the probes.

No broader suite was repeated because these probes did not change application code. The existing acceptance receipt remains the baseline suite evidence.
