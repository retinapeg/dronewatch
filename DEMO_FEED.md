# Continuous demo feed

The original ~/Downloads/mq9-reaper.mp4 is read only. The dashboard plays it
muted on repeat from a separate local server, labelled DEMO SENSOR FEED.
LIVE PIPELINE reflects genuine Viso events within the last 120 seconds, never
video playback or simulated events. The FastAPI server and tunnel are unchanged.

From the dronewatch directory, start video playback and copying:

```sh
python3 demo_feed.py --watch-dir '/absolute/path/to/Google Drive/Viso watched folder' --interval 25
```

The folder must exist locally, be synced by Google Drive for desktop, and already
be watched by the existing Viso workflow. Each completed MP4 has a unique name.
Only completed copies are renamed to .mp4. Drive sync and Viso processing may
take longer than the copy interval. The helper cannot confirm ingestion itself;
watch the LIVE PIPELINE indicator and real event log for confirmation.

If the video server is already running, start just the copy loop:

```sh
python3 demo_feed.py --copy-only --watch-dir '/absolute/path/to/Google Drive/Viso watched folder' --interval 25
```

Alternatively set DRONEWATCH_DRIVE_FOLDER to the local folder. --source overrides
the original video path. Ctrl+C stops the helper and removes any unfinished copy;
completed files are retained. No deletion or cleanup of existing Drive files is
performed.

Without --watch-dir, the helper serves video only and copies nothing:

```sh
python3 demo_feed.py
```

Open http://localhost:8000 on this computer. The local-only video server listens
on 127.0.0.1:8001 and supports byte-range requests for smooth looping. Other
computers opening a public dashboard URL cannot use this computer's loopback
video feed. The existing public Viso webhook does not change.
