# Demo implementation plan

Initial state: clean main branch; created demo/parliament-tracking-ui. Existing
FastAPI + SQLite ingestion, vanilla HTML/JS, pytest and Node's built-in tests.
No tracker, OpenCV, Ultralytics, frontend build, lint or type configuration exists.
SQLite backup: ../work/dronewatch-before-tracking.sqlite3. No GitHub push planned.

The stale-view bug was source preference rather than missing backend events.
Always follow the latest database ID; merge stream and poll deliveries by that ID,
never by class/category. Current events API fields are status, latest,
open_incidents, open_count, events and received_at. Preserve them all.

The saved genuine Viso example (row 6) contains application/incident metadata,
labels, qualitative high confidence, textual approximate_position and OUTSIDE
zone_state. It has no measured bbox, frame dimensions or absolute media URL.
Keep it as a sighting; remove the old schematic radar/derived trajectory.

1. Add pure domain normalization and an isolated per-camera IoU/constant-velocity
   tracker with configurable confirmation, confidence smoothing and lost/end states.
2. Notify a thread-safe SSE hub after SQLite commit, support cursor catch-up and
   heartbeat, retain two-second cache-busted polling and explicit reconnect backoff.
3. Add independent transient live, replay and optional local-inference state.
   Keep reset separate from permanent source data. Default replay is a small,
   explicitly synthetic saved annotation sequence, not an accuracy benchmark.
4. Replace the schematic radar with a 16:9 evidence/annotation panel, explicit
   source modes, track details, filtered lifecycle/source logs and system health.
5. Add optional detector/strategy adapters, VOC/YOLO dataset tools and a runbook.
6. Run Python/JS tests, HTTP and browser smoke checks, then commit locally using
   the requested commit message. Report optional dependency and real-data limits.
