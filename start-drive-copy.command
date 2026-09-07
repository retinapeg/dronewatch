#!/bin/zsh
set -eu

dronewatch_folder=${0:A:h}
watched_folder="${DRONEWATCH_DRIVE_FOLDER:-}"
source_media="${DRONEWATCH_DEMO_SOURCE:-}"
python_bin="${DRONEWATCH_PYTHON:-$dronewatch_folder/.venv/bin/python}"

if [[ ! -x "$python_bin" ]]; then
  python_bin="$(command -v python3)"
fi

if [[ -z "$watched_folder" ]]; then
  printf 'Local Google Drive folder already watched by Viso: '
  IFS= read -r watched_folder
fi

if [[ -z "$source_media" ]]; then
  printf 'Source MP4 to replay: '
  IFS= read -r source_media
fi

exec "$python_bin" "$dronewatch_folder/demo_feed.py" \
  --copy-only --source "$source_media" \
  --watch-dir "$watched_folder" --interval 25
