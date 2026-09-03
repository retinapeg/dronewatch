# Tactical dashboard

Open http://localhost:8000. The existing FastAPI process serves index.html
directly. The page polls the unchanged events API every two seconds.

- Full screen uses the browser full-screen API.
- Demo controls is collapsed in the footer, gated by the existing API's
  simulation_enabled setting.
- Run demo scenario shows CLEAR, DETECTED, APPROACHING, RESTRICTED ZONE and
  EXITED, with 3.2 seconds between steps. Local scenario events never enter
  SQLite. Return to sensor ends the scenario. A new genuine Viso event
  interrupts the scenario automatically.
- The three development API buttons preserve the simulation endpoint and
  store events marked SIMULATED.
- Select a local video for manual, muted playback, marked DEMO SOURCE VIDEO.
  It is never uploaded and remains independent of sensor events.
- Expand operations log rows for the raw payload and historical observation
  selection. Follow latest returns to the sensor observation.

## Display semantics

State and severity come directly from the existing API. Raw payloads supplement
confidence, position, track identity, zone state and media. Qualitative confidence
is retained as qualitative, never converted to a percentage. Unknown does not
mean clear airspace.

Without a sensor track ID, TRK identifiers are display aliases for events grouped
by source/application. Active tracks counts these groups, not verified aircraft.
Open incidents preserves the API count of non-EXITED records within its last 200
events, including test and simulation records.

Radar rings and the zone boundary are schematic and uncalibrated. Supplied frame
coordinates and understood bounding boxes are used where possible. Text positions
are displayed verbatim and placed approximately; missing positions use a labelled
state-derived position. This is not geographic tracking. No speed, distance or
heading is invented. The sweep is decorative.

Viso provenance requires non-simulated application/incident metadata or a Viso
incident URL. Default source=VISO alone is insufficient. This is payload provenance,
not authentication. ONLINE means an event within 120 seconds. STALE does not
invent a track exit. Webhook RECEIVED indicates a stored delivery, while event-feed
connectivity is reported separately.

Only supplied absolute HTTP(S) media URLs are loaded. Relative mediaLink values
remain references, with an incident link where provided. Simulation placeholder
URLs are never shown as sensor evidence.

## Checks

Run existing Python tests from the parent of the dronewatch package:

```sh
python -m pytest -q dronewatch/tests/test_main.py
```

Run presentation-data tests from the dronewatch directory:

```sh
node --test tests/dashboard.test.cjs
```

Pre-UI checkpoint: b66c6a9. Consistent SQLite backup:
../work/dronewatch-before-tactical.sqlite3. Runtime data is excluded from Git.
