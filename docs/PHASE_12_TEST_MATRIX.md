# Phase 12 Test Matrix

## Core unit safety gate

Contract version: `phase12-core-unit-matrix/v1`

The first Phase 12 gate proves the framework-independent safety contracts without depending on a
database, container, provider, or network service. Run it with:

```text
python scripts/dev.py test --suite unit
```

The task runner owns the exact command. It collects only `tests/unit`, disables incidental Pytest
cache writes, resets the repository-wide coverage source selection, and measures this immutable
production scope:

- the complete `agentops_incident_commander.domain` package;
- deterministic Evidence Gate and Policy Engine application services;
- action preflight/execution, replay, and Tool Gateway idempotency boundaries;
- Diagnosis, Remediation, and versioned graph-state schema modules.

The gate requires 100% statement and branch coverage. Adding a production branch to this scope
without a unit test therefore fails the command. The ordinary `quality` and `pre-commit` tasks
remain the larger repository gates and include PostgreSQL/infrastructure integration paths.

## Requirement-to-test mapping

| Requirement | Primary production scope | Primary unit evidence | Required path classes |
| --- | --- | --- | --- |
| Domain invariants | `domain/*` | `test_domain_values.py`, `test_evidence.py`, `test_artifacts.py`, `test_action_executions.py`, `test_audit_domain.py` | valid construction, bounds, immutable identity, invalid type/value refusal |
| Evidence Gate | `domain/evidence_gate.py`, `application/evidence_gate.py` | `test_evidence_gate.py`, `test_evidence_gate_resolution.py`, `test_remediation_gate.py` | pass, missing/stale/cross-scope evidence, counter-evidence, historical-reference refusal |
| Policy | `domain/policy.py`, `application/policy_engine.py` | `test_policy_contracts.py`, `test_policy_engine.py`, `test_action_execution_preflight.py` | allowlisted evaluation, every denial family, risk/separation/expiry binding |
| Typed schemas | `workflows/diagnosis.py`, `workflows/remediation.py`, `workflows/state.py` | `test_diagnosis_schemas.py`, `test_remediation_schemas.py`, `test_graph_state.py` | valid round trip, malformed/extra/oversized fields, version and fingerprint mismatch |
| Redaction | `domain/redaction.py`, evidence/log/telemetry safety types | `test_redaction.py`, `test_evidence_processing.py`, `test_structured_logs.py`, `test_telemetry_safety.py` | secret classes, nested values, control characters, bounds, fail-closed invalid input |
| Idempotency and replay | execution/tool domain and application modules | `test_action_executions.py`, `test_action_executor.py`, `test_tool_gateway.py`, `test_audit_completeness.py` | first result, exact replay, conflicting reuse, duplicate/concurrent observation, bounded retry |
| State transitions | Incident, Approval, execution, verification, and postmortem domain types | `test_incident_lifecycle.py`, `test_approvals.py`, `test_health_verification_routing.py`, `test_health_verification_failure_routing.py`, `test_postmortem_revisions.py` | every legal edge, illegal edge refusal, terminal immutability, safe cancellation/failure route |

This matrix does not claim the later Phase 12 Testcontainers, E2E, crash, concurrency,
timeout/outage, adversarial-security, evaluation, or load items. The Agent-output property and
LangGraph all-path items are now covered by the separate gates below; all other items keep their
own TODO gates and must not use the unit result as substitute evidence.

## Reproducible measured result

On 2026-10-16, Python 3.12.14 and the locked dependency set collected and passed 2,479 unit tests.
The fixed production scope contained 5,149 statements and 1,570 branches, with no misses or partial
branches (100.00%). The repository-wide suite is still required before commit because integration
tests own database and other adapter behavior.

## Agent output and property gate

Contract version: `phase12-agent-output-properties/v1`

Run the independent generated contract with:

```text
python scripts/dev.py test --suite agent-output
```

Hypothesis `6.170.0` is locked as a development dependency. Every property uses a disabled example
database, deterministic derivation, no deadline, and at most 75 examples, so it has no hidden local
corpus, provider, credential, network, or wall-clock dependency. The gate disables coverage
collection because behavior generation is its purpose; the complete repository suite still owns
the 100% coverage requirement.

The ten properties cover:

- generated valid Diagnosis plans, candidate/non-candidate reports, and Remediation proposals with
  exact JSON round trips and stable canonical fingerprints;
- proposal material-fingerprint invariance only for monotonic version changes;
- generated unsupported schema versions, invalid identifiers, and coercible-looking numeric types;
- arbitrary adversarial values in extra fields plus an exhaustive 9-model-by-16-field rejection
  matrix for command, transport, target, credential, approval, policy, prompt, evidence-payload,
  and execution authority;
- prompt-like and JSON-shaped strings remaining inert scalar data rather than executable fields;
- generated syntactically valid fabricated Evidence IDs producing deterministic Evidence Gate
  `FAIL` decisions even with 10,000 confidence basis points.

On 2026-10-16, the locked Python 3.12.14 environment collected and passed all ten property tests.
The generated gate supplements, rather than replaces, the exact boundary examples in the unit
suite and later workflow, integration, E2E, and security suites.

## Workflow all-path gate

Contract version: `phase12-workflow-paths/v1`

Run the closed path set with:

```text
python scripts/dev.py test --suite workflow
```

The allowlisted task binds fourteen product-path names to twelve unique existing test nodes.
Duplicate node IDs are removed while preserving first-seen order because approval rejection and
expiry intentionally share one parameterized authority test, as do failed-verification
re-diagnosis and handoff. A missing or renamed node fails Pytest collection instead of silently
reducing coverage.

| Path contract | Authoritative exercised boundary |
| --- | --- |
| Diagnosis success | compiled read-only graph reaches `COMPLETE` with parallel tool references |
| Diagnosis replan | one bounded Gate replan accumulates budgets and then passes |
| Diagnosis refusal | typed model timeout/refusal/malformed outputs stop downstream effects |
| Diagnosis handoff | explicit handoff and exhausted replan budget terminate and are recorded |
| Approval success | durable interrupt resumes only after reloading exact persisted `APPROVED` authority |
| Approval rejected / expired | clock expiry, stored `EXPIRED`, and stored `REJECTED` all reach `NEEDS_HUMAN` |
| Recovery success | only a bound deterministic verification `PASS` reaches `CLOSED` |
| Verification re-diagnosis / handoff | `FAIL` routes exclusively to `INVESTIGATING` or `NEEDS_HUMAN` |
| Safe-boundary cancellation | every Diagnosis node cancels before its effect; paused resume may cancel without an effect |
| Compensation guards | failed rollback verification records the non-compensable route and executable MVP compensation surfaces are rejected |

On 2026-10-17, the task expanded the selected parameterized nodes into 34 tests; all passed. It
uses no database, provider, credential, network, coverage mutation, or generated-state cache. The
full repository suite remains mandatory before commit.

## External integration gate

Contract version: `phase12-external-integration/v1`

Run the complete container-owned adapter boundary with:

```text
python scripts/dev.py test --suite integration
```

The allowlisted task first checks the Docker daemon, then collects only `tests/integration`,
disables incidental Pytest cache writes, and disables coverage collection so this focused run
cannot replace or distort the repository-wide coverage gate. It uses the locked
`pgvector/pgvector:0.8.6-pg18` image through Testcontainers and a bounded 300-second test timeout.
The suite owns these external boundaries:

- Alembic upgrade, downgrade, re-upgrade, PostgreSQL constraints, transactions, tenant scoping,
  optimistic concurrency, advisory/row locks, append-only audit permissions, outbox and JobLease
  claims, stale-lease takeover, Approval races, action idempotency, and recovery routing;
- the installed pgvector extension, dimension checks, authoritative memory projection binding,
  and tenant/freshness/version-scoped similarity retrieval against real vector columns;
- the official PostgreSQL LangGraph saver, strict serialization, thread isolation, durable
  interrupts, every Diagnosis-node worker replacement boundary, committed-effect replay, and
  Approval resume with authoritative record reload;
- immutable Artifact/Evidence, Gate, model-call, execution, five-signal verification, postmortem,
  correlation, audit, and API persistence paths, including the complete authorized rollback and
  exact-replay chain;
- the Tool Gateway's classified retry persisted as the required started/retried/succeeded audit
  path, plus persistence-owned control-plane observer failure isolation.

Prometheus, Loki, Tempo, and OTLP exporters are external processes rather than Python persistence
or Tool Gateway adapters in this repository. Their topology and data-source wiring remain covered
by the Compose contract, while their telemetry adapters and export behavior remain covered by
isolated adapter tests. They are deliberately not mislabeled as Testcontainers coverage.

On 2026-10-17, Python 3.12.14, Docker Engine 29.8.0, and the locked dependency/image set collected
and passed 100 integration cases in 55.01 seconds. Eleven cases exercise PostgreSQL checkpoint
durability and 89 exercise migrations and operational repositories. The task-level elapsed time,
including the frozen-environment invocation, was 59.500 seconds. These local measurements prove
the bounded test contract only; they are not production throughput or reliability claims.

## Six-scenario product E2E gate

Contract version: `phase12-six-scenario-e2e/v1`

Run the closed fault matrix and its real recovery-chain proof with:

```text
python scripts/dev.py test --suite e2e
```

The fixed task checks Docker and then runs seven scenario-matrix cases plus the existing PostgreSQL
authorized rollback full-chain case. Runtime setup derives observations only from validated
`FaultBehavior`, typed alerts, immutable Artifacts/Evidence, and deterministic components. The six
Ground Truth manifests are loaded only after each runtime result exists, on the evaluator side, to
score target service, automation eligibility, action, and exact handoff reason. A source-level
guard also rejects evaluation outcome labels from the runtime half of the test.

Each scenario opens and groups an Alert, advances the real Incident state machine, constructs a
strict Diagnosis Report, and passes five independent current-Incident references through the
deterministic Evidence Gate. The recovery matrix is closed:

| Scenario | Required terminal route | Write count | Postmortem |
| --- | --- | ---: | --- |
| release-induced HTTP 500 | Policy `APPROVAL_REQUIRED`, approved rollback, deterministic verification, `CLOSED` | 1 | constrained, confirmed-fact-only draft |
| deployment-linked memory leak | Policy `APPROVAL_REQUIRED`, approved rollback with 300-second criterion, `CLOSED` | 1 | constrained, confirmed-fact-only draft |
| database pool exhaustion | `NEEDS_HUMAN / POOL_CAPACITY_ACTION_UNAVAILABLE` | 0 | prohibited before closure |
| Redis timeout | `NEEDS_HUMAN / DEPENDENCY_RECOVERY_ACTION_UNAVAILABLE` | 0 | prohibited before closure |
| downstream latency | `NEEDS_HUMAN / DOWNSTREAM_LATENCY_ACTION_UNAVAILABLE` | 0 | prohibited before closure |
| bad configuration | `NEEDS_HUMAN / CONFIGURATION_ACTION_UNAVAILABLE` | 0 | prohibited before closure |

The selected PostgreSQL case separately proves that an eligible path traverses human Approval,
the default-off mutation capability, preflight, immutable before/after snapshots, one local
simulator mutation, durable ActionExecution, five-signal verification, closure, audit, and exact
replay without a second mutation. Handoff-only incidents deliberately do not receive a postmortem:
the production generator requires `CLOSED`, so the path ends at its durable human wait until an
authorized external resolution is recorded and verified.

On 2026-10-17, the gate collected and passed all eight cases in 12.60 seconds; the task-level time
including Docker preflight and frozen invocation was 15.985 seconds. This is a reproducible local
functional result, not a production reliability or throughput claim.

## Worker-crash and stale-lease resilience gate

Contract version: `phase12-worker-resilience/v1`

Run the fixed crash-boundary matrix with:

```text
python scripts/dev.py test --suite resilience
```

The allowlisted task checks Docker and then resolves thirteen named resilience requirements to
thirteen unique test nodes. Parameter expansion produces twenty cases. Missing or renamed nodes
fail collection, coverage is disabled for the focused run, and the complete repository suite
remains the release gate.

| Boundary | Required durable behavior |
| --- | --- |
| Every Diagnosis node checkpoint | A new saver and worker resume the same thread; each operation occurs once |
| Effect committed before node checkpoint | The stable operation identity replays the committed result instead of repeating the effect |
| Approval interrupt | A new worker restores the interrupt and reloads the authoritative Approval before continuing |
| Action claim commit | Process loss after claim leaves one `STARTED` record; replacement delivery records replay and never dispatches |
| Action dispatch | Cancellation or unknown dispatch completion leaves the durable claim and never automatically redispatches |
| Action terminal persistence | Failure before commit preserves the claim; loss after commit replays the exact terminal result with one adapter call |
| Verification Evidence to decision | Five committed Evidence records are reused exactly after process loss; one decision is persisted |
| Verification decision to route | A durable decision can be routed by a replacement worker; exact replay adds no transition or audit |
| Verification route to acknowledgement | Concurrent replacement deliveries return one atomically committed closure |
| Expired Job lease | Sequential recovery emits the stale-recovery record; eight replacement workers produce one attempt-two owner and the crashed owner is rejected |
| Final expired Job lease | No replacement claim is issued; the configured `DEAD_LETTER` or `NEEDS_HUMAN` route is persisted |

The action contract is deliberately conservative. A replayed in-progress execution is observable
as `STARTED` and is not treated as successful or automatically repeated because the system cannot
infer whether the external mutation happened. The stale-work policy can therefore route it for
deterministic recovery or human handling without redeploying the known faulty version.

On 2026-10-17, Python 3.12.14 and Docker Engine 29.8.0 collected and passed all twenty cases in
29.02 seconds; the full allowlisted task, including Docker preflight, completed in 38.687 seconds.
These measurements prove only the fixed local crash/replay contract, not a production availability
or recovery-time claim.

## Duplicate-delivery and authority-race gate

Contract version: `phase12-concurrency-and-duplicates/v1`

Run the closed concurrency matrix with:

```text
python scripts/dev.py test --suite concurrency
```

The allowlisted task checks Docker and binds sixteen named requirements to sixteen real PostgreSQL
test nodes. One parameterized Approval node expands to four terminal-race combinations, producing
nineteen cases. Missing or renamed nodes fail collection; coverage remains owned by the complete
repository gate.

| Boundary | Required concurrent or duplicate behavior |
| --- | --- |
| API control commands | Exact key/body replays one response; changed or incomplete reuse fails closed |
| Correlation and Alert ingestion | Concurrent identical deliveries create one authoritative aggregate history |
| Audit ledger | Concurrent appends receive unique, tenant-contiguous sequence positions |
| Outbox | Duplicate aggregate intent is rejected; claims are disjoint; only the live lease owner publishes |
| Job queue | Concurrent claims are disjoint and no job is assigned twice |
| Approval API | Exact command replay returns the stored decision; changed command reuse conflicts |
| Approval lifecycle | approve/approve, approve/reject, approve/expire, reject/expire, and expire/expire each commit one terminal winner and one matching audit |
| Action lifecycle | Eight duplicate claims create one execution and one Incident execution transition |
| Action Executor | Eight duplicate deliveries call the rollback adapter exactly once |
| Action conflict | Changed idempotency content, active-target conflict, and Approval reuse are rejected |
| Verification closure | Concurrent route delivery creates one resolved/closed route and one success audit |

The tests distinguish a duplicate from a conflict. An exact duplicate may replay only immutable
stored output. A caller that reuses an identity with changed authority, request content, target, or
expected version receives a deterministic refusal; it never inherits the first caller's authority.

On 2026-10-17, Python 3.12.14 and Docker Engine 29.8.0 collected and passed all nineteen cases in
25.38 seconds; the full allowlisted task, including Docker preflight, completed in 32.797 seconds.
These are bounded local correctness measurements, not throughput or production-scale claims.

## Timeout, malformed-payload, and dependency-outage gate

Contract version: `phase12-failure-modes/v1`

Run the closed failure matrix with:

```text
python scripts/dev.py test --suite failure
```

The allowlisted task checks Docker and binds twenty-four named requirements to exact existing unit
and PostgreSQL integration nodes. Parameterized nodes expand the individual model scenarios,
adapter outcomes, malformed outputs, postmortem failures, database connection failures, and
dependency readiness cases. A missing or renamed node fails collection, coverage is disabled for
the focused run, and the complete repository suite remains the release gate.

| Failure boundary | Required behavior |
| --- | --- |
| Diagnosis tool timeout | Exhaust only the declared attempts, cancel unfinished peers, and persist no partial Evidence |
| Diagnosis and mock-model timeout/refusal/malformed output | Produce typed terminal failure without downstream tools, Gate calls, handoff claims, or invented usage |
| Tool input and output validation | Reject malformed or oversized payloads without adapter retry or raw payload audit |
| Tool retry policy | Retry only allowlisted classified errors with bounded backoff; exhaustion and unclassified failures stop deterministically |
| Tool cancellation or audit outage | Record bounded failure for cancellation; prevent dispatch when the audit writer is unavailable |
| Action dispatch timeout/failure | Classify the one attempted dispatch as timed out, failed, or uncertain; never infer success or retry the write |
| Health verification timeout | Cancel the all-or-nothing five-signal bundle and never persist a partial or authoritative PASS |
| Postmortem timeout/refusal/malformed output | Record the exact terminal model status and emit no unconstrained draft |
| PostgreSQL and Redis outage | Bound connection, command, pool, and forced-timeout paths; release held resources and expose no secret exception text |
| Simulator service dependency outage | Return stable 503/readiness failure and never convert unavailable storage into business success |
| Persisted Tool Gateway retry | Commit the hash-only started/retried/succeeded sequence through the real PostgreSQL AuditRepository |

The gate deliberately combines isolated failure injection with one external persistence proof. It
does not call unavailable providers, accept caller-selected backends, or weaken the separate full
integration and repository-wide verification gates.

On 2026-10-27, Python 3.12.14 and Docker Engine 29.8.0 expanded the twenty-four named requirements
into and passed all forty-two cases in 28.30 seconds. The focused Pytest task completed in 51.797
seconds, and the full allowlisted command including Docker preflight completed in approximately
56.234 seconds. These are bounded local correctness measurements, not availability or production
reliability claims.
