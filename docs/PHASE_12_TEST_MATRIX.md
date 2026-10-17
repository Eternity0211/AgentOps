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
