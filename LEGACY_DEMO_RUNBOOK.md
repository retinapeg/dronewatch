# DroneWatch demo runbook

Independent prototype. Do not imply Parliament endorsement, deployment or official
affiliation. No official crests or branding. This is monitoring and awareness,
not a safety-certified airspace-control or counter-drone system.

## Before the room opens

1. Keep the existing Viso connector, SQLite database and Cloudflare tunnel intact.
2. From the repository run `./start-demo.sh`, unless port 8000 is already serving the app.
3. Open http://127.0.0.1:8000/ and reload once if an older tactical dashboard is cached.
4. Confirm BACKEND ONLINE, a current SENSOR EVENT number, and the stored-observation count.
5. Treat SOURCE STALE honestly: it means no recent genuine Viso webhook, not an app crash.
6. Choose BENCHMARK REPLAY for a deterministic offline demonstration. Its watermark must stay visible.
7. Press Reset demo just before speaking. This restarts replay but preserves SQLite history.

First installation requires Python 3.11+ recommended, a virtual environment and
`pip install -r requirements.txt`. No model, credentials or external service is
needed for the bundled replay. No frontend build is needed. Use one server worker.

## Expected screen

- Header: DroneWatch, source selector, UTC/local clock, Reset demo.
- Status: latest backend event ID distinct from the genuine Viso freshness indicator.
- KPIs: active tracks, confirmed sightings, open warnings, event age or replay time.
- Main stage: 16:9 measured/annotated image coordinates, never a fabricated radar map.
- Right: track ID, state, confidence when supplied, first/last seen, duration and zone.
- Bottom: newest-first lifecycle events with source/severity filters and raw payload disclosure.
- Footer: backend, stream, source and last-update health. A degraded stream can use polling.

For Viso's currently saved payload there are no measured boxes. Expect a sighting-only
view with no invented spatial track. Numeric confidence is absent when Viso provides
only a qualitative label. The latest stored observation may be SIMULATED or TEST;
that does not make it a genuine Viso event.

For bundled replay expect a synthetic annotation stage, not real drone footage.
One track is confirmed after three observations; a second appears around seven
seconds. The first enters the configured image-space zone around 8.6 seconds.
There is a short detection gap; identity is retained. Lost and ended events follow
later. The 18-second sequence loops and resets its own counters. Ground-truth
annotations have no invented model confidence. All viewers share replay controls.

## Ninety-second demonstration

1. **0-15 seconds, VISO LIVE:** "DroneWatch is an independent airspace-awareness prototype. Viso supplies visual detections; our backend preserves the original observations and gives operators a usable event history. This connection indicator reflects genuine recent webhook activity, not a video playing on a loop."
2. **15-30 seconds:** Open the raw genuine Viso event. "This source reports a sighting but not measured image coordinates. We retain that evidence without inventing a trajectory, range, altitude or intent."
3. **30-60 seconds, BENCHMARK REPLAY, Reset demo:** "This is a recorded benchmark replay, using a clearly labelled synthetic annotation fixture. Watch one identity persist across frames and a brief missed detection. The count increments on confirmation, not every frame. A configured image-space zone produces an operational warning. These annotations are not live model inference."
4. **60-80 seconds:** Pause, point at tracks and timeline. "DroneWatch converts raw frame-level detections into persistent tracks and operationally useful events. It separates detection, tracking and alert logic so different camera and model providers can be substituted without replacing the operator interface."
5. **80-90 seconds:** "Viso already supplies genuine webhook observations. A local detector is an optional adapter when compatible weights are supplied. The prototype still needs field validation, production security and robust multi-camera tracking before deployment."

## Reset / replay controls

**Reset demo** clears transient tracks, alerts and counters and restarts benchmark
replay if it is selected. Stored observations and the latest backend ID remain.
**PAUSE** stops replay time. **PLAY** resumes. **RESTART** starts the sequence from
the beginning with a fresh tracker. **LOOP** repeats the recorded sequence.
Switch back to VISO LIVE to inspect preserved original source records.

For a reviewed annotated video, set `DRONEWATCH_REPLAY_PATH` before startup using
the fixture's manifest format and a matching local `video`. Never overlay this
synthetic fixture on unrelated MQ-9 footage. See README for the exact boundary.

## Optional local detector

Do not install or train a model minutes before the presentation. If a compatible
model is already available, install `requirements-inference.txt`, set
`DRONEWATCH_MODEL_PATH`, `DRONEWATCH_LOCAL_SOURCE` and optionally
`DRONEWATCH_INFERENCE_STRATEGY=full`, then restart the app and press START MODEL in
LOCAL INFERENCE. Sources can be a local MP4, webcam index or RTSP URL. Missing
weights/dependencies should produce a clear message, not break Viso/replay.
This path has not been validated against a supplied drone model in this workspace.

## Offline fallback

The bundled benchmark sequence works without network access, a video download or
model dependencies. Use the existing virtual environment and localhost dashboard.
Select BENCHMARK REPLAY and Reset demo. Keep the recorded-replay watermark visible
and say explicitly that the bundled input is synthetic annotations, not footage.
The database history remains available offline. Viso appropriately becomes stale.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| No new events | Check `/health` and `/api/events`; inspect the backend terminal for incoming payloads. Preserve the working Viso/tunnel configuration. Replaying a local video alone cannot generate a genuine webhook. |
| Frontend stale | Reload once after upgrading static files. Compare SENSOR EVENT #N with `latest.id` from `/api/events`. Thereafter SSE and cache-busted two-second polling update without reload. |
| Event stream offline | Polling should continue. Cloudflare Quick Tunnels do not support SSE; this is an expected reason to use polling. Prefer localhost for the on-stage display. |
| BACKEND CONNECTION LOST | Keep the page open; restart the same app on port 8000. Polling/reconnect resumes automatically. Do not delete the database. |
| Source disconnected/stale | This is separate from backend health. Use the honestly labelled replay until genuine source activity resumes. |
| No boxes or video for Viso | The payload may not include measured boxes or a publicly accessible media URL. Sighting-only is correct, not a missing radar plot. |
| Model unavailable | Use Viso or replay; supply existing compatible weights and optional dependencies only when time allows. No automatic download or training is performed. |
| Replay unavailable | Check the configured manifest against the supplied sample. Unset `DRONEWATCH_REPLAY_PATH` and restart to use the built-in fixture. |
| Port 8000 occupied | Check `curl http://127.0.0.1:8000/health` first; the app may already be running. Do not kill unrelated processes. Use `PORT=8002 ./start-demo.sh` only for a separate offline instance, not by silently changing Viso's target. |
| Counts differ from old open incidents | Old `/api/events.open_count` counts event records. New track counts count confirmed spatial identities. They are intentionally different; simulations are not genuine live tracks. |

## Fast terminal checks

```sh
curl -fsS http://127.0.0.1:8000/health
curl -fsS 'http://127.0.0.1:8000/api/events?limit=10'
curl -fsS 'http://127.0.0.1:8000/api/console?mode=VISO_LIVE'
curl -N --max-time 12 'http://127.0.0.1:8000/api/stream?mode=VISO_LIVE'
```

The last command intentionally times out after showing a snapshot and heartbeat;
that timeout is not a stream failure. Do not post fake events to the genuine Viso
webhook merely to make SOURCE ONLINE. Use the explicitly SIMULATED development
controls if demonstrating ingestion without the real sensor.

## Known boundaries

- No trained drone model or matching annotated MQ-9 video is bundled.
- Live Viso data without boxes is sighting-level only; textual locations are not plotted.
- IoU-centroid tracking is a small fallback, not validated ReID or multi-camera identity.
- Image-space zones are not geographic airspace/geofences or legal flight boundaries.
- The app is a single-process demo with transient tracking and SQLite event persistence.
- Controls and event APIs are unauthenticated; do not treat the existing public tunnel as production security.
- Quick Tunnel polling updates at two seconds; benchmark animation is smoother locally over SSE.
- Model capture/inference, RTSP reliability and full annotated-video synchronization need real-source validation.
- Dataset tools validate known VOC structure; Anti-UAV requires a reviewed sample before implementation.
- Existing FastAPI startup/shutdown hooks emit deprecation warnings; they remain functional.
