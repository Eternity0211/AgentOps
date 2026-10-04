# Immutable Evidence Model

Evidence is an immutable, incident-owned normalized observation. It is not a model assertion and
cannot exist as an oversized inline payload. Every record points to one immutable Artifact and
duplicates its SHA-256 digest so resolvers can detect substituted or altered content.

## Required fields and types

- opaque Evidence, tenant, Incident, Artifact, ToolCall, and WorkflowRun identities;
- source type (`METRIC`, `LOG`, `TRACE`, `DEPLOYMENT`, or `TOPOLOGY`) and bounded source instance;
- exact canonical query parameters plus tool implementation and input/output schema versions;
- UTC observation range, collection time, and expiry;
- parser and normalizer versions;
- deterministic quality score in integer basis points with one or more reason codes;
- ToolCall/WorkflowRun lineage, optional redaction transform, and bounded parent Evidence IDs;
- trust classification and prompt-injection classification;
- Evidence schema version `1.0.0`.

Query fields are sorted and unique. Observation, collection, and expiry timestamps have an
enforced order. Confidence is deliberately absent from this authoritative contract: later agent
confidence remains non-authoritative metadata and cannot make the Evidence Gate pass.

## Artifact resolution and ownership

Before persistence, `Evidence.verify_artifact` checks Artifact ID, tenant, Incident, and content
hash. PostgreSQL additionally enforces Evidence-to-Incident tenant ownership using a composite
foreign key and makes Artifact IDs unique in the Evidence table. Retrieval is scoped by Evidence
ID, tenant, and Incident. The later Evidence Gate will resolve the referenced Artifact bytes and
apply freshness, quality, independence, and counter-evidence rules; this schema does not claim
that merely stored Evidence is sufficient.

Normalized query parameters and quality/lineage collections are bounded. Raw telemetry remains
in Artifact storage and Ground Truth fields are not represented in the runtime schema.

## Deterministic normalization and validation

The normalization service accepts JSON-compatible collector output only. It recursively enforces
depth and node limits, rejects non-finite numbers, unsupported values, and invalid object keys,
then emits canonical sorted UTF-8 JSON. Identical logical input therefore produces identical bytes
and SHA-256 content hashes independent of input key order.

## Sensitive-data redaction and lineage

Before persistence or model access, the deterministic redactor walks bounded JSON-compatible
content while preserving its structure. It replaces values under known sensitive fields and
recognizes private-key blocks, authorization credentials, common token prefixes, and explicit
secret assignments inside free text. Object paths use escaped JSON Pointer notation. Oversized
text, excessive depth/node counts, non-finite numbers, invalid keys, and non-JSON values fail
closed.

Every replacement records a Redaction Transform ID, path, stable occurrence, rule, marker, and an
HMAC-SHA256 of the removed value. The HMAC requires a server-held key of at least 32 bytes; the key
and plaintext are never retained in the result, so lineage can correlate deterministic
transformations without becoming a low-entropy secret oracle. A result is marked `REDACTED` only
when at least one replacement occurs, otherwise `NOT_REQUIRED`. Seeded-canary tests assert that
field, inline credential, token, assignment, and private-key values appear in neither redacted
content nor lineage representations.

## Untrusted telemetry screening and quarantine

Log and trace text is always classified as untrusted data. A bounded deterministic screen applies
Unicode compatibility normalization, removes zero-width separators, normalizes whitespace, and
detects explicit instruction override, role impersonation, tool invocation, policy bypass, and
secret-exfiltration phrases. This classification does not interpret or execute the text and does
not grant authority based on its contents.

Normal content is serialized as a JSON string inside a fixed `UNTRUSTED_TELEMETRY_DATA` boundary;
angle brackets are Unicode-escaped so payload text cannot close the boundary. Suspected content is
never returned as model-ready text. Quarantine retains only the source Artifact ID, SHA-256 hash,
UTF-8 length, deterministic reason codes, and `QUARANTINED` status, leaving the raw value solely in
its access-controlled Artifact. Only `SUSPECTED` content with consistent metadata may transition
to quarantine; normal Evidence construction already rejects unquarantined suspected content.

## Budgeted Context Builder

The deterministic Context Builder accepts at most 256 bounded derived summaries or quarantine
metadata items; raw telemetry is not a representable content kind. Every candidate carries its
Incident, Evidence, and Artifact IDs, source type, trust classification, content kind, and stable
priority. Summary text is limited to 4,096 characters and receives a deterministic conservative
UTF-8 token estimate, while actual provider token accounting remains a later model-call concern.

Candidates must belong to one Incident and have unique keys and Evidence references. Selection is
stable by priority, source type, Evidence ID, and key. Whole items are admitted only while both the
token and item budgets permit; the builder never slices text into an unverifiable fragment. Every
excluded candidate is recorded with its Evidence/Artifact provenance, estimated size, and either
`TOKEN_BUDGET` or `ITEM_LIMIT`, making context loss explicit and reproducible. The resulting
bounded object can enter future graph state or model prompts without embedding Artifact payloads.

Artifact and Evidence records are built together from one typed request. Their tenant, Incident,
Artifact ID, digest, collection time, versions, and lineage cannot drift. Evidence cannot outlive
its Artifact. Suspected prompt injection cannot enter normal Evidence construction until it is
explicitly quarantined; quarantined material remains visibly low-quality and untrusted.

Quality scoring uses deterministic collector facts rather than model confidence: source
availability, observation-window completeness, observed/dropped record counts, parser warnings,
and injection classification. Every deduction emits a stable reason code. Scores use integer basis
points to avoid floating-point ambiguity.

Validation first performs authorized Artifact resolution, then rechecks ownership, ID, hash, and
byte size. It returns `VALID` or `EXPIRED` with separate Evidence and Artifact expiry reasons.
Missing, altered, unauthorized, cross-Incident, or cross-tenant content raises a typed failure
instead of producing a partially trusted result.
