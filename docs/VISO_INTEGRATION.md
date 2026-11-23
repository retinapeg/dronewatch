# Viso Now integration evidence

Documentation review: **2026-10-04**. First delivery from a real Viso Now agent:
**2026-11-23** (see [below](#2026-11-23-first-delivery-from-a-real-agent)). This is a
prototype's evidence record. It shows what one agent sent on one day; it is not a
vendor-verified contract.

The intended vendor is **viso.ai**, product **Viso Now**, as confirmed by its
[official product page](https://viso.ai/viso-now/), which links the
[Viso Now documentation](https://docs.now.viso.ai/). The owner's spelling
“visnow.ai” is not the domain used by those official links. Viso Suite is a
separate product; its APIs must not be substituted for a Viso Now contract.

## Dated contract evidence matrix

All URLs below were accessed on **2026-10-04**, without credentials, account
requests, uploads or production API calls. VERIFIED means only the stated fact
was readable; UNRESOLVED means no implementable wire contract was recovered.
The table is kept as the record of that review. What has been observed since is
in the next section.

| Area | Status | Official sources and observed evidence | Supported mapping / unresolved requirements |
| --- | --- | --- | --- |
| Vendor and product | VERIFIED | [Product page](https://viso.ai/viso-now/) names Viso Now and links [docs](https://docs.now.viso.ai/); the [documentation sitemap](https://docs.now.viso.ai/sitemap.xml) lists the topics below. | Product identity only; this does not verify an API. |
| Webhook payload shape | UNRESOLVED | [Webhook/API](https://docs.now.viso.ai/webhook-api) metadata describes forwarding results to an external endpoint. [Custom output messages](https://docs.now.viso.ai/custom-output-messages) metadata refers to notification content. Article bodies were not recovered. | None. No verified JSON envelope, fields, types, identifiers, lifecycle, retries or idempotency rules. |
| Webhook authentication | UNRESOLVED | [Webhook/API](https://docs.now.viso.ai/webhook-api) returned metadata and an application shell, with no authentication specification. | None. No verified header, token format, signature, signed bytes, timestamp or replay protection. |
| File/video submission | UNRESOLVED | [Media processing model](https://docs.now.viso.ai/media-processing-model) metadata describes individual media files. [Input connectors](https://docs.now.viso.ai/input-connectors) metadata describes images and short clips entering an agent. | None. No verified HTTP method/base URL/path, API-key scheme, multipart field, body schema, format/size limits or job ID. |
| Processing-result retrieval | UNRESOLVED | [Reviewing results](https://docs.now.viso.ai/reviewing-results) metadata describes board review; [Webhook/API](https://docs.now.viso.ai/webhook-api) describes forwarding outputs. | None. No verified result schema, retrieval/polling path, status enum, completion semantics or delivery guarantees. |

The web reader exposed only the docs root shell and could not retrieve the
webhook/processing articles. TLS-verified system curl recovered the sitemap and
the five article pages above, but their HTML contained page titles/descriptions
and a JavaScript application shell rather than contract text. A successful HTML
response is not proof of an API schema. This access limitation does **not** mean
the vendor has no documentation or API. No backend/content-service API was called
to work around it.

The current product page advertises camera/live-feed capabilities alongside files
and APIs. The processing-page metadata still describes discrete media. This run
does not resolve that product-scope difference; DroneWatch's intended integration
remains bounded recorded-file analysis, with no demonstrated live Viso capability.
Older statements in `DATA_SOURCES.md` and the adapter docstring that public docs
“define no” schema must be read as earlier evidence limitations, not proof of
vendor absence. This dated record is the current evidence assessment.

## 2026-11-23: first delivery from a real agent

On 2026-11-23 the owner's Viso Now agent ("Drone Restricted Zone Monitor")
analysed a recorded clip that was uploaded by hand, and delivered its result to
`POST /v2/webhook/viso` on a local server reached through a temporary HTTPS
tunnel. It is the first evidence here that comes from Viso Now itself.

The clip was `V_DRONE_001` from the Halmstad Drone Detection Dataset (CC0), a
public research recording of a small quadcopter. No sensitive media was sent to
the service.

| Area | What the delivery shows | What it does not show |
| --- | --- | --- |
| Webhook payload shape | One JSON object with the top-level keys `activities`, `appId`, `appName`, `category`, `confidence`, `decision`, `fileName`, `fileType`, `findings`, `incidentId`, `incidentNumber`, `incidentUrl`, `labels`, `mediaLink`, `severity`, `source`, `status`, `summary` and `timestamp`. Each entry of `labels` had `label`, `confidence`, `approximate_position`, `motion_state`, `tracking_status`, `structure`, `first_visible_time`, `zone_state_sequence` and `intrusion_events`. | A fixed vendor schema. The documentation says the payload follows the agent's output configuration, so this is the shape of this agent's output on that day. |
| Recognition | The existing rule (`appId` with `incidentId`, or an `incidentUrl` on `now.viso.ai`) accepted the delivery unchanged, on both counts: outcome `MAPPED`. | Who sent it. The rule recognises a shape, not a signature. |
| Authentication | The delivery was accepted with DroneWatch's own shared token, which the owner entered in the agent's webhook connection. | Any signing, timestamping or replay protection on Viso's side. None was examined. |
| File submission | The clip was uploaded in the Viso Now web app. Viso stored it under its own name, so `fileName` was `<uuid>-<epoch ms>.mp4`. The original name appeared only in the report text ("Media sourced from `fx05.mp4`"). | An upload API. None is used here. |
| Result delivery | A webhook arrived for the clip the agent classed as a zone intrusion (label `drone`, confidence 0.95, severity `high`). A helicopter clip uploaded the same evening finished as an uncertain detection and produced no delivery. | Retries, ordering or duplicate handling. A missing delivery does not mean a clip was not analysed: a webhook is sent only when the agent's trigger rule matches. |
| Times and positions | `timestamp` held the item number, not a time. `approximate_position` and the "zone" describe a region of the image; this agent treats the central third of the frame as the zone. | An observation time or a map position. DroneWatch records the time of receipt and no position. |

What DroneWatch does with a delivery like this:

- `dronewatch/api/camera.py` reads the top label for display (`verdict`) and
  links the result to a local clip: by `fileName` when it matches a clip in the
  manifest, otherwise by the one known clip name quoted in the report
  (`source_match: "named_in_report"`). A report that names no known clip, or
  more than one, is linked to nothing.
- The operator view shows the verdict on the contacts the simulated camera
  picked up during the look the clip is linked to. When a result lists several
  objects, their number is compared with the number of contacts in that look,
  as a number only: no object in the clip is matched to a particular contact.
  It is shown, not fused: tracks do not change.
- A redacted copy of the delivery is kept at
  `tests/fixtures/viso/captured/drone_detected_2026-11-23.json`, with account
  and incident identifiers replaced by zeros. It sits outside the synthetic
  manifest, which still describes only fabricated fixtures. It is exercised by
  `tests/test_camera_api.py` and `tests/operator.test.cjs`.

Product facts read in the Viso Now documentation in a browser on the same day
(the articles are drawn by script, which is why the October fetch recovered
only page titles). Check the current documentation before relying on a limit
or a price:

- Viso Now analyses uploaded files: JPG, JPEG, PNG, MP4, MOV and MKV, images up
  to 5 MB and videos up to 200 MB. The documentation describes file-by-file
  analysis, not a live stream. The camera and live-feed wording on the product
  page, noted in October, has not been tested here.
- Each item is analysed on its own. Nothing is tracked from one upload to the
  next.
- A webhook is sent when the agent's trigger rule matches (severity, impact,
  board column or a custom rule). Any response other than 2xx counts as a
  failed delivery.
- Credits: building an agent 0.4, refining one 0.1, an image or short video 0.2
  to 1, a large video 2 to 3. Measured here: two 10-second clips cost 1.0
  credit each.

## Local fixtures and compatibility boundary

[manifest.json](../tests/fixtures/viso/manifest.json) identifies four tiny
**SYNTHETIC**, **FABRICATED_LOCAL** JSON fixtures, their SHA-256 hashes, source test
names, expected local outcomes and unresolved contract evidence. They were
authored from existing regression examples, with fabricated identifiers only;
they are neither captured nor redacted copies of real vendor deliveries (the one
captured delivery is kept apart from them, as described above). No
account, personal data, real media or credentials were used. The example incident
URL is a string tested offline, never a URL to fetch.

The provenance label lives in the manifest, not in invented vendor payload fields.
`appId`, `incidentId` and `incidentUrl` are **local compatibility examples**, not
verified vendor fields. Local `MAPPED` means only that the existing recogniser
accepted metadata. It does not establish vendor provenance, a drone detection,
position, confidence, real observation time or a live connection. Narrative-only
and unknown payloads remain unmapped; recognised examples retain UNKNOWN
classification and absent position/confidence. No unresolved vendor contract
claims a supported mapping.

## Current implementation and next evidence gate

Updated 2026-10-04. Settings are read from the process
environment; no `.env` file is loaded and all credentials are absent by default.

| Setting | Local behaviour |
| --- | --- |
| `VISO_API_KEY` | Independent outbound configuration only. It never enables inbound ingestion or verifies a connection. No outbound processing client exists yet. |
| `VISO_WEBHOOK_SECRET` | Enables the protected `POST /v2/webhook/viso` receiver. |
| `DRONEWATCH_WEBHOOK_SECRET` | Explicit compatibility alias for the inbound secret. Equal nonempty aliases work; conflicting values disable protected ingestion with HTTP 503. |

Empty and whitespace-only values are absent; surrounding whitespace is trimmed.
When an inbound secret arrives, set `VISO_WEBHOOK_SECRET` and leave the legacy
alias unset (or identical). The existing local sender script still accepts
`--secret` or `DRONEWATCH_WEBHOOK_SECRET`. The receiver accepts
`X-DroneWatch-Token` (customizable with `DRONEWATCH_WEBHOOK_HEADER`) or the existing
query-token compatibility path. Prefer the header to avoid credentials in URLs.
These are **local choices, not verified Viso authentication mechanisms**.
Set `VISO_API_KEY` separately when an outbound key arrives; it cannot supply the
missing wire contracts or make outbound processing operational.

`GET /health` retains `status: ok` and `received_at` as liveness fields and adds
`providers.viso`. With no credentials its message is `Viso: not configured`
(`NOT_CONFIGURED`). Either configured direction yields `CONFIGURED_UNVERIFIED`;
conflicting inbound aliases yield `CONFIGURATION_ERROR` without failing liveness.
An authenticated JSON delivery, including quarantined input, can yield
`DELIVERY_RECEIVED`; malformed JSON or rejected authentication cannot. The
`inbound_configured`, `outbound_configured`, `delivery_received` and
`configuration_error` fields distinguish configuration from process-local receipt
history. `connection_verified` remains false in every state. A synthetic test can
produce receipt evidence; it does not prove vendor identity, schema compliance,
outbound processing or live coverage. Receipt history resets on process restart;
removing settings returns the appropriate unconfigured status without erasing
in-memory counters.

`GET /api/preview/viso/status` retains its existing fields and state strings.
Without an inbound secret it reports `NOT CONFIGURED`, even with an outbound key.
Alias conflicts report `ERROR`, `configured: false` and a secret-free
`configuration_error`; ingestion returns 503 before processing the body. The
camera status uses the same inbound configuration reader. The unauthenticated
V0.1 route `POST /webhook/viso` was removed on 2026-11-23; `/v2/webhook/viso` is
the only route that accepts a delivery. No credential was enabled for real use
in the October run.

The October gate asked for an authorised, redacted delivery recorded separately
from the synthetic fixtures. That now exists (see the 2026-11-23 section). Still
open: an official specification for the payload and its authentication, what
happens on retry or duplicate delivery, and an upload route that does not
depend on the web app. Media sent to the service must stay within the rule in
`ROADMAP.md`: nothing classified, export-controlled, customer-confidential, from
an operational site or otherwise sensitive.

Offline evidence checks: `python -m pytest tests/test_viso_evidence.py
tests/test_camera_api.py`, plus the narrative-negative and unknown-payload
regressions in `tests/test_preview_api.py`.
