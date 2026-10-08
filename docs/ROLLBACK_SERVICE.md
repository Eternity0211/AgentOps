# Typed rollback_service contract

Phase 8 defines the first and only MVP write-tool contract. `rollback_service` is a forward
recovery action from a known faulty deployment to a server-configured stable version. The contract,
resolution boundary, and server-bound adapter are validated through an explicitly enabled local
simulator E2E. The adapter remains unregistered in production and the default capability stays off.

## Caller-controlled input

The immutable v1 input contains exactly four fields:

- `schema_version`, fixed to `1.0.0`;
- `incident_id`, which must equal the Tool Gateway call's Incident scope;
- `approval_id`, identifying the proposal-bound human Approval; and
- `idempotency_key`, identifying the durable result-replay scope.

All identifiers use the conservative 1–128 character identifier grammar. Additional fields are
forbidden, including service, environment, command, URL, path, target, and target version. The
typed parser independently rejects missing, extra, non-string, unsupported-version, malformed,
and cross-Incident inputs after JSON Schema validation.

The `ToolDefinition` is exactly version `1.0.0`, `WRITE`, `HIGH` risk, requires
`approved_action:execute`, requires durable result replay, permits one gateway attempt, has bounded
input/output sizes and timeout, and uses request/result-hash audit metadata. One gateway attempt is
intentional: any later transport retry must pass through the Executor's durable idempotency and
result-replay boundary rather than blindly repeat a write.

## Server-owned target resolution

`RollbackTargetCatalog` is deployment configuration, never model or caller input. Every immutable
entry is scoped by tenant, conservative service name, and closed Policy environment, and contains
an opaque backend target reference, an ordered unique allowlist of semantic versions, and one
stable version drawn from that allowlist.

Resolution requires an exact tenant/service/environment match and an observed current version that
is itself allowlisted. It returns a typed target with the expected current version and configured
stable version. Unknown tenant, service, environment, current version, malformed/injected service,
duplicate configuration, and an already-stable no-op all fail closed. There is no fallback to a
similarly named service, latest release, arbitrary target, or caller-selected version.

The future deterministic Action Executor must obtain the service from the approved proposal, the
environment from the Policy context, and the current version from server-owned deployment state;
then it must repeat RBAC, Incident state, Policy, Approval hash/expiry/invalidation, idempotency,
and lock checks immediately before mutation. Defining this contract does not satisfy or bypass any
of those requirements.

## Server-bound deployment adapter

`ServerBoundRollbackAdapter` maps the authorized execution record to a narrow deployment-control
backend. That backend accepts only the server-resolved `ResolvedRollbackTarget` and typed
Idempotency Key, then reports an opaque operation identity and the observed deployed semantic
version. It exposes no shell command, URL, manifest, namespace, credential, or caller-selected
target. The bounded dispatcher still owns timeout and uncertain-result classification.

The adapter is not registered in production composition and the capability remains disabled by
default. The local simulator supplies the concrete test backend and full-chain E2E gate; a real
production backend, transport composition, and an explicit production enablement decision are
still required before production mutation is available.

The shared deployment observation port also feeds `ImmutableActionSnapshotWriter`. It persists
canonical before/after JSON as immutable hash-bound Artifacts under identities derived from the
authorized idempotency scope and snapshot phase. Before mutation, the observed version must still
match preflight. After mutation, the adapter result, observed version, and configured stable version
must all agree. Exact retries reuse the validated original snapshot, while changed scope or backend
operation identity fails closed.

## Local simulator backend

`LocalSimulatorRollbackBackend` is a deliberately non-production adapter for the versioned local
recovery E2E suite. It is constructed with one exact server-owned `ResolvedRollbackTarget` and a
shared simulator deployment state. Its only mutation moves that state from the expected faulty
version to the configured stable version and creates a deterministic opaque operation identity from
the authorized scope and idempotency key. The simulator `/versionz` endpoint reads the same locked
state, so later verification observes the actual transition rather than a test-only return value.

An async serialization lock plus the typed idempotency map makes concurrent identical calls return
one result after one state transition. A different key after the transition, changed target, stale
current version, invalid state, or refused/mismatched transition fails closed. The backend exposes
no command, URL, manifest, namespace, credential, arbitrary version, or production provider
surface. It is not part of production process composition and does not change the default-disabled
mutation capability.

## Verification

Unit tests verify exact metadata and schemas, strict round trips, immutable values, caller-field
rejection, command/URL/path/target injection refusal, cross-Incident refusal, every allowlist
configuration invariant, exact stable-version resolution, tenant/environment isolation, unknown
and already-stable version refusal, and the absence of any caller-controlled service or target.
Adapter tests prove exact target/idempotency delegation, typed result enforcement, and the absence
of command, URL, manifest, or namespace arguments.
Local simulator backend tests prove eight-way concurrent exactly-once transition, stable replay,
HTTP-visible version change, every target-field substitution refusal, stale-state refusal, invalid
transition classification, and the continued absence of a production-enabled write route.

The authorized full-chain PostgreSQL E2E explicitly enables the capability only inside the test,
uses a real persisted Approval-bound authority, and composes durable lifecycle execution with the
server-bound adapter, shared simulator deployment state, immutable snapshots, live five-signal
collection, persisted deterministic verification, and success routing. It asserts exactly one
deployment transition, one ActionExecution, five Evidence records, one `PASS`, and the legal
`READY_TO_EXECUTE -> EXECUTING -> VERIFYING -> RESOLVED -> CLOSED` path. Exact replay returns the
same records without another mutation, collection, verification, or closure.
