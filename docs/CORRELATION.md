# Trace, Correlation, and Causation Contract

Phase 11 uses three different identifiers because they answer different questions:

- `TraceId` is the W3C-compatible, nonzero 16-byte lowercase hexadecimal identity used to join
  OpenTelemetry spans for one distributed operation.
- `CorrelationId` is the bounded opaque identity of one Incident control-flow stream. It remains
  stable from Alert admission through deterministic health verification.
- `CausationId` is the exact preceding correlation-event identity that directly caused a new
  event. It forms an explicit directed chain rather than relying on timestamp proximity.

These identities are metadata only. They cannot contain logs, prompts, tool arguments/results,
credentials, or other request payloads.

## Versioned domain contract

`CorrelationLink` schema `1.0.0` binds an immutable event ID, tenant, Incident, closed component,
resource ID, Trace ID, Correlation ID, optional Causation ID, and aware UTC occurrence time. The
closed component vocabulary is:

1. `ALERT`
2. `INCIDENT`
3. `GRAPH`
4. `TOOL`
5. `MODEL`
6. `APPROVAL`
7. `EXECUTION`
8. `VERIFICATION`

`CorrelationTimeline` fails closed unless every link has one tenant/Incident/Correlation scope,
strict time/event ordering, a unique event ID, and a unique component/resource pair. It permits
exactly one leading `ALERT` root; every later link must cite an earlier event in the same stream.
The timeline is bounded to 10,000 links. `require_complete()` proves all eight component classes
are present but never infers that recovery succeeded; that authority remains with the deterministic
health verifier.

Each link has a canonical SHA-256 fingerprint covering every stored field. A stored fingerprint is
recomputed on reads, so substituted scope, time, trace, resource, component, or causation metadata
cannot silently enter a reconstructed timeline.

## Durable ledger

Alembic revision `20261015_0021` adds:

- `correlation_streams`, whose composite key `(tenant_id, correlation_id)` binds a stream to
  exactly one tenant-owned Incident; and
- `correlation_links`, an immutable content-free event ledger with database-assigned sequence,
  same-stream parent foreign keys, component/resource uniqueness, strict Trace ID and fingerprint
  checks, and tenant/Incident stream ownership.

`CorrelationLinkRepository.append()` creates or locks the stream claim before inspecting or adding
a link. This serializes concurrent workers. An exact event replay returns the fingerprint-verified
stored link; reuse of the event ID with changed content is rejected. A correlation ID cannot be
rebound to another Incident, and a parent cannot cross tenant or correlation scope. Reads require
the complete tenant/Incident/Correlation tuple and reconstruct all domain invariants.

This ledger is distinct from OpenTelemetry storage and the append-only business audit ledger:

- traces explain timing and distributed execution;
- correlation links prove control-flow resource relationships; and
- audit events prove actor-visible decisions and state changes.

## Runtime boundary workflow

`IncidentCorrelationWorkflow` is the deterministic, framework-independent coordinator for the
eight authoritative boundaries. It does not execute a tool, call a model, approve a proposal,
mutate a service, or declare recovery. It accepts only the resulting typed authoritative objects:

- a normalized `Alert` and tenant-matched `Incident` establish the root and ownership binding;
- a `DiagnosisGraphState` must carry the current Correlation ID and the preceding ledger event as
  its Causation ID;
- a successful `ToolCallResult` must exactly match its scoped `ToolCallRequest`, whose Causation ID
  names the preceding ledger event;
- a successful terminal `ModelCallTrace` must match tenant, Incident, Correlation, and preceding
  Causation identity;
- the Approval must be `APPROVED`, the ActionExecution must be `SUCCEEDED`, and the Verification
  decision must bind that exact execution.

Graph, Tool, and Model events may repeat during bounded investigation and replanning. Approval is
refused until at least one of each exists; after Approval, only Execution and then Verification are
legal. Verification completes the chain but its PASS/FAIL outcome remains authoritative only to the
existing deterministic routers.

Event IDs are deterministically derived from schema, tenant, Incident, Correlation, component, and
resource identity. Retries therefore address the same immutable event. Authoritative occurrence
times and per-boundary W3C Trace IDs remain fingerprinted, so replay with a substituted time or
Trace ID fails closed. A cursor contains only the verified content-free timeline; `resume()` rebuilds
it from PostgreSQL after worker replacement and revalidates the runtime order.

`PostgresCorrelationLinkStore` owns one short transaction per append/read, and the worker
composition root exposes the workflow without holding a transaction over the long-lived Incident.
Starting is crash-safe: a retry replays the deterministic Alert root before adding the Incident
binding if a worker stopped between those two commits.

## Verification

Unit tests cover Trace ID wire validation, typed identities, canonical fingerprints, bounded size,
single-root causation, strict ordering, scope isolation, duplicates, missing components, and full
eight-component reconstruction. Workflow tests cover typed boundary admission, repeated
investigation events, safety-chain ordering, deterministic replay, completion, and crash resume.
PostgreSQL integration tests cover migration presence, round trip, transaction-owned concurrent
duplicate delivery, one-Incident ownership, cross-tenant read refusal, and stored-fingerprint
tamper detection.
