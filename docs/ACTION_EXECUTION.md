# Recovery ActionExecution lifecycle

Phase 8 defines the immutable domain record, PostgreSQL persistence, and deterministic application
composition used by the Action Executor. The real mutation capability remains disabled: no runtime
write adapter is registered, and Phase 9 verifier/failure-routing gates must pass before enablement.

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

`ImmutableActionSnapshotWriter` implements both snapshot ports against the Artifact Store. Before
storage it reads the server-resolved deployment target and requires the observed version to remain
the preflight version. After dispatch it requires the adapter result, a second deployment read, and
the configured stable version to agree. Canonical JSON binds the snapshot phase, full target scope,
observation time, deployed version, and—only for the after snapshot—the opaque backend operation
identity. Its content hash is the `ActionSnapshot` hash binding.

Artifact identities derive deterministically from tenant, Incident, actor, caller idempotency key,
and snapshot phase. An exact retry therefore reloads and validates the original immutable snapshot
before any new deployment observation. A changed target or operation identity cannot reuse it, and
a concurrent identical create returns only the content-identical winner. The writer exposes no
path, URL, command, manifest, credential, or caller-selected deployment target.

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
terminal event. The repository also exposes an explicit replay operation that locks and verifies
the authoritative stored result before appending a distinct `REPLAYED` lifecycle record and
hash-bound audit event. It never mislabels a replay as a new start and never mutates the stored
execution. The Executor composition calls this operation within the same transaction that observes
every replay path.

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

This boundary produces bounded execution authority; it does not call a write adapter. The Executor
composition runs it together with the durable idempotency/target claim, replay audit, timeout
classification, and disabled capability gate immediately before dispatch.

## Bounded mutation dispatch

`BoundedRollbackDispatcher` defines the only write invocation boundary without enabling a real
adapter. Its server-side capability flag defaults to disabled. When explicitly enabled by test or
future Phase 9 composition, it accepts only a started `ActionExecution` whose tenant, Incident,
Approval, actor, idempotency key, proposal/Policy fingerprints, and resolved target exactly match
the preflight authority.

The dispatcher invokes the typed adapter exactly once under a positive maximum-five-minute timeout;
the configured rollback contract remains 30 seconds and declares no write retries. A confirmed
pre-effect refusal becomes `FAILED`, a deadline becomes `TIMED_OUT`, and an unclassified exception,
wrong service/version result, or unavailable after Artifact becomes `UNCERTAIN`. Only an exact
stable-version result plus a successfully persisted target-bound after snapshot becomes
`SUCCEEDED`. This outcome means the mutation result is known; it does not declare service recovery,
which remains exclusively owned by the Phase 9 deterministic Health Verifier.

## Crash-safe Executor composition

`RollbackActionExecutor` is the single application path from the strict rollback request to a
stored ActionExecution result. It first checks the server capability flag, reruns authoritative
preflight, and persists an idempotent target-bound before snapshot. It then constructs the bounded
execution request and calls `PostgresActionExecutionStore`, whose claim transaction serializes the
idempotency key and target, and atomically commits the `STARTED` lifecycle and audit records before
any adapter invocation.

When the claim is new, the Executor invokes the bounded dispatcher exactly once and commits the
terminal result, lifecycle record, audit record, and target-lock release in a separate transaction.
When the claim resolves to an existing in-progress or terminal execution, the same claim
transaction appends the hash-bound `REPLAYED` lifecycle and audit records before returning; the
dispatcher is never invoked. Keeping claim and replay audit in one transaction prevents a
concurrent completion from invalidating the observed replay between those operations.

`PostgresLifecycleActionExecutionStore` is the recovery composition adapter for those durable
boundaries. A new claim and the legal `READY_TO_EXECUTE -> EXECUTING` Incident transition commit in
one transaction. Completion and its safe Incident route also commit together: `SUCCEEDED` enters
`VERIFYING`; a confirmed pre-effect `FAILED` result returns to `INVESTIGATING`; `TIMED_OUT` and
`UNCERTAIN` enter `NEEDS_HUMAN`. These execution outcomes can never resolve or close an Incident.
Each state bridge adds a deterministic, hash-bound audit record, locks the tenant-owned Incident,
and reuses that audit identity on exact replay so later workflow progress cannot be duplicated or
rewound. A state mismatch rolls back the ActionExecution claim/completion transaction.

Cancellation, worker loss after claim, or a terminal-commit failure cannot trigger automatic
redispatch: a later identical delivery observes the durable `STARTED` record and records a replay.
That conservative result remains available for the later deterministic failure-routing and stale
execution recovery policy; the known faulty version is never inferred as a compensation target.

## Verification

Unit tests cover every lifecycle outcome, immutable/versioned transitions, canonical fingerprint
bindings, UTC normalization, invalid field types and schema versions, before/after tenant,
Incident, service, environment, target, version and time substitution, invalid error codes,
completion ordering, stable-version proof, and duplicate terminal completion refusal.
PostgreSQL integration tests cover migration round trips, initial claim, active-target exclusion,
changed-request rejection, eight-way concurrent duplicate claiming, exact completion replay,
terminal result replay, per-observation replay audit, forged/missing/stale replay refusal,
transactional lifecycle/audit writes, and target-lock release.
Preflight tests cover successful authoritative reconstruction, missing authentication, Viewer and
cross-tenant refusal, missing or changed Incident state, absent/rejected/expired/invalidated
Approval, proposal/Policy substitution, lost Evidence Gate admission, changed Policy rules,
unavailable deployment observation, and already-stable target refusal.
Dispatcher tests prove the default kill switch prevents invocation, authority mismatches and time
regression fail before side effects, success calls once, writes receive no automatic retry, timeout
and confirmed refusal remain distinct, unknown/mismatched results are uncertain, after-snapshot
loss is uncertain, and task cancellation propagates to the safe-boundary owner.
Snapshot-writer tests prove before/after version confirmation, canonical Artifact content and hash
bindings, deterministic exact replay without a second deployment read, concurrent-create reuse,
operation/scope substitution refusal, malformed stored-content refusal, and storage-metadata
substitution refusal.
Executor tests prove fixed preflight/claim/dispatch/finish ordering, disabled and rejected
pre-effect refusal, terminal classification persistence, cancellation and finish-failure replay
safety, atomic replay auditing, and eight-way PostgreSQL duplicate delivery with exactly one
adapter dispatch. Together with Approval lifecycle/graph tests, the Phase 8 exit matrix covers
concurrent approval, rejection and lazy expiry routing, successful mutation classification,
terminal replay, duplicate delivery, adapter timeout, unauthorized roles, and attempts to bypass
Incident, Evidence Gate, Policy, Approval, target-resolution, or capability controls. The runtime
mutation capability remains disabled by default; the Phase 9 full-chain E2E enables it only inside
the local test composition.
Lifecycle-store integration additionally proves atomic execution/Incident transitions, exact
completion replay without duplicate transitions, eight-way concurrent claim serialization,
transaction rollback on invalid Incident state, success-to-verification routing, confirmed-failure
re-diagnosis, and timeout/uncertainty human handoff.
The full-chain integration additionally proves one persisted execution and one simulator mutation
flow through five live Evidence records, one persisted `PASS`, and closure, while exact replay
cannot recollect, redispatch, reverify, or duplicate an Incident transition.
