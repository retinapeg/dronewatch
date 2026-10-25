# DroneWatch

Visual intelligence for restricted-airspace awareness. An independent monitoring
prototype, not a safety-certified system or an official parliamentary deployment.
No affiliation, endorsement, hostile-intent inference, range or altitude claims.

The working integration remains:

```text
Video -> Viso -> POST /webhook/viso -> FastAPI -> SQLite -> operator dashboard
                                               |-> SSE + 2-second polling
                                               |-> isolated transient tracking
```

Viso remains the visual sensor. Optional local inference and clearly labelled
recorded replay sit alongside it; neither replaces the webhook or rewrites its
stored observations.

## Start in one command

From this repository, with its virtual environment already installed:

```sh
./start-demo.sh
```

Open http://127.0.0.1:8000/. Stop with Ctrl+C. The server binds to loopback and uses
one worker. `PORT=8002 ./start-demo.sh` selects a different local port, but do not
change the working webhook/tunnel target during the demo.

First-time setup (Python 3.11+ recommended):

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./start-demo.sh
```

Equivalent command:

```sh
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

For code development only, append `--reload`. There is no frontend package install
or production bundler: HTML, CSS and vanilla JavaScript are served directly.
Existing local validation also runs on the available Python 3.9.6 environment;
this is not a claim that a new Python 3.11 environment was installed or tested.

## Three honest source modes

### VISO LIVE

The current database is shown immediately. `SENSOR EVENT #N` always follows the
latest backend ID, including clearly attributed test and simulation events.
Every webhook record remains a separate observation, even when multiple records
classify the same category. Retransmission of the same database ID via SSE and
polling does not create duplicate UI rows.

Genuine Viso connectivity is a separate freshness indicator: it requires Viso
application/incident metadata, no simulation/test marker, and a received timestamp
within 120 seconds. Video playback, a healthy backend, and simulated events cannot
make Viso online. This is event freshness, not a direct Viso connection probe.

The saved genuine payload contains qualitative confidence and a textual position,
not measured boxes or image dimensions. It therefore stays a sighting-level event.
No positions, trajectory, percentage confidence, identity, range, altitude or
restricted-zone intrusion are invented from prose. Viso-relative media paths are
not turned into guessed public URLs. The event timeline exposes original JSON.

### BENCHMARK REPLAY

Select **BENCHMARK REPLAY**. The bundled 18-second deterministic sequence starts
playing, with play/pause, restart and loop controls. It is a **synthetic annotation
fixture**, not an MQ-9 detector, not footage, and not an accuracy benchmark. Both
the stage and source header permanently say **RECORDED BENCHMARK REPLAY**.

Expect two persistent tracks during the sequence, one configured image-space zone
entry, temporary missed observations, and lost/ended lifecycle events. Confirmed
sightings count track confirmation, not frames. Confidence is absent for ground
truth. Restart/loop resets that replay's transient tracker.

To use your own local annotated video or saved sequence, author a reviewed manifest
following `samples/synthetic_replay.json`, then start with:

```sh
DRONEWATCH_REPLAY_PATH="$PWD/data/interim/my-replay.json" ./start-demo.sh
```

The `dronewatch.replay.v1` manifest declares image width/height, duration, camera,
ordered timestamped frames and detections with explicit `bbox_format`. Optional
`video` is resolved relative to the manifest; it must refer to an existing local
file. Supply real annotations for that exact video and coordinate system. Set
`synthetic` honestly. A zone is optional and is an explicitly configured normalized
image-space polygon, not a geographic boundary. Use the fixture as the canonical
field-name example. Invalid manifests leave the base application functional and
report replay unavailable. Only that configured video can be served; the route
does not accept arbitrary user-supplied filesystem paths.

### LOCAL INFERENCE (optional)

The base install does not include OpenCV, Ultralytics, weights, or dataset downloads.
Without a compatible local model, this mode displays an explicit unavailable
message; Viso and benchmark replay remain functional.

Only install this optional stack if you already have time and a compatible model:

```sh
.venv/bin/python -m pip install -r requirements-inference.txt
DRONEWATCH_MODEL_PATH="$PWD/models/drone.pt" \
DRONEWATCH_LOCAL_SOURCE="$HOME/Downloads/mq9-reaper.mp4" \
DRONEWATCH_INFERENCE_STRATEGY=full \
./start-demo.sh
```

Select **LOCAL INFERENCE**, then **START MODEL**. Use **STOP** before changing the
source. `DRONEWATCH_LOCAL_SOURCE=0` selects a webcam; an RTSP URL is also accepted
by the optional OpenCV capture adapter. Keep credentials in local environment
variables, not committed scripts. Existing weights are required; no model download
is initiated. `DRONEWATCH_LOCAL_LOOP=1` loops MP4 capture and resets its tracker.
The default allowed classes are drone/uav/quadcopter; use
`DRONEWATCH_LOCAL_CLASSES` only if supported by your model adapter configuration.
Model output is neither ground truth nor a trained-accuracy claim. Review the
model's license and class mapping before any public use.

The strategy interface supports `full`, `sliced` and `candidate`. Full-frame is the
default. Sliced inference is bounded to 16 tiles and falls back to a full frame
rather than silently ignoring the rest of an oversized image. Candidate inference
uses padded recent regions plus periodic full-frame detection; it is an extension
point, not a validated motion detector. No appearance/ReID dependency is added.

## Tracking and reset

`domain.py` separates detections, tracks and alerts. `tracking.py` implements an
isolated per-source/per-camera IoU-centroid association fallback, with constant
velocity for association only. It draws observed coordinates, not predicted
positions. It is replaceable through a tracker interface; it is not ByteTrack.

Defaults can be overridden before startup:

| Environment variable | Default |
| --- | --- |
| `DRONEWATCH_CONFIRMATION_COUNT` | 3 |
| `DRONEWATCH_CONFIRMATION_WINDOW` | 5 |
| `DRONEWATCH_LOSS_TIMEOUT` | 1 second |
| `DRONEWATCH_END_TIMEOUT` | 4 seconds |
| `DRONEWATCH_ASSOCIATION_THRESHOLD` | 0.1 IoU |
| `DRONEWATCH_CENTROID_THRESHOLD` | 0.12 normalized distance |
| `DRONEWATCH_HISTORY_LENGTH` | 20 observed centroids |
| `DRONEWATCH_CONFIDENCE_ALPHA` | 0.25 |

`DRONEWATCH_ZONES_JSON` can map actual camera IDs to normalized polygon vertices.
Do not configure geographic coordinates here. Slow event-only sources should use
appropriate loss/end thresholds; they do not behave like a frame-rate detector.

**Reset demo** clears transient tracks, alerts and counters, and restarts replay
if selected. It does not delete SQLite observations. Consequently the stored total
and latest sensor event ID do not reset to zero. State is shared by all viewers
in this single demo process. Use one worker, not multiple Uvicorn workers.

## Existing and added API routes

- `POST /webhook/viso`: unchanged arbitrary-JSON ingestion, raw logging and persistence.
- `GET /api/events`: existing fields preserved; `total_count` adds the full SQLite count.
- `GET /health` and `GET /api/config`: existing health and development configuration.
- `POST /dev/simulate`: existing simulated scenarios, never genuine Viso activity.
- `GET /api/stream?mode=VISO_LIVE`: SSE snapshots, observations, console state, heartbeats.
- `GET /api/console?mode=VISO_LIVE`: transient tracking/source snapshot.
- `GET /api/sources`: source availability and optional-model reason.
- `POST /api/demo/reset`: JSON `{"mode":"BENCHMARK_REPLAY"}` or another mode.
- `POST /api/replay/control`: JSON `{"action":"play","loop":true}`; also pause/restart.
- `GET /api/replay/video`: the configured replay video only, with byte-range support.
- `POST /api/local/start`, `POST /api/local/stop`, `GET /api/local/frame`: optional model.

Valid API modes: `VISO_LIVE`, `BENCHMARK_REPLAY`, `LOCAL_INFERENCE`.
SSE accepts `Last-Event-ID` or `after_id`; SQLite supplies missing observations.
Heartbeat interval is 10 seconds. Client retry grows from 1 to 30 seconds. The
watchdog reconnects stale streams. Polling remains active every 2 seconds using
`?t=...` and `cache: "no-store"`, including when streaming is unavailable.

## Public webhook / existing Cloudflare setup

Do not replace a working Viso connector or running tunnel during the demo. For a
fresh development tunnel, with `cloudflared` already installed:

```sh
cloudflared tunnel --url http://localhost:8000
```

Use the printed host plus `/webhook/viso`, for example
`https://xxxxx.trycloudflare.com/webhook/viso`. The URL changes when a Quick Tunnel
is recreated. Quick Tunnels do not support SSE; the two-second polling fallback is
intentional. See [Cloudflare's Quick Tunnel limitations](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).

This is an unauthenticated development console, not a hardened public service.
The existing tunnel exposes routes beyond the webhook, including raw event data
and demo controls. Do not share its URL indiscriminately or enable a private
webcam/RTSP source through a publicly accessible console. Authentication, webhook
verification, access restrictions and retention policy are production follow-ups,
not silently changed integration settings in this demo patch.

## Continuous MQ-9 feed helper

The existing `demo_feed.py`, `DEMO_FEED.md` and watched-folder copying workflow are
preserved. The helper never modifies the original video and stops with Ctrl+C.
Run `.venv/bin/python demo_feed.py --help` for its existing options. Playback alone
is not genuine Viso activity. This new console does not put synthetic annotation
boxes over unrelated MQ-9 footage; use matching recorded annotations or the
optional model adapter when displaying spatial tracks on that video.

## Dataset preparation (no automatic downloads)

See `data/README.md`. Originals belong in `data/raw`, intermediate frames in
`data/interim`, and processed output in `data/processed`; generated files and
model weights are ignored by git.

Maciullo Pascal VOC data can be converted after you acquire it under its license.
The converter accepts standard VOC XML, not an assumed archive layout. First
validate the actual class names, dimensions, images and annotations:

```sh
.venv/bin/python tools/dataset.py validate-voc \
  --annotations data/raw/maciullo/annotations --images data/raw/maciullo/images

.venv/bin/python tools/dataset.py voc-to-yolo \
  --annotations data/raw/maciullo/annotations --images data/raw/maciullo/images \
  --class drone --output data/interim/maciullo-yolo --every-n 2
```

Repeat `--class` for each real class in desired class-ID order; replace `drone` if
the labels use a different name. Unknown classes are errors, not silently relabelled.
Standard one-based inclusive VOC coordinates are the default. If your exporter
uses zero-based half-open coordinates, explicitly pass `--coordinate-origin 0`.
Output is normalized `class x_center y_center width height`, as specified in
[Ultralytics dataset documentation](https://docs.ultralytics.com/datasets/detect/).

Validation reports missing image/annotation pairs, unreadable PNG/JPEG dimensions,
XML/image size mismatches, invalid/negative/out-of-bounds boxes, class counts and
empty labels. Empty labels are reported as background-image warnings, not erased.
Header validation is not a full image decode/corruption audit. Conversion stops on
errors before writing labels. `--every-n` subsamples sorted annotation files.

Extract frames without modifying a local annotated source video:

```sh
.venv/bin/python -m pip install -r requirements-data.txt
.venv/bin/python tools/dataset.py extract-frames \
  --video data/raw/flight.mp4 --output data/interim/flight \
  --every-n 10 --limit 300
```

`frames.csv` records the original frame index, video identity and timestamp when
FPS is available. Extraction does not invent annotations. Join the actual source
labels using the retained frame index, respecting that dataset's indexing convention.

Fill the converter's `manifest.csv` with the real `source_video` for every row.
Never guess video identity from adjacent frame filenames. Then split whole videos:

```sh
.venv/bin/python tools/dataset.py split \
  --manifest data/interim/maciullo-yolo/manifest.csv \
  --output data/processed/maciullo --train-fraction 0.8 --seed 42
```

At least two videos are required. A video is assigned wholly to train or validation;
no adjacent-frame random split is used. The output copies selected images/labels
into standard `images/train`, `labels/train`, `images/val`, `labels/val` directories
and writes split lists/provenance. Choose a fresh output directory for each run.
Review source identity yourself: incorrect input group metadata can still leak data.
No training job is started.

No Anti-UAV sample labels are present. `AntiUAVAdapter` is only a documented
interface; `tools/dataset.py anti-uav` deliberately fails with a clear requirement
for a sample label file. Supplying a file does not enable an invented parser: its
schema must be reviewed before a concrete adapter is implemented.

## Tests and validation

```sh
.venv/bin/python -m pytest -q
node --test tests/dashboard.test.cjs
node --check static/core.js
node --check static/app.js
sh -n start-demo.sh
```

Tests are deterministic, local and model-free. The video-server test binds an
ephemeral localhost port, so restricted execution environments must allow local
sockets. Browser tests exercise transport/store logic using Node's built-in runner;
manual browser smoke checks cover actual rendering and source controls. No lint or
type-check configuration or frontend build step is present in this small stack.

See `DEMO_RUNBOOK.md` for the live presentation sequence and failure recovery.
