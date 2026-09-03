# DroneWatch

Backend-first webcam incident monitor for Viso webhook events.

## Run locally

```bash
cd /Users/leo/Documents/Codex/2026-09-03/yes-that-is-the-right-architecture/dronewatch
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open: http://localhost:8000

## Cloudflare tunnel (public webhook URL)

From project root:

```bash
cd /Users/leo/Documents/Codex/2026-09-03/yes-that-is-the-right-architecture/dronewatch
cloudflared tunnel --url http://localhost:8000
```

The command returns a URL like:
`https://xxxxx.trycloudflare.com`. Use:
`https://xxxxx.trycloudflare.com/webhook/viso`

## Endpoints

- `POST /webhook/viso` — accepts any JSON payload from Viso and stores it.
- `GET /` — dashboard.
- `GET /api/events` — latest events.
- `GET /health` — service health.
- `POST /dev/simulate` — development-only synthetic events with body: `{ "scenario": "detected" | "restricted" | "left" }`.

## Tests

```bash
pytest -q
```
