#!/bin/zsh
set -eu

dronewatch_folder='/Users/leo/Documents/Codex/2026-09-03/yes-that-is-the-right-architecture/dronewatch'
watched_folder="${DRONEWATCH_DRIVE_FOLDER:-}"

if [[ -z "$watched_folder" ]]; then
  printf 'Local Google Drive folder already watched by Viso: '
  IFS= read -r watched_folder
fi

exec /usr/bin/python3 "$dronewatch_folder/demo_feed.py" \
  --copy-only --watch-dir "$watched_folder" --interval 25
