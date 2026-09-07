#!/bin/bash
set -eu

dronewatch_folder="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
scenario_id="${DRONEWATCH_SCENARIO_ID:-}"
run_id="${DRONEWATCH_RUN_ID:-}"
fixture_id="${DRONEWATCH_FIXTURE_ID:-}"
manifest_file="${DRONEWATCH_FIXTURE_MANIFEST:-$dronewatch_folder/fixtures/halmstad-selection.v1.json}"
source_media="${DRONEWATCH_DEMO_SOURCE:-}"
watched_folder="${DRONEWATCH_DRIVE_FOLDER:-}"
copy_count="${DRONEWATCH_COPY_COUNT:-}"
copy_interval="${DRONEWATCH_COPY_INTERVAL:-25}"
record_dir="${DRONEWATCH_RUN_RECORD_DIR:-$dronewatch_folder/run-records}"
python_bin="${DRONEWATCH_PYTHON:-$dronewatch_folder/.venv/bin/python}"

if [[ ! -x "$python_bin" ]]; then
  python_bin="$(command -v python3)"
fi

if [[ -z "$scenario_id" ]]; then
  printf 'Scenario ID (letters, digits, dot, underscore, hyphen): '
  IFS= read -r scenario_id
fi

if [[ -z "$run_id" ]]; then
  printf 'Unique run ID (must not already have a run record): '
  IFS= read -r run_id
fi

if [[ -z "$fixture_id" ]]; then
  printf 'Fixture ID from the selected manifest: '
  IFS= read -r fixture_id
fi

if [[ -z "$source_media" ]]; then
  printf 'Exact manifest-selected source MP4: '
  IFS= read -r source_media
fi

if [[ -z "$watched_folder" ]]; then
  printf 'Existing local folder already watched by Viso: '
  IFS= read -r watched_folder
fi

if [[ -z "$copy_count" ]]; then
  printf 'Finite copy count (1-20): '
  IFS= read -r copy_count
fi

exec "$python_bin" "$dronewatch_folder/demo_feed.py" replay \
  --scenario-id "$scenario_id" \
  --run-id "$run_id" \
  --fixture-id "$fixture_id" \
  --manifest "$manifest_file" \
  --source "$source_media" \
  --watch-dir "$watched_folder" \
  --count "$copy_count" \
  --interval "$copy_interval" \
  --record-dir "$record_dir"
