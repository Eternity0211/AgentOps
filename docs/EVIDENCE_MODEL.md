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
