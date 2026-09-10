#!/usr/bin/env bash
# DroneWatch demo: operator view + live Viso Now ingestion with synthetic data.
#
#   ./scripts/demo_viso.sh                          # generated synthetic feed
#   ./scripts/demo_viso.sh --drive-file  <fileId>   # pull from a shared Drive file
#   ./scripts/demo_viso.sh --drive-folder <id> --drive-key <apiKey>
#
# Everything goes through the real authenticated webhook. Nothing is faked.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8010}"
SECRET_FILE=".viso-demo-secret"          # git-ignored
[ -f "$SECRET_FILE" ] || openssl rand -hex 16 > "$SECRET_FILE"
SECRET="$(cat "$SECRET_FILE")"

# Reuse a running server ONLY if OUR secret actually authenticates against it.
# Checking "configured: true" is not enough: a server may already be running
# with a different secret, which fails every delivery with 401 mid-demo.
running=0
probe=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 \
  -X POST "http://127.0.0.1:$PORT/v2/webhook/viso" \
  -H "content-type: application/json" -H "X-DroneWatch-Token: $SECRET" \
  -d '{"probe":"secret-check"}' 2>/dev/null || echo 000)
# 200 = accepted (and quarantined, as an unrecognised shape should be).
# 401 = a different secret is in force, so restart. 000/503 = not usable.
[ "$probe" = "200" ] && running=1

if [ "$running" -eq 0 ]; then
  echo "==> starting DroneWatch on 127.0.0.1:$PORT with the webhook enabled"
  pkill -f "uvicorn main:app" 2>/dev/null || true
  sleep 1
  DRONEWATCH_WEBHOOK_SECRET="$SECRET" nohup .venv/bin/uvicorn main:app \
    --host 127.0.0.1 --port "$PORT" > /tmp/dronewatch-demo.log 2>&1 &
  disown
  for _ in $(seq 1 30); do
    sleep 1
    curl -sf "http://127.0.0.1:$PORT/preview" >/dev/null 2>&1 && break
  done
else
  echo "==> reusing the server already running on :$PORT"
fi

echo "==> Viso status before"
curl -s "http://127.0.0.1:$PORT/api/preview/viso/status" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   ", d["state"], "| deliveries:", d["delivery_count"])'

echo
echo "==> feeding the scenario's Viso camera detections through the authenticated webhook"
echo "    (the same synthetic detections that re-localise lost tracks in the"
echo "     'Radar off 30 s + Viso visual detection' mode; plus one unrecognised payload)"
.venv/bin/python scripts/viso_feed.py \
  --secret "$SECRET" --url "http://127.0.0.1:$PORT/v2/webhook/viso" \
  --source scenario --from-t 40 --to-t 70 --interval 0.15 "$@"
.venv/bin/python scripts/viso_feed.py \
  --secret "$SECRET" --url "http://127.0.0.1:$PORT/v2/webhook/viso" \
  --count 1 --include-unmapped --interval 0 >/dev/null 2>&1 || true

echo
echo "==> Viso status after"
curl -s "http://127.0.0.1:$PORT/api/preview/viso/status" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(f"    {k:16} {d[k]}") for k in ("state","delivery_count","mapped_count","unmapped_count","last_outcome")]'

cat <<TXT

Open:
  operator view   http://127.0.0.1:$PORT/preview
                  Sensor loss -> "Radar off 30 s + Viso visual detection", Play 4x,
                  pause ~T+58, click a LOST row. VISO chip top-right for the panel.
  legacy board    http://127.0.0.1:$PORT/
  diagnostics     http://127.0.0.1:$PORT/preview/diagnostics

Webhook:  POST http://127.0.0.1:$PORT/v2/webhook/viso
Header:   X-DroneWatch-Token: $SECRET
TXT
