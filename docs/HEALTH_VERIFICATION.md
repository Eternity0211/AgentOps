# Deterministic health-verification contract

Phase 9 begins with a framework-independent, versioned contract for deciding whether a completed
recovery action produced an observably stable service. It is a deterministic component, not an
agent, and it cannot accept a model success claim or confidence score.

## Scope and scenario binding

`HealthVerificationCriteria` binds the tenant, Incident, successful ActionExecution, service,
environment, server-resolved stable version, scenario, metric limits, zero-new-alert requirement,
stability-window duration, sampling-gap limit, rules version, and schema version. The closed MVP
scenario set contains only release-induced HTTP 500 and deployment-linked memory leak, the two
scenarios eligible for `rollback_service` under ADR 0005.

Release-induced HTTP 500 requires at least a 60-second stable window. Deployment-linked memory leak
requires at least 300 seconds so a momentary process response cannot masquerade as recovery. Both
remain capped at 3,600 seconds. Server rules permit no new alerts and bound sampling gaps to five
minutes or less; proposal thresholds cannot weaken these structural requirements.

## Immutable observations

`HealthVerificationObservation` binds the same authority scope and expected stable version. It
contains a strictly ordered, bounded sample sequence whose first and last timestamps exactly cover
the declared window. Every sample records integer-basis-point error rate, integer-millisecond P95
latency, health-endpoint status, deployed semantic version, and new-alert count.

Five distinct Evidence IDs bind the error-rate series, latency series, health endpoint, deployed
version, and alert query. Observation collection and expiry timestamps are explicit and UTC.

The application resolver treats these references as a non-bypassable prerequisite. Every ID must
resolve in the same tenant and Incident to a direct, unexpired Evidence record and an authorized
immutable Artifact whose bytes still match the recorded hash and size. The Evidence must cover the
complete observation window, report an available source, carry no prompt-injection classification,
and use the controlled source/tool/query purpose for its signal. Error rate and P95 use
`METRIC/query_metrics`; health uses `TRACE/query_traces`; version uses
`DEPLOYMENT/query_deployments`; and new alerts use `LOG/query_logs`.

Each Artifact contains a canonical `health-verification-signal` document under schema `1.0.0`.
It repeats the exact service, environment, signal, window bounds, and strictly ordered sample
timestamps and values. The resolver compares the entire document to the typed observation; extra,
missing, substituted, malformed, or reordered content fails closed. It returns typed reason codes
for missing ownership, unavailable Artifact content, expiry, trust, injection, window, source,
query, and value failures. The health evaluator is not called unless all five distinct series pass.
The read-only `LiveHealthVerificationCollector` now constructs these canonical series from five
deployment-injected backend ports. It queries the existing bounded metrics port twice with fixed
`http_request_error_rate` and `http_request_duration_p95` names, exact service/environment/window,
and a server-controlled step. Three dedicated verifier ports return health-probe, active-version,
and cumulative new-alert samples at the same fixed timestamps. They expose no URL, query language,
command, credential, or caller-selected backend target.

All five calls share one timeout and complete as an all-or-nothing bundle. The collector rejects
incomplete or dropped metric windows, wrong metric names or labels, missing/reordered timestamps,
incomplete probe/version/alert series, negative or non-finite values, and converted values outside
the domain bounds. Error-rate ratios become integer basis points and P95 seconds become integer
milliseconds using deterministic half-up rounding. The result contains the typed observation and
five direct, complete, immutable Evidence/Artifact records; the evidence resolver independently
rechecks that bundle before evaluation. Concrete production transports remain deployment adapters
and are not claimed by this repository-local contract test.

`PostgresPersistedHealthVerifier` composes that collector with immutable Artifact storage,
tenant/Incident-scoped Evidence persistence, full Artifact re-resolution, deterministic
evaluation, and the PostgreSQL verification record. It accepts only a successful execution and a
server-produced plan bound to the exact execution scope and stable target. Exact decision replay
returns before collection. Existing Artifact/Evidence identities are reusable only when their
complete metadata and bytes are unchanged; any conflict fails closed. The resulting audit binds
the execution causation, deterministic input fingerprint, and decision fingerprint.

## Deterministic decision

`evaluate_health_verification` accepts only a `SUCCEEDED` ActionExecution and exact-scope criteria
and observation records. It evaluates reasons in fixed order:

1. observation expiry;
2. insufficient stability duration;
3. excessive sampling gap;
4. any error-rate breach;
5. any P95 latency breach;
6. any unhealthy endpoint sample;
7. any deployed-version mismatch; and
8. any new alert.

All samples must pass. A degraded intermediate sample therefore fails a flapping window even when
the first and last samples are healthy. A pass has no reasons; a failure retains every unique
applicable stable reason code. The decision binds criteria, observation, and ActionExecution
fingerprints plus a canonical combined input fingerprint, exact evaluation time, rules version,
and schema version.

This decision describes observed post-action health only. It does not transition the Incident,
enable the real mutation route, create compensation, or redeploy the known faulty version. Those
application routes remain separate deterministic work.

## Durable verification record

PostgreSQL stores each accepted observation and deterministic decision as one immutable
`health_verification_runs` record. The record binds tenant, Incident, successful ActionExecution,
scenario, complete sample window, the five Evidence IDs, every criteria/observation/execution/input
fingerprint, ordered outcome reasons, evaluation time, rules version, and schema version. Composite
foreign keys keep the ActionExecution and each Evidence reference in the same tenant and Incident;
dangling or cross-scope references cannot be committed.

The repository recomputes the decision before writing, reloads the exact durable successful
ActionExecution, confirms all five Evidence records exist in scope, and validates a hash-bound
`health.verification_decided` audit event. A repeated decision ID, observation ID, or identical
execution/input pair is accepted only when the complete stored observation and decision match.
Changed reuse fails closed. Reads recompute both immutable fingerprints so direct storage
corruption is detected rather than returned as trusted verification data. Persistence remains
descriptive: it neither changes Incident state nor invokes a write or compensation path.

## Successful-verification routing

`SuccessfulHealthVerificationRouter` is the only application path in this phase that consumes a
persisted `PASS` to close an Incident. It requires an authorized same-tenant Operator, reloads the
decision by tenant and Incident, and delegates to a transaction-scoped repository that locks both
the verification and Incident rows. The repository rechecks the complete stored decision and
permits only the legal `VERIFYING -> RESOLVED -> CLOSED` sequence. Both transitions carry the
verification decision ID as causation and commit atomically with one
`health.verification_succeeded` audit event whose request and result hashes bind the decision and
final route.

The decision ID is also the route's durable idempotency identity. Exact retries and concurrent
delivery return the already-closed aggregate without adding transitions or another success audit.
A partial, substituted, or conflicting route fails closed. A failed/missing/cross-tenant decision,
an Incident outside `VERIFYING`, an unauthorized caller, time regression, or an unbound audit can
never close the Incident. A deferred cancellation does not override an observed successful
recovery: the atomic route completes through `RESOLVED` and `CLOSED`, as required by the lifecycle
contract. Failed-verification routing remains a separate unfinished deterministic path.

## Failed-verification routing

`FailedHealthVerificationRouter` consumes only a persisted `FAIL` and the exact immutable
`rollback_service` proposal whose fingerprint is stored on the successful ActionExecution. Its
pure route decision binds the verification and proposal fingerprints, current and maximum
re-diagnosis counts, consumed count, outcome, and target state. When the proposal's bounded budget
has room, exactly one attempt is consumed and the Incident moves from `VERIFYING` to
`INVESTIGATING`; an exhausted budget or explicit zero-budget handoff moves it to `NEEDS_HUMAN`.

The transaction locks the verification, ActionExecution, and Incident, recomputes the route, and
records one transition plus a hash-bound `health.verification_failed` audit event. The transition
reason exposes the bounded count and explicitly records `compensation=forbidden`. The verification
decision ID is the idempotency/causation identity, so concurrent or repeated delivery cannot
consume another attempt or append another route. A changed proposal, decision, budget result,
scope, Incident state, audit, or partial stored route fails closed.

If cancellation was requested while verification was running, the failure result is recorded
first. Once the route reaches cancellable `INVESTIGATING` or `NEEDS_HUMAN`, the Incident aggregate
immediately appends the deferred `CANCELLED` transition in the same transaction. Replay accepts
only that exact two-transition sequence; cancellation can neither interrupt observation nor erase
the deterministic failure outcome.

This router has no write-adapter or compensation dependency and its target type admits only
`INVESTIGATING` or `NEEDS_HUMAN`. The typed remediation contract still fixes
`compensation_eligible=false` and `redeploy_faulty_version=false`; even deliberately constructed
invalid proposal objects are rejected before routing. It therefore cannot restore the known faulty
version or enter `COMPENSATING`.

## Recovery orchestration boundary

`RollbackRecoveryCoordinator` is the single application composition point from an authorized
rollback execution to a persisted verification decision and exactly one terminal route. It does
not enable or register a mutation adapter. A non-successful ActionExecution returns immediately;
the verifier and both route handlers remain unreachable. A successful execution must retain the
exact tenant, Incident, Approval, Idempotency Key, proposal fingerprint, policy-input fingerprint,
and policy-decision fingerprint supplied to the attempt before verification can begin.

The persisted decision must bind that exact tenant, Incident, ActionExecution ID, and execution
fingerprint. `PASS` can call only the success router and must return the same Incident in `CLOSED`.
`FAIL` can call only the failure router and must return the same Incident in `INVESTIGATING` or
`NEEDS_HUMAN`. Untyped results, substituted scope, or any other state fail closed. Mutation
success therefore never implies recovery, and a failed verification cannot accidentally enter a
success, compensation, or faulty-version redeployment route.

## Verification

Tests cover healthy release and memory-leak criteria, scenario-specific window floors, immutable
fingerprints, every individual reason in fixed order, intermediate flapping, missing coverage,
excessive gaps, stale observations, invalid numeric/type/version bounds, duplicate Evidence
references, time regression, non-successful actions, and cross-tenant/Incident/execution/service/
environment/version substitution. Application tests additionally cover successful five-series
resolution, missing and cross-scope Evidence, unavailable/tampered/malformed Artifacts, expiry,
non-direct trust, quarantined input, incomplete windows, wrong source/tool/query purpose, and exact
sample-value mismatch. The verifier contract and evidence-binding modules maintain complete
statement and branch coverage. Live-collection tests additionally cover exact backend requests,
unit conversion, end-to-end Artifact re-resolution, incomplete/dropped/substituted series,
misaligned timestamps, invalid values, strict identities/time bounds, and whole-bundle timeout.
PostgreSQL integration tests additionally prove migration upgrade/full downgrade/re-upgrade,
round-trip retrieval, exact replay, tenant/Incident isolation, missing Evidence refusal,
non-reproducible decisions, audit substitution, durable ActionExecution substitution, identity
conflicts, and observation/decision corruption detection. Success-routing tests prove RBAC,
same-tenant resolution, atomic resolved/closed transitions, hash-bound audit, exact retry,
concurrent serialization, failed-verification refusal, wrong-state refusal, record substitution,
and corrupted partial-route rejection.
Failure-routing tests additionally cover bounded attempt consumption, exhaustion and explicit
handoff, exact replay, proposal/decision/route substitution, wrong-state and audit refusal,
corrupted stored routing, deferred cancellation at the first safe boundary, and the structural
compensation/faulty-version prohibition. Together with collector whole-bundle timeout tests and
the domain's intermediate-flapping/stability-window cases, these cover the Phase 9 verifier
resilience matrix. Coordinator tests additionally prove execution short-circuiting, complete
authority and decision binding, exclusive PASS/FAIL dispatch, route-result scope and state
validation, and rejection of every untyped or substituted boundary result. PostgreSQL integration
tests compose the coordinator with durable verification reads and the real success/failure route
repositories for both outcomes; exact replay returns the stored route without a second route audit.
Persisted-verifier tests additionally cover live PASS/FAIL collection, durable five-Evidence
records, exact decision replay, invalid execution/principal/plan identities, collection scope
substitution, Artifact and Evidence conflicts, incomplete re-resolution, and audit identity
rejection.
The authorized local rollback E2E composes that verifier with the lifecycle-aware executor,
server-bound simulator mutation, immutable action snapshots, and success router. It reaches
`CLOSED` only after five live Evidence records produce one persisted `PASS`; exact replay returns
the existing execution, verification, and closed Incident without a second mutation, collection,
decision, or route transition. This test-only enablement does not change the production-default
capability flag.
