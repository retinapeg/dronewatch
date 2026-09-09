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

## HTTP endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Tactical dashboard (`index.html`). |
| `GET` | `/health` | Liveness check. Returns status and server time only. |
| `GET` | `/api/events` | Stored events, newest first. `limit` defaults to 20 and is clamped to 200. Returns the derived `status`, `latest`, and `open_incidents`. |
| `GET` | `/api/config` | Reports whether stored simulation is enabled. |
| `POST` | `/webhook/viso` | Accepts any JSON payload, normalizes it, and stores it. Always returns `{"status": "ok"}`. |
| `POST` | `/dev/simulate` | Stores a labelled synthetic event. Body: `{"scenario": "detected"}`, `"restricted"`, or `"left"`. Returns 404 unless `DRONEWATCH_SIMULATION=1`. |

All endpoints are unauthenticated. `GET /api/events` returns stored raw payloads
verbatim, so treat it as sensitive. See [Internet exposure](#internet-exposure).

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

## V0.2 preview

A browser preview that replays the synthetic multi-sensor scenarios from the M2
generator. The V0.1 dashboard at `/` is unchanged.

```bash
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/preview>. It loads `mixed_threat_decoy` seed 42
by default; press PLAY. Everything shown is synthetic, generated from a fixed
seed, and is labelled as such. No fusion, tracking or classification algorithm
exists in this build, so the preview displays supplied observations only and
draws no tracks.

If port 8000 is occupied, pass any free port, for example `--port 8010`.

### Connecting Viso Now

External ingestion is disabled unless a secret is configured, while the
synthetic preview keeps working either way.

```bash
DRONEWATCH_WEBHOOK_SECRET='<your-secret>' \
  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

| Variable | Purpose |
| --- | --- |
| `DRONEWATCH_WEBHOOK_SECRET` | Enables `POST /v2/webhook/viso`. Unset means external ingestion is off. |
| `DRONEWATCH_WEBHOOK_HEADER` | Header carrying the secret. Default `X-DroneWatch-Token`. |
| `DRONEWATCH_MAX_BODY_BYTES` | Streaming body ceiling. Default 1048576. |

The secret may be sent either in that header or as `?token=...`, because Viso
Now's supported authentication headers are not documented publicly and must be
confirmed against your own account. Prefer the header; the URL token is redacted
from the access log, but a header keeps it out of intermediate proxy logs too.

`127.0.0.1` is not reachable from the internet. Reaching this endpoint from Viso
requires an authenticated HTTPS ingress you control, terminating at
`/v2/webhook/viso` only.

The V0.1 `POST /webhook/viso` route keeps its original unauthenticated
behaviour. Only the new `/v2` route is protected, and only a delivery through it
can change the connection panel's state.

## Documentation

- [DATA_SOURCES.md](DATA_SOURCES.md) — sensor and data-source research.
- [ROADMAP.md](ROADMAP.md) — V0.1 delivery roadmap.
- [docs/V0.2_PANOPTES_ROADMAP.md](docs/V0.2_PANOPTES_ROADMAP.md) — V0.2 defeat-chain
  simulation roadmap, milestones, and the required synthetic-data workstream.
- [docs/V0.2_ARCHITECTURE.md](docs/V0.2_ARCHITECTURE.md) — proposed V0.2 architecture,
  domain model, and the SAPIENT integration boundary.
- [data/synthetic/README.md](data/synthetic/README.md) — synthetic dataset contract.

## Repository notes

- `index.html` is intentionally frozen while the event and sensor contracts are
  designed and validated.
- The repository has no software licence yet. Do not infer third-party reuse
  rights from its public visibility.
- Viso workflow configuration, account state, demo footage, credentials, and
  any sensor hardware remain external to this repository.
