# Viso Now file-replay helper

The selected source MP4 is opened read-only. The dashboard can play it muted on
repeat from a separate local server, labelled DEMO SENSOR FEED. LIVE PIPELINE
reflects Viso-shaped events within the last 120 seconds, never video playback or
simulated events. V0 does not authenticate Viso provenance.

Viso Now processes discrete media files rather than a continuous live stream.
This helper therefore creates a supervised file replay, not a live camera feed.

From the dronewatch directory, start video playback and copying:

```sh
.venv/bin/python demo_feed.py \
  --source '/absolute/path/to/demo.mp4' \
  --watch-dir '/absolute/path/to/Google Drive/Viso watched folder' \
  --interval 25
```

The folder must exist locally, be synced by Google Drive for desktop, and already
be watched by the existing Viso workflow. Each completed MP4 has a unique name.
Only completed copies are renamed to .mp4. Drive sync and Viso processing may
take longer than the copy interval. The helper cannot confirm ingestion itself;
watch the LIVE PIPELINE indicator and real event log for confirmation.

If the video server is already running, start just the copy loop:

```sh
.venv/bin/python demo_feed.py --copy-only \
  --source '/absolute/path/to/demo.mp4' \
  --watch-dir '/absolute/path/to/Google Drive/Viso watched folder' \
  --interval 25
```

Alternatively set `DRONEWATCH_DRIVE_FOLDER` to the local folder. `--source`
selects the video. Ctrl+C stops the helper and removes any unfinished copy;
completed files are retained. No deletion or cleanup of existing Drive files is
performed. At the default interval the helper can create 144 copies per hour, so
run it only for a bounded, supervised demo session.

Without --watch-dir, the helper serves video only and copies nothing:

```sh
.venv/bin/python demo_feed.py --source '/absolute/path/to/demo.mp4'
```

Open http://localhost:8000 on this computer. The local-only video server listens
on 127.0.0.1:8001 and supports byte-range requests for smooth looping. Other
computers opening a public dashboard URL cannot use this computer's loopback
video feed. The Viso webhook path remains independent of this loopback server.
