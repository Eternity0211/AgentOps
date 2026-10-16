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

This matrix does not claim the later Phase 12 Agent-property, LangGraph all-path, Testcontainers,
E2E, crash, concurrency, timeout/outage, adversarial-security, evaluation, or load items. Those keep
their separate TODO gates and must not use this unit result as substitute evidence.

## Reproducible measured result

On 2026-10-16, Python 3.12.14 and the locked dependency set collected and passed 2,479 unit tests.
The fixed production scope contained 5,149 statements and 1,570 branches, with no misses or partial
branches (100.00%). The repository-wide suite is still required before commit because integration
tests own database and other adapter behavior.
