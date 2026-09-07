# Tactical dashboard

Open <http://127.0.0.1:8000>. FastAPI serves the unchanged `index.html`, which
polls `GET /api/events` every two seconds.

The V0.2 frontend is deliberately frozen while the observation and provider
contracts are proven. Its tactical styling is a presentation surface, not a
calibrated sensor display.

## Existing controls

- Full screen uses the browser full-screen API.
- Demo controls remain collapsed in the footer and are gated by
  `simulation_enabled` from `GET /api/config`.
- The browser-only scenario shows CLEAR, DETECTED, APPROACHING, RESTRICTED ZONE,
  and EXITED. Those steps do not enter SQLite and are not sensor evidence.
- Stored development simulation is disabled by default. When explicitly
  enabled, the route requires the same bearer authentication as webhook writes
  and stores observations as `SYNTHETIC` plus `LOCAL_SIMULATION`.
- A selected local video plays muted in the browser as demo source media. Video
  playback is independent of event ingestion and cannot prove Viso processing.

## V0.2 API semantics

`GET /api/events` returns a sanitized, allowlisted compatibility projection. It
preserves the legacy top-level fields the frozen dashboard consumes while also
including canonical identity, source time, receipt time, scope, track,
provenance, and delivery mode. The field named `raw_payload` is **not** the raw
request: it is a bounded compatibility object containing only approved canonical
values. Unknown provider keys, nested source content, credentials, URLs, and
complete request bodies are excluded.

`open_incidents` and `open_count` come from materialized effective track heads,
not from the paginated history. Therefore `GET /api/events?limit=1` cannot change
the system's open-track result. A positive `DRONE` observation in DETECTED,
APPROACHING, or RESTRICTED_ZONE is open. A newer matching `EXITED` observation
closes that scoped track while both historical observations remain. Explicit
negative and `UNKNOWN` observations never become open incidents.

Legacy V0.1 rows are absent from the ordinary event list and contribute only to
`legacy_unverified_count`. An authenticated operator can inspect their fixed,
sanitized quarantine projection at `GET /api/legacy/events`; their original raw
payload is never returned or reinterpreted.

## Display boundaries

Radar rings, sweep, and zone boundary are schematic and uncalibrated. Optional
coordinates are normalized image-frame values only. They are not geographic,
radar-derived, or calibrated position. DroneWatch does not invent speed,
distance, bearing, heading, or location.

Confidence is a source-reported numeric score from 0.0 through 1.0, not a
calibrated probability or measured accuracy. `UNKNOWN` does not mean clear
airspace. Recent receipt indicates data recency only; it does not establish a
live video stream, successful continuous operation, or authenticated Viso
provenance.

The Viso adapter is disabled pending an actual redacted delivery and account
authentication test. Consequently no V0.2 event should be described as a
genuine Viso observation until the acceptance procedure is complete. Synthetic
contract tests use `CONTRACT_TEST`, and the canonical endpoint rejects the
reserved source system `VISO`.

Only supplied absolute HTTP(S) media URLs were historically considered by the
frozen UI. V0.2 canonical projections intentionally return `media_url: null`;
the receiver does not retain or expose provider media URLs.

## Checks

Run backend and presentation-data tests from the repository root:

```sh
.venv/bin/python -m pytest -q
node --test tests/dashboard.test.cjs
```

The frontend remains protected by its known Git blob and SHA-256 hashes. The
release handoff must verify both and confirm `index.html` is absent from the
candidate diff. Any future V0.6 frontend work requires a separate, explicit
scope and must preserve the provenance and modality distinctions established
here.
