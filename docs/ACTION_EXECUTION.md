# Recovery ActionExecution lifecycle

Phase 8 defines the immutable domain record used by the deterministic Action Executor. This is a
foundation, not an enabled Executor: PostgreSQL locking, idempotent claiming, authorization
rechecks, adapter dispatch, and the real mutation capability remain separate incomplete work.

## States and bindings

An execution begins in `STARTED` with a positive optimistic version and binds the exact tenant,
Incident, Approval, caller idempotency key, actor, proposal fingerprint, Policy-decision
fingerprint, server-resolved rollback target, and before snapshot. Terminal states are:

- `SUCCEEDED`, with a target-bound after snapshot proving the configured stable version;
- `FAILED`, for a confirmed bounded failure;
- `TIMED_OUT`, when the configured deadline expires; and
- `UNCERTAIN`, when the mutation result cannot be established safely.

Every non-success terminal state requires a bounded stable error code. A started execution cannot
carry terminal data, terminal records cannot finish again, completion cannot precede start, and
the optimistic version advances exactly once on completion. The canonical execution fingerprint
binds all authority, target, snapshot, status, time, error, and version fields.

## Snapshot safety

Before and after observations are references to immutable Artifacts rather than embedded provider
responses. Each snapshot binds tenant, Incident, service, Policy environment, opaque backend target
reference, deployed semantic version, UTC observation time, and content hash. The before snapshot
must match the resolved current version and cannot postdate execution start. Any after snapshot
must match the same scope and occur between start and completion. Success additionally requires
the after version to equal the server-configured stable version.

No execution state contains shell text, credentials, provider arguments, or a compensation target.
In particular, the faulty before version is observation data and never an authorization to deploy
it again.

## Verification

Unit tests cover every lifecycle outcome, immutable/versioned transitions, canonical fingerprint
bindings, UTC normalization, invalid field types and schema versions, before/after tenant,
Incident, service, environment, target, version and time substitution, invalid error codes,
completion ordering, stable-version proof, and duplicate terminal completion refusal.
