# DroneWatch

DroneWatch is a local airspace-awareness demonstration with a deterministic small synthetic scenario and a separate event-inspection view. It runs on phones and desktop browsers using the same FastAPI server. There are no external fonts, map tiles, video feeds or APIs in the default demo.

**The default scenario is synthetic.** Positions, priorities, courses and confidence values are authored fixtures. They are not live radar measurements, evidence of hostile intent or output from a trained classifier. The project does not implement interception, targeting or engagement.

## Launch the demo

Requires Python 3.11+ and a modern Chromium-based browser. Node.js 24+ is needed for development/browser tests, not to serve the demo.

```bash
git clone https://github.com/retinapeg/dronewatch.git
cd dronewatch
./scripts/demo.sh
```

Open <http://127.0.0.1:8000>. The launcher creates a local `.venv` and installs Python dependencies if needed. **Internet is needed for first dependency installation; subsequent demo runs work without internet.** Ctrl+C stops the server.

If port 8000 is occupied:

```bash
DRONEWATCH_PORT=8080 ./scripts/demo.sh
```

To open the demo on an Android phone connected to the same trusted Wi-Fi network:

```bash
DRONEWATCH_HOST=0.0.0.0 ./scripts/demo.sh
```

Open `http://<your-computer-LAN-IP>:8000` on the phone. `127.0.0.1` on a phone means the phone itself. The computer must remain awake and its firewall must allow the port. Use a trusted local demo network: the preserved prototype ingestion API is unauthenticated. Do not expose it through a public tunnel or deploy it as a public production service.

## The operator flow

1. The page opens in **Demo mode** with five synthetic targets. The review banner identifies the first target to inspect.
2. Tap a marker or a target in the register. Its status, illustrative confidence, scripted course and uncertainty appear in Selected target.
3. Use **Focus selected target** to enlarge the selected area; **Show all targets** restores the overview.
4. Pause, resume or reset the deterministic 90-second scenario. The target-count control switches between 3, 5 and 10.
5. Expand **Source & interpretation** for evidence and alternative interpretations. “Unknown” means insufficient evidence; movement style is not treated as proof of a weapon or decoy.
6. Switch to **Sensor mode** to inspect stored event records. This mode never puts camera detections on a fabricated geographical radar map.

Reset uses the same fixture positions and values every time. The browser owns scenario playback, so a sensor API outage cannot interrupt the synthetic demo. A local server is still required to load/reload the application; this is not a service-worker/PWA offline installation.

## Architecture

```text
Browser fixture producer (assets/scenario.js)
    -> common target fields + synthetic provenance
    -> operator renderer (assets/operator.js)

Viso-shaped / test / other webhook payload
    -> POST /webhook/viso
    -> bounded input validation + conservative normalization
    -> SQLite incident history
    -> GET /api/targets (safe target projection)
    -> operator renderer in sensor mode
```

- **Frontend:** vanilla HTML, CSS and JavaScript. SVG draws schematic geometry and paths; HTML controls keep labels and touch areas readable at phone sizes. No frontend build step.
- **Backend:** Python/FastAPI/Uvicorn, with SQLite. `main.py` owns routes and storage; `target_schema.py` projects stored records.
- **Canonical fields:** target/event identity, source and provenance, status and its basis, confidence, nullable position/velocity/heading, source time, evidence, uncertainty and alternative interpretation. Both producers use this target shape; only the synthetic producer supplies authored trajectories.
- **Source honesty:** unauthenticated webhook content cannot establish genuine Viso connectivity. Missing or invalid observation timestamps must not appear current because the server recently returned a response. Raw payloads are excluded from `/api/targets`.
- **Legacy view:** `/legacy` preserves the original dashboard for comparison and the original helper tests. It retains historical limitations and is outside the new operator-view acceptance gate.

## Routes

| Route | Purpose |
| --- | --- |
| `GET /` | Default synthetic operator demo |
| `GET /?mode=sensor` | Sensor event view, including empty/failure states |
| `GET /assets/...` | Same-origin frontend resources |
| `GET /health` | Backend readiness |
| `GET /api/config` | Development simulation availability |
| `GET /api/targets` | Canonical projection used by the new UI |
| `GET /api/events` | Preserved legacy event history API, including raw payloads |
| `POST /webhook/viso` | Preserved prototype webhook ingress |
| `POST /dev/simulate` | Stored test events, disabled by default |
| `GET /legacy` | Original frontend, for historical comparison |

## Backend and frontend startup separately

The frontend has no separate dev server requirement. FastAPI serves HTML/assets and APIs together, avoiding CORS and phone-localhost dependencies.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Configuration:

| Variable | Meaning |
| --- | --- |
| `DRONEWATCH_PORT` | Launcher port; default 8000 |
| `DRONEWATCH_HOST` | Launcher interface; default 127.0.0.1 |
| `DRONEWATCH_PYTHON` | Optional Python executable for scripts |
| `DRONEWATCH_DB_PATH` | SQLite path; launcher defaults to `.local/demo.db` |
| `DRONEWATCH_SIMULATION` | Set to `1` to enable stored `/dev/simulate` events; the browser demo does not require it |

Relative database paths resolve from the repository. Tests use disposable SQLite databases. Do not place credentials or real customer media in Git.

## Tests and evidence

Install browser test dependencies once:

```bash
npm ci
npx playwright install chromium
```

Run Python, JavaScript and all browser checks:

```bash
./scripts/test.sh
```

Useful focused commands:

```bash
./scripts/test.sh --unit
npm run test:mobile
npm run test:browser
.venv/bin/python -m pytest -q
npm test
```

Playwright starts a disposable local server automatically. `DRONEWATCH_BASE_URL=http://127.0.0.1:8000` instead tests an already-running instance. The browser suite covers 360×800, 393×873, 412×915, 873×393 landscape and 1440×1000 desktop, with real touch events in mobile contexts. It exercises target selection/focus, pause/reset, 3/10 targets, orientation, malformed/empty/stale data, delayed responses, outages/recovery, keyboard focus and accessibility.

These are desktop Chromium tests with Android viewport/touch emulation; they do not certify a particular physical phone, Android WebView or battery profile. See [Playwright’s emulation documentation](https://playwright.dev/docs/emulation). Browser reports/traces are written to ignored `test-results/` and `playwright-report/`. Original failing screenshots and regression evidence are retained under [docs/evidence/baseline](docs/evidence/baseline/README.md).

A local performance sample, with the demo server running:

```bash
DRONEWATCH_BASE_URL=http://127.0.0.1:8000 node scripts/benchmark-demo.cjs
```

This records Chromium task/layout time, bounded DOM observations and selection timings at ten targets, including a 4× CPU-throttled mobile viewport. These are browser measurements, not physical phone CPU/battery claims.

## Real-event integration

The Viso path remains available for mocked and future provider-specific events. Its current customer-configured JSON normalizer is a prototype, not a verified universal Viso webhook specification. Unit and browser fixtures establish local boundary behavior only. No live Viso account delivery, authentication/signature contract, actual sensor calibration or end-to-end cloud processing was verified in this milestone.

The optional `demo_feed.py` and `start-drive-copy.command` media-copy workflow remains separate from the default demo. See [DATA_SOURCES.md](DATA_SOURCES.md) and [DEMO_FEED.md](DEMO_FEED.md) for its original scope. Copying files or playing local video does not prove Viso processing or webhook delivery.

## Troubleshooting

- **Address already in use:** choose another `DRONEWATCH_PORT`; do not stop unrelated services.
- **Phone cannot connect:** use the computer’s LAN IP, the same Wi-Fi and the LAN bind command above. Check the host firewall and keep the computer awake.
- **Sensor list is empty:** that is expected without stored events. Use Demo mode for the self-contained scenario.
- **Sensor feed unavailable:** cached observations are explicitly marked; retry runs automatically. Demo mode remains independent.
- **Playwright browser missing:** run `npx playwright install chromium`; Linux CI uses `--with-deps`.
- **Python imports fail:** use the repository `.venv` or set `DRONEWATCH_PYTHON` to the intended environment; install `requirements.txt`.
- **Original video unavailable in `/legacy`:** that historical page required a separate local video process. Use `/` for the new dependency-free browser scenario.

## Engineering workflow

[AGENT_BOARD.md](AGENT_BOARD.md) records the current mission, branches, findings and integration decisions. [docs/engineering/WORKFLOW.md](docs/engineering/WORKFLOW.md) documents the working official Claude Code/Codex CLI runner, isolation and adversarial review process. The repository has no software licence; public visibility does not establish third-party reuse rights.
