# Recovery ActionExecution lifecycle

Phase 8 defines the immutable domain record and PostgreSQL persistence foundation used by the
deterministic Action Executor. This is not an enabled Executor: authorization rechecks, bounded
adapter dispatch, replay-audit orchestration, and the real mutation capability remain separate
incomplete work.

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

## Durable claim and completion

Migration `20261006_0014` adds `action_executions`, `action_execution_locks`, and
`action_execution_events`. The execution row stores the typed authority and server-resolved target,
the before snapshot binding, terminal result, and a request fingerprint that intentionally excludes
attempt identity and timing while retaining the Approval, actor, proposal, Policy decision, target,
and before observation. Database uniqueness scopes an idempotency key to tenant, actor, Incident,
and key, and permits an Approval to authorize only one action execution.

Claiming takes transaction-scoped PostgreSQL advisory locks for both the idempotency scope and the
server-resolved target before inspecting durable state. Concurrent identical claims therefore
create one execution and return that stored record to all other callers. Reusing the key with a
different authority, target, or before snapshot fails closed; a different key cannot acquire an
already-active target. Completing an execution locks its row, writes exactly one terminal event,
and removes the target lock in the same transaction. Exact completion retries and later identical
claims return the stored terminal result without creating a second lifecycle transition.

The append-only audit ledger is transactionally bound to the initial `STARTED` event and the one
terminal event. A later application-service batch must add a distinct audit event for each replay
observation before the complete Executor TODO can close; the persistence layer does not mislabel a
replay as a new execution start.

## Authoritative execution preflight

`RollbackExecutionPreflight` is a framework-independent application boundary that runs before an
execution can be claimed. It accepts only the strict typed rollback request and approval-bound
proposal/Policy records, requires the authenticated tenant Operator execution permission, then
reloads the Incident, Approval, and immutable invalidation marker through tenant-scoped ports. The
Incident must still be `READY_TO_EXECUTE`; the Approval must still be `APPROVED`, unexpired, not
invalidated, and exactly bound to the proposal, Policy input, Policy decision,
risk, and current server Policy version.

The preflight re-resolves the stored passing Evidence Gate decision and deterministically evaluates
the current server-owned Policy rules with the approval-bound input. A decision that is no longer
exactly reproducible is refused. Only after those checks does it ask a server-owned deployment
observation port for the current version and resolve the service, environment, backend reference,
and stable version from the immutable rollback target catalog. The request still cannot contain a
service, version, command, URL, path, or provider target.

This boundary produces bounded execution authority; it does not call a write adapter. The next
Executor composition batch must run it together with the durable idempotency/target claim, replay
audit, timeout classification, and disabled capability gate immediately before dispatch.

## Verification

Unit tests cover every lifecycle outcome, immutable/versioned transitions, canonical fingerprint
bindings, UTC normalization, invalid field types and schema versions, before/after tenant,
Incident, service, environment, target, version and time substitution, invalid error codes,
completion ordering, stable-version proof, and duplicate terminal completion refusal.
PostgreSQL integration tests cover migration round trips, initial claim, active-target exclusion,
changed-request rejection, eight-way concurrent duplicate claiming, exact completion replay,
terminal result replay, transactional lifecycle/audit writes, and target-lock release.
Preflight tests cover successful authoritative reconstruction, missing authentication, Viewer and
cross-tenant refusal, missing or changed Incident state, absent/rejected/expired/invalidated
Approval, proposal/Policy substitution, lost Evidence Gate admission, changed Policy rules,
unavailable deployment observation, and already-stable target refusal.
