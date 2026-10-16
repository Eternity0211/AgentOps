# Structured logging safety contract

Phase 11 applies one versioned structured-log contract to diagnosed-system and control-plane
runtime logs. The contract is an observability boundary only: it cannot replace Evidence,
AuditEvent, correlation-ledger, policy, approval, execution, or verification records.

## Record schema

Schema `1.0.0` is a flat scalar object. Every accepted record contains exactly the common fields
`log.schema.version`, `event.name`, and `severity.text`, followed by fields from the selected
closed event schema. Values may be strings, finite numbers, or booleans. Lists, objects, nulls,
unknown fields, caller-supplied logging metadata, and sensitive field names are rejected.

The event registry covers simulator HTTP, downstream HTTP, dependency, deployment and bounded
memory observations; control-plane operations; and content-free observer/configuration/shutdown
failures. A rejected candidate becomes `structured_log.payload_refused` with only the rejected
event name and a stable reason code. The rejected value and exception text are never copied into
that refusal record.

The same canonical record is emitted as compact sorted JSON to the standard Python logger and as
the body/attributes of OTLP log records. OTLP trace and span linkage remains SDK-owned. Direct
free-form calls to Python loggers are not used by runtime modules.

## Redaction and bounds

Before export, string values are scanned for private keys, Basic/Bearer authorization values,
common hosted-token prefixes, secret assignments, cookies, and credentials embedded in a URI.
Matches become the fixed non-reversible marker `[REDACTED]`; a boolean
`agentops.log.redacted=true` records that the transform occurred. Control characters, including
newlines and NUL, are removed from attribute values so they cannot forge another record.

Each string is capped at 256 UTF-8 bytes without splitting a code point. One record accepts at
most 40 input attributes and its canonical representation is capped at 4,096 UTF-8 bytes. If the
record cap is reached, optional attributes are dropped in deterministic reverse-key order while
tenant, Incident, correlation, causation, operation, workflow, and service identities are
preserved. `agentops.log.truncated` and `agentops.log.dropped_attributes` make the loss explicit.
If even the protected identity record cannot fit, the candidate fails closed.

These limits apply at the logging adapter, independently of upstream type validation. Simulator
Span names/attributes and metric dimensions also sanitize external strings before emission.
Control-plane Spans, logs, and model/tool metric dimensions are derived from the same sanitized
record, so a value cannot be clean in one signal and secret-bearing in another. Identity-bearing
fields are deliberately excluded from metric dimensions to avoid unbounded cardinality.

## Failure behavior and verification

Logging remains fail-open with respect to business and recovery behavior. Exporter setup,
recording, flushing, and observer failures may lose telemetry or emit a content-free refusal, but
they cannot alter workflow state, idempotency, policy, approval, execution, verification, or a
simulator dependency/deployment outcome.

Unit tests cover canonical serialization, immutable records, closed fields, sensitive-key refusal,
all redaction families, control-character removal, finite scalar enforcement, Unicode byte-boundary
truncation, deterministic whole-record reduction, protected identities, content-free refusal, and
standard logger serialization. In-memory OpenTelemetry exporters seed the same secret into
simulator and control-plane paths and assert it is absent from logs, Spans, and metric dimensions
while correlation identity remains intact. Existing exception-path tests assert that exception
bodies never reach fallback logs.
