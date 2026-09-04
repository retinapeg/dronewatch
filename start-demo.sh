#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -x .venv/bin/python ]; then
  DEMO_PYTHON=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  DEMO_PYTHON=python3
else
  printf '%s\n' 'Python is missing. Use the prepared local virtual environment.' >&2
  exit 1
fi
if ! "$DEMO_PYTHON" -c 'import fastapi, uvicorn, httpx' >/dev/null 2>&1; then
  printf '%s\n' 'Missing local dependencies. Prepare the environment with: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt' 'The demo launcher never downloads anything.' >&2
  exit 1
fi
export DRONEWATCH_ENABLE_INTEGRITY_EXPERIMENT=0
export DRONEWATCH_LIVE_ENABLED=0
PORT="${PORT:-8000}"
printf '\nDRONEWATCH READY\nOPEN: http://127.0.0.1:%s\nMODE: SYNTHETIC DEMO\n\nPress RUN DRONE DEMO. Ctrl+C stops the server.\n\n' "$PORT"
exec "$DEMO_PYTHON" -m uvicorn main:app --host 127.0.0.1 --port "$PORT" --workers 1 --timeout-graceful-shutdown 3 --no-access-log
