# Offline presentation demo

Run `PORT=8010 ./start-demo.sh` in this directory. No downloads, npm, external media,
models, or network services are required. The prepared `.venv` is already present.
Keep the verified presentation on http://127.0.0.1:8010 and this checkout.

Use RESET, RUN DRONE DEMO, AIRCRAFT, BIRD, and FULLSCREEN. The drone sequence is
35 seconds: detection at 3, acquisition at 6, approach at 8, warning at about
25.19, and restricted entry at 32. It holds at 35 seconds. Aircraft takes 24
seconds and remains outside both zones; bird takes 18 seconds and remains non-UAS.
Each button starts a fresh scenario. Reset returns to airspace clear.

The FastAPI process owns the clock, positions, classifications, telemetry, alerts,
and event log. The frontend interpolates received positions only. It freezes and
shows a disconnected banner if the backend stops. The EO scene is procedural SVG.
All measurements and confidence scores are synthetic scenario values, not trained
model results. Coordinates use metres with X east, Y north and Z up. The scripted
drone's speed is about 73.4 m/s to cover this 2.4 km approach in the short stage
sequence; it is not a claim about a specific aircraft's performance.

API: POST `/api/demo/start` with `{"scenario":"drone"}`, `"aircraft"`, or `"bird"`;
POST `/api/demo/reset` without a body; GET `/api/demo/state`. An optional
POST `/api/demo/pause` toggles pause, but is not shown in the presentation.
Explicit legacy reset bodies such as `{"mode":"VISO_LIVE"}` retain their previous
behavior. Demo runs do not write or delete stored observations.

Existing code, original stage UI, earlier integrations and legacy APIs are
preserved. The root route serves `final-demo.html`; it does not load legacy media,
live-provider code, or any cloud API. Run one Uvicorn worker only.

Validation:

```sh
.venv/bin/python -m pytest -q
node --test tests/dashboard.test.cjs tests/final-demo.test.cjs
.venv/bin/python tools/final_demo_smoke.py http://127.0.0.1:8010
```

The final smoke command takes about two minutes and runs all three scenarios,
then the drone a second time. It verifies geometry, transitions, stable IDs,
final-state holds and unchanged permanent records against the running server.

Validation recorded on 4 September 2026: 73 Python tests and 19 JavaScript tests
passed. The real-time server rehearsal completed drone → aircraft → bird → drone
with final-state holds and an unchanged observation database. Browser access
disconnected during visual QA, so final fullscreen and both requested viewport
checks still require a manual check. The presentation server was left on port
8010 to avoid interrupting existing servers on 8000 and 8001.
