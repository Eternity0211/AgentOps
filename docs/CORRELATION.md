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

The runtime-wiring batch must append links at the eight authoritative component boundaries. Until
that integration and its full-chain tests pass, the parent Phase 11 TODO remains open.

## Verification

Unit tests cover Trace ID wire validation, typed identities, canonical fingerprints, bounded size,
single-root causation, strict ordering, scope isolation, duplicates, missing components, and full
eight-component reconstruction. PostgreSQL integration tests cover migration presence, round trip,
exact replay, concurrent duplicate delivery, one-Incident ownership, cross-tenant read refusal, and
stored-fingerprint tamper detection.
