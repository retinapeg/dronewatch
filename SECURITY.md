# Receiver security and data boundaries

V0.2 is a local/supervised prototype receiver. Its repository-local controls do
not make it suitable for an unattended public or operational deployment. No
public tunnel, rate-limiting layer, managed secret store, provider account, or
authenticated relay is configured by this repository.

## Authentication boundary

All write routes and the legacy-quarantine route require exactly one
`Authorization: Bearer <token>` header. The expected token comes only from the
`DRONEWATCH_WEBHOOK_TOKEN` process environment variable.

- There is no committed/default token and no unauthenticated fallback.
- The configured value must contain at least 32 visible ASCII characters.
- Missing configuration fails closed with `503 receiver_unavailable`.
- Missing, duplicate, malformed, or incorrect authorization fails with the same
  generic `401 authentication_failed` response.
- The receiver hashes both supplied and expected values to fixed-length SHA-256
  byte strings and compares those with `secrets.compare_digest`.
- Query-string credentials are never accepted.
- Authentication occurs before the request body is read or stored.

Local tests can establish that DroneWatch enforces this bearer boundary. They
do **not** establish that Viso Now can emit this header. The Viso account's
incoming-webhook authentication capability is an external acceptance question.
If the account cannot emit the required header, an authenticated relay may be
designed only after evidence establishes that need and the user authorizes it.

Viso account/API OAuth is a separate concern from DroneWatch's inbound bearer
header. OAuth credentials and fields stay blank for this V0.2 acceptance run
and are not invented as application environment variables. All Viso account
secrets, connector credentials, tokens, sensitive endpoint URLs, and
authorization values remain external/local and uncommitted. Any later OAuth
integration would require separate evidence and explicit authorization.

## Request parsing boundary

Authenticated webhook requests must meet all of these conditions:

- one `Content-Type: application/json` header, optionally with exactly
  `charset=utf-8`;
- no content encoding, or exactly `identity`;
- at most one decimal `Content-Length` value, if supplied;
- a non-empty, strictly decoded UTF-8 body;
- an actual streamed byte count no larger than
  `DRONEWATCH_WEBHOOK_MAX_BYTES` (65,536 bytes by default); and
- one top-level JSON object with no duplicate keys, non-finite numbers, more
  than 20 levels of nesting, or more than 2,000 JSON nodes.

`Content-Length` is an early rejection aid, not the size control. The receiver
counts streamed chunks and stops an oversized body even when the header is
absent or understates the body. The configurable range is 1,024 through
1,048,576 bytes. A declared length that differs from the received byte count is
rejected.

The provider-neutral canonical route then applies the strict
`dronewatch.event.v1` contract. Extra fields, accidental nested keys, loose type
coercions, missing identity, invalid timestamps, conflicting lifecycle/class
semantics, or provenance/simulation contradictions fail without a database
write. `received_at` is captured by DroneWatch on route entry and cannot be
provided by the sender. Source time later than the configured receipt-time
tolerance (60 seconds by default) is rejected.

The strict Viso adapter is unavailable until real redacted account evidence is
captured. `/webhook/viso` therefore applies authentication and body safety, then
returns `503 viso_adapter_unavailable` without treating any JSON shape as Viso.
No recursive or narrative-key heuristic is present.

When the development simulation route is explicitly enabled, it uses the same
authentication-first, media-type, streamed-size, UTF-8, and strict-JSON boundary
before its smaller scenario model is validated.

## Response classes

| HTTP status | Meaning |
| --- | --- |
| `201` | First valid canonical delivery accepted. |
| `200` | Exact retry acknowledged; no second logical observation. |
| `400` | Empty/invalid JSON, invalid length, disconnected/incomplete body, duplicate key, or excessive JSON complexity. |
| `401` | Missing, malformed, duplicate, or incorrect bearer credential. |
| `409` | Existing composite delivery key reused with different normalized content. |
| `413` | Declared or actually streamed body exceeds the configured limit. |
| `415` | Unsupported/missing media type, charset, or content encoding. |
| `422` | Contract/time validation failure or reserved source-system misuse. |
| `503` | Receiver credential absent, Viso adapter unavailable, or storage unavailable. |

Error bodies expose stable generic codes, not secrets, request bodies, database
paths, sensitive URLs, provider data, or internal exception messages.

## Persistence and idempotency

The unique idempotency boundary is
`(source_system, source_scope, source_event_id)`. Reservation and observation
insertion occur inside one immediate SQLite transaction. An exact normalized
retry receives the original observation ID. Conflicting content never overwrites
the original; a digest-only audit record records the attempted conflict.

The delivery-key ledger is permanent even when history retention prunes the
corresponding observation. This avoids silently accepting an old event key again.
Materialized track heads are also outside history retention so pruning cannot
change current open-track state.

The database file is created or tightened to owner read/write mode (`0600`) on
every application connection. SQLite WAL, shared-memory, and rollback-journal
sidecars inherit that private mode; pre-existing sidecars are tightened before
use. Migration refuses incompatible table column types, nullability, primary-key
shape, defaults, partial uniqueness, non-binary collation, or descending unique
keys rather than operating on a merely name-compatible schema.

## Raw-data and API boundary

DroneWatch does not retain complete inbound request bodies. It stores:

- validated canonical fields;
- a SHA-256 digest of exact accepted request bytes; and
- a deterministic digest of normalized canonical source content.

`GET /api/events` exposes only an allowlisted compatibility projection and sends
`Cache-Control: no-store` plus `X-Content-Type-Options: nosniff`. Its
`raw_payload` name is retained solely for the frozen dashboard; the value is a
bounded (maximum 4 KiB), rebuilt object of approved canonical fields. It does
not contain arbitrary provider content, unknown nested values, authorization
headers, or provider media URLs. The public projection does expose validated
source, scope, track, scenario, and run identifiers. Their syntax is bounded,
but syntax validation cannot detect a secret or personal name used as an ID;
senders must use non-sensitive opaque identifiers and this prototype must not be
exposed publicly without a separate access-control review.

Preserved V0.1 raw strings remain quarantined in the database and are never
returned. Authenticated `GET /api/legacy/events` returns a fixed
`LEGACY_UNVERIFIED` projection with unknown/non-detection semantics.

There is no full-raw diagnostic route in V0.2. Adding one would require an
explicit threat/retention design, separate authorization, and shorter bounded
retention than canonical observations.

## Retention defaults

- canonical observation history: 30 days and 10,000 rows;
- digest-only delivery conflicts: 7 days and 1,000 rows;
- delivery keys: permanent;
- effective track heads: permanent until a later explicit lifecycle policy;
- V0.1 legacy rows: preserved; and
- full raw requests: disabled/not stored.

Both age and count limits apply deterministically during accepted, duplicate,
or conflict delivery transactions. Environment overrides are range checked at
startup. Retention does not claim regulatory compliance and is not a substitute
for an organization-specific data policy.

## Logging and evidence hygiene

Normal receiver logs contain only a generic outcome and internal observation
ID. Conflict and storage failures use generic messages. Do not enable middleware
that logs request headers or bodies around this application without a separate
review.

Never place any of the following in Git, a run record, a redacted provider
fixture, API output, terminal transcript intended for sharing, or release
evidence:

- bearer/OAuth values or authorization headers;
- Viso/Drive credentials or account tokens;
- sensitive webhook or tunnel URLs;
- unredacted provider/customer payloads;
- personal or operational-site data;
- controlled, classified, ITAR/export-controlled, or customer-confidential
  media; or
- machine-specific absolute paths.

Only public, synthetic, CC0/licence-clean, or specifically authorized media may
enter the supervised Viso Now path. Stop any temporary exposure immediately
after the explicitly authorized acceptance run.

Any temporary external acceptance proxy must expose only authenticated
`POST /webhook/viso` and deny every read/UI/config/legacy/development route. A
sensitive URL plus bearer authentication on writes does not protect the
otherwise local, sanitized read API.
