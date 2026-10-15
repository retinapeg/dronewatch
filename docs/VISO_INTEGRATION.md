# Viso Now integration evidence

Access/review date: **2026-10-04**. This is a disconnected prototype's contract
record, not evidence of an account connection or vendor-compliant integration.

The intended vendor is **viso.ai**, product **Viso Now**, as confirmed by its
[official product page](https://viso.ai/viso-now/), which links the
[Viso Now documentation](https://docs.now.viso.ai/). The owner's spelling
“visnow.ai” is not the domain used by those official links. Viso Suite is a
separate product; its APIs must not be substituted for a Viso Now contract.

## Dated contract evidence matrix

All URLs below were accessed on **2026-10-04**, without credentials, account
requests, uploads or production API calls. VERIFIED means only the stated fact
was readable; UNRESOLVED means no implementable wire contract was recovered.

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

## Local fixtures and compatibility boundary

[manifest.json](../tests/fixtures/viso/manifest.json) identifies four tiny
**SYNTHETIC**, **FABRICATED_LOCAL** JSON fixtures, their SHA-256 hashes, source test
names, expected local outcomes and unresolved contract evidence. They were
authored from existing regression examples, with fabricated identifiers only;
they are neither captured nor redacted copies of real vendor deliveries. No
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

Updated 2026-10-04 for backlog item 5. Settings are read from the process
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
camera status uses the same inbound configuration reader. The legacy
`POST /webhook/viso` remains unauthenticated and does not affect the provider
receipt summary. No credential was enabled for real use in this run.

Before enabling a real integration, obtain official account-applicable
specifications for all four unresolved rows, then record an authorised, redacted
delivery separately from these synthetic fixtures. Verify authentication support
and permitted media handling before any real upload. Outbound refusal, ingress
hardening and the final setup runbook belong to later backlog items.

Offline evidence checks: `python -m pytest tests/test_viso_evidence.py` plus the
existing narrative-negative/unknown-payload regressions in
`tests/test_preview_api.py` and `tests/test_main.py`. Use the repository virtual
environment and the run's required retained-scratch/no-deletion harness when
operating under that restriction; full-run results are in `BUILD_LOG.md` and
`ERROR_LOG.md`.
