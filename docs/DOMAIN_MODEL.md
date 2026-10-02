# Pure Domain Model

This document records the implemented Phase 2 domain contract. The implementation lives in
`src/agentops_incident_commander/domain` and imports no API, ORM, workflow, simulator, or model
provider code.

## Value objects and time

Incident, Alert, actor, correlation, and causation identifiers are distinct immutable runtime
types. Their values are opaque: the domain accepts UUID/ULID-style values and other conservative
identifiers of 1–128 characters, but does not infer ordering or authority from their text. Values
must start with an alphanumeric character and may then contain alphanumerics, `.`, `_`, `:`, or
`-`. This keeps identifiers bounded and safe to put in structured audit data.

Mutable aggregates use a positive `AggregateVersion` starting at one. Every accepted mutation
compares an explicit expected version and advances the stored version. A stale command raises a
typed `OptimisticVersionError`; adapters must map that failure to their own transport convention
rather than bypassing it.

Domain timestamps must be timezone-aware. Aware inputs are normalized to UTC, while naive inputs
are rejected. Incident event times cannot precede the latest aggregate event. Event reasons are
trimmed, single-line, and limited to 512 characters.

Incident severity is the closed vocabulary `SEV1`, `SEV2`, `SEV3`, and `SEV4`. Authentication
roles remain a separate Phase 2 principal/RBAC task and are deliberately not implied by the actor
identifier.

## Incident lifecycle

`ALLOWED_TRANSITIONS` is the authoritative pure-domain transition table corresponding exactly to
the lifecycle in the project specification and architecture. Every accepted transition returns an
immutable record containing Incident ID, prior/new state, prior/new version, actor, reason,
correlation ID, causation ID, and UTC timestamp.

`CLOSED` and `CANCELLED` are the only terminal states. `AWAITING_APPROVAL` and `NEEDS_HUMAN` are
durable waits. Every other non-terminal state has at least one legal outgoing route, including
`RESOLVED -> CLOSED`; exhaustive tests cover every state pair so an added or missing edge cannot
silently change the contract.

Cancellation has three explicit rules:

1. A request in one of the nine specification-listed pre-side-effect safe states records the
   request and transitions immediately to `CANCELLED`.
2. A request in `EXECUTING`, `VERIFYING`, `COMPENSATING`, or `VERIFYING_COMPENSATION` is recorded,
   advances the optimistic version, and remains pending while deterministic work completes.
3. When deterministic work subsequently routes to a cancellable safe state, that route is
   recorded first and a second transition applies `CANCELLED`. If verification succeeds, the
   Incident instead continues through `RESOLVED -> CLOSED`. Requests from `RESOLVED`, `CLOSED`, or
   `CANCELLED` are rejected.

The domain returns all records created by one command together with the new immutable aggregate.
Future repositories must persist the aggregate and records atomically and enforce the same
expected-version comparison; they must not reproduce or weaken the state rules in an adapter.

## Verification scope

Unit tests enumerate the complete expected transition graph, execute every declared edge, reject
every undeclared state pair, assert non-terminal liveness, cover immediate/deferred cancellation,
and verify optimistic concurrency, time normalization, chronology, terminal timestamps, bounded
values, and import isolation. Persistence constraints, API mappings, and LangGraph route parity are
not claimed until their later Phase 2 batches exist.
