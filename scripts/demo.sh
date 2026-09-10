#!/usr/bin/env bash
# One server, same-origin assets/API, no Viso or external services needed.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

if [[ -n "${DRONEWATCH_PYTHON:-}" ]]; then
  python_bin="$DRONEWATCH_PYTHON"
else
  python_bin="$repo_dir/.venv/bin/python"
  if [[ ! -x "$python_bin" ]]; then
    command -v python3 >/dev/null || { echo "Python 3.11+ is required." >&2; exit 1; }
    python3 -m venv "$repo_dir/.venv"
  fi
fi

"$python_bin" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
if ! "$python_bin" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "Installing Python dependencies (internet required on first setup)."
  "$python_bin" -m pip install -r "$repo_dir/requirements.txt"
fi

export DRONEWATCH_DB_PATH="${DRONEWATCH_DB_PATH:-$repo_dir/.local/demo.db}"
export DRONEWATCH_SIMULATION="${DRONEWATCH_SIMULATION:-0}"
listen_host="${DRONEWATCH_HOST:-127.0.0.1}"
listen_port="${DRONEWATCH_PORT:-8000}"
case "$listen_port" in
  ''|*[!0-9]*) echo "DRONEWATCH_PORT must be an integer between 1 and 65535." >&2; exit 2 ;;
esac
if (( 10#$listen_port < 1 || 10#$listen_port > 65535 )); then
  echo "DRONEWATCH_PORT must be between 1 and 65535." >&2
  exit 2
fi

echo "DroneWatch synthetic demo: http://$listen_host:$listen_port"
echo "The browser scenario works without Viso. Ctrl+C stops the server."
if [[ "$listen_host" == "0.0.0.0" ]]; then
  echo "For your phone, use this computer's LAN IP in the URL (same Wi-Fi)."
  echo "The prototype webhook is unauthenticated; use a trusted demo network."
fi
exec "$python_bin" -m uvicorn main:app --host "$listen_host" --port "$listen_port"
