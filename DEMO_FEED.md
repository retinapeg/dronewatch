# Bounded Viso Now file-replay helper

Viso Now processes discrete media files. DroneWatch therefore names this
workflow `NEAR_REAL_TIME_FILE_REPLAY`; it is not a live camera feed. Viso Now is
the intended visual-analysis field, not radar.

`demo_feed.py` has two explicit modes:

- `serve` provides one local MP4 over loopback for the frozen dashboard. It
  creates no watched-folder files and runs until interrupted.
- `replay` performs a finite manifest-checked copy run. It does not start an
  uncontrolled retry/copy loop.

## Preconditions

Before a replay:

1. Select a fixture from `fixtures/halmstad-selection.v1.json`.
2. Obtain only that exact source MP4 and keep it outside Git.
3. Confirm the destination directory already exists. If it is a Google Drive
   watched folder, Drive sync and the Viso workflow must be configured outside
   DroneWatch.
4. Choose explicit scenario and run IDs. Use a new run ID for every attempt;
   the runner refuses to overwrite an existing run record.
5. Use a finite positive count from 1 through 20 and an interval from 20 through
   30 seconds.

The source must be a non-empty regular file outside the watched directory. The
run-record directory must also be outside the watched directory, preventing
evidence JSON from becoming a Viso input.

## Run a finite scenario

From the repository root:

```sh
.venv/bin/python demo_feed.py replay \
  --scenario-id perimeter-demo \
  --run-id perimeter-demo-001 \
  --fixture-id halmstad-v-drone-001 \
  --manifest fixtures/halmstad-selection.v1.json \
  --source /path/to/V_DRONE_001.mp4 \
  --watch-dir /path/to/existing/watched-folder \
  --count 3 \
  --interval 25
```

The macOS launcher requests the same values interactively when they are not
provided through its documented environment variables:

```sh
./start-drive-copy.command
```

Launcher-only environment variables:

| Variable | Blank/default behavior |
| --- | --- |
| `DRONEWATCH_SCENARIO_ID` | Prompts for the scenario ID. |
| `DRONEWATCH_RUN_ID` | Prompts for the unique run ID. |
| `DRONEWATCH_FIXTURE_ID` | Prompts for a fixture ID from the manifest. |
| `DRONEWATCH_FIXTURE_MANIFEST` | Uses the checked-in Halmstad selection manifest. |
| `DRONEWATCH_DEMO_SOURCE` | Prompts for the exact external source MP4. |
| `DRONEWATCH_DRIVE_FOLDER` | Prompts for the existing watched directory. |
| `DRONEWATCH_COPY_COUNT` | Prompts for a finite count from 1 through 20. |
| `DRONEWATCH_COPY_INTERVAL` | Uses 25 seconds; allowed range is 20 through 30. |
| `DRONEWATCH_RUN_RECORD_DIR` | Uses the ignored repository `run-records/` directory. |
| `DRONEWATCH_PYTHON` | Uses repository `.venv/bin/python`, then a discovered `python3` if that is not executable. |

These are process inputs, not credentials. Viso/Drive account credentials and
OAuth values are never read by the launcher and remain external/local.

The runner validates all arguments before copying. The manifest must be marked
`VERIFIED`, the fixture ID and source basename must match, and the source byte
count and SHA-256 must equal the manifest. A mismatch exits non-zero without a
watched-folder copy.

## Copy and stop behaviour

For each requested sequence, the runner:

1. opens the source read-only and calculates its SHA-256;
2. copies in bounded chunks to a uniquely named `.part` file in the existing
   watched directory;
3. flushes the completed temporary file, verifies that the source did not
   change during the copy, and atomically publishes it without replacing an
   existing basename;
4. calculates/records the completed-copy SHA-256; and
5. updates the machine-readable run record before continuing.

There are no automatic retries. A requested run succeeds only after exactly the
requested number of completed copies. Copy or validation failure exits non-zero
and removes only the runner's unfinished `.part` file. Interruption also removes
that unfinished part and returns an interruption status. The source, pre-existing
watched-folder files, and successfully completed copies are never deleted or
overwritten.

The default retained record is `run-records/<run-id>.json`, a directory ignored
by Git. It contains the schema/version, scenario and run IDs, fixture identity,
source hash, per-copy sequence number, destination basename, completed-copy
hash, UTC start/completion timestamps, and success/failure state. It contains no
credentials, authorization values, sensitive URLs, raw provider messages, or
machine-specific absolute paths. Failure records use stable error codes rather
than retained exception text.

## Serve the dashboard video locally

Video-only mode creates no files and may run until interrupted:

```sh
.venv/bin/python demo_feed.py serve \
  --source /path/to/V_DRONE_001.mp4 \
  --port 8001
```

The server listens on `127.0.0.1` and serves the selected file with byte-range
support at <http://127.0.0.1:8001/mq9-reaper.mp4>. The historical URL is retained
for frontend compatibility; it does not describe the selected aircraft or
fixture. A browser on another computer cannot use this machine's loopback URL.
Cross-origin reads are allowed only from the local dashboard origins
`http://127.0.0.1:8000` and `http://localhost:8000`; arbitrary web origins and
non-local host headers are rejected. Use only reviewed, licence-clean,
non-sensitive media even for local playback.

Local playback is independent of webhook ingestion. Seeing the video in the
dashboard proves neither that Viso received it nor that an observation was
delivered.

## What a successful local run proves

A successful record proves only that:

- the local source matched the pinned manifest when checked;
- the requested number of files were copied atomically; and
- the recorded completed-file hashes matched the copied bytes.

It does **not** prove Google Drive synchronization, Viso ingestion or processing,
webhook authentication/delivery, correct classification, latency, model
accuracy, live video, or operational reliability. Those claims require the
separate supervised evidence procedure in
`VISO_ACCEPTANCE.md`.
