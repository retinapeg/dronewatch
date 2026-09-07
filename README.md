# DroneWatch

DroneWatch is an evidence-aware prototype for receiving visual-analysis events,
storing them, and presenting incident awareness in a tactical dashboard. The
current visual integration is built around **Viso Now** file processing. Radar,
RF, live camera ingestion, sensor fusion, and model training are not implemented
yet.

> Current maturity: prototype. It is not a calibrated radar, a certified
> counter-UAS system, or proof of live airspace coverage.

## What exists today

- FastAPI webhook receiver at `POST /webhook/viso`.
- SQLite event history and `GET /api/events`.
- Tactical dashboard served at `/`.
- Explicitly labelled browser-only and stored simulation modes.
- A local MP4 server and optional Google Drive watched-folder replay helper.
- Python and JavaScript tests.

The dashboard's radar-style view is schematic. It does not contain measured
range, bearing, speed, heading, or geographic position. The local video panel is
independent of the Viso webhook path; playing a video does not prove Viso
processed it.

Viso Now currently documents discrete image/video processing rather than a
continuous live stream. Google Drive polling can support a near-real-time file
replay, but it must not be described as a live camera feed. See
[DATA_SOURCES.md](DATA_SOURCES.md) and [ROADMAP.md](ROADMAP.md).

## Run locally

Requires Python 3.11+ and Node.js 24+ for the full test suite.

```bash
git clone https://github.com/retinapeg/dronewatch.git
cd dronewatch
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>.

Stored simulation is disabled by default. Enable it only for a supervised local
demo:

```bash
DRONEWATCH_SIMULATION=1 .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Optional configuration:

- `DRONEWATCH_DB_PATH`: SQLite path. Relative values resolve from the repository.
- `DRONEWATCH_SIMULATION`: set to `1` to enable `POST /dev/simulate`.
- `DRONEWATCH_DRIVE_FOLDER`: existing local folder watched by Viso Now.
- `DRONEWATCH_DEMO_SOURCE`: source MP4 used by `start-drive-copy.command`.
- `DRONEWATCH_PYTHON`: Python executable used by `start-drive-copy.command`.

## Viso Now file replay

The source media is deliberately not stored in Git. Use only footage that you
own or are licensed to process and demonstrate.

```bash
.venv/bin/python demo_feed.py \
  --source '/absolute/path/to/demo.mp4' \
  --watch-dir '/absolute/path/to/Viso watched folder' \
  --interval 25
```

This serves the selected video on loopback for the local dashboard and copies a
complete, uniquely named file into the watched folder every 20–30 seconds. It
does not verify Google Drive sync, Viso processing, or webhook delivery. Stop it
with Ctrl+C. Completed copies are retained, so use a bounded supervised session
and clean up the watched folder manually when appropriate.

See [DEMO_FEED.md](DEMO_FEED.md) for the exact behavior.

## Test

Run all checks from the repository root:

```bash
.venv/bin/python -m pytest -q
node --test tests/dashboard.test.cjs
.venv/bin/python -m compileall -q main.py demo_feed.py
```

The same checks and a dependency audit run in GitHub Actions.

## Internet exposure

The current webhook and event API are unauthenticated, and the event API returns
stored raw payloads. Do not expose this version as a persistent public service.
A temporary tunnel may be used only for a supervised integration test where the
URL is treated as sensitive and the process is stopped immediately afterward.
Authentication, request limits, deduplication, and sanitized API projections are
release gates in the roadmap.

## Repository notes

- `index.html` is intentionally frozen while the event and sensor contracts are
  designed and validated.
- The repository has no software licence yet. Do not infer third-party reuse
  rights from its public visibility.
- Viso workflow configuration, account state, demo footage, credentials, and
  any sensor hardware remain external to this repository.
