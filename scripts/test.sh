#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
python_bin="${DRONEWATCH_PYTHON:-$repo_dir/.venv/bin/python}"
if [[ ! -x "$python_bin" ]] && ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Python environment missing. Run ./scripts/demo.sh once to set it up." >&2
  exit 1
fi
if [[ "${1:-}" != "" && "${1:-}" != "--unit" ]]; then
  echo "Usage: ./scripts/test.sh [--unit]" >&2
  exit 2
fi
"$python_bin" -m pytest -q
"$python_bin" -m py_compile main.py demo_feed.py
if [[ -f target_schema.py ]]; then
  "$python_bin" -m py_compile target_schema.py
fi
npm test
if [[ "${1:-}" != "--unit" ]]; then
  export DRONEWATCH_PYTHON="$python_bin"
  npm run test:browser
fi
