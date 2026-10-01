# ADR 0005: Recovery Action and Compensation Semantics

- Status: Accepted
- Date: 2026-10-01
- Clarifies: ADR 0004

## Context

ADR 0004 selected `rollback_service` as the only MVP write tool. Earlier workflow wording also sent failed health verification to a generic Rollback Controller. That overloaded “rollback”: `rollback_service` is already the intended recovery from a faulty version, while compensating it could redeploy the version known to be faulty.

The six fault scenarios also do not all have a safe version-rollback remedy. Treating every diagnosis as recoverable by `rollback_service` would reward unsafe plans and distort recovery metrics.

## Decision

Use distinct terms and records:

- A **recovery action** attempts to restore service health. In the MVP, `rollback_service` moves a service from a diagnosed faulty deployment to a server-resolved known stable version.
- A **compensation action** is a separately authorized safe inverse for a previously executed write. It is never inferred merely because an action failed verification.
- Failed verification after `rollback_service` routes to bounded re-diagnosis or `NEEDS_HUMAN`. The platform must not automatically redeploy the known faulty version.
- The generic compensation states/controller remain unreachable for `rollback_service`. A future write tool can enable them only through versioned reversibility metadata, a typed compensation action, independent Policy Engine evaluation, approval when required, idempotency, and compensation verification.
- Version rollback is eligible only for release-induced HTTP 500 and the explicitly deployment-linked memory-leak scenario when current evidence proves the introducing deployment and identifies a stable predecessor. Pool exhaustion, Redis timeout, downstream latency, and configuration drift are diagnosis-and-handoff scenarios in the MVP.
- Evaluator fault cleanup is isolated test infrastructure, not a runtime recovery tool and not recovery credit.

## Consequences

The MVP favors correct refusal/handoff over a misleading recovery-rate target. Recovery and compensation have different records, state transitions, policies, and metrics. Additional write tools must state whether a safe inverse exists; the default is non-compensable.

Approval `REJECTED` and `EXPIRED` remain Approval statuses. Incident routing returns to remediation planning or waits for a human, avoiding stranded pseudo-terminal states. `CLOSED` and `CANCELLED` are the only terminal Incident states.

## Rejected alternatives

- Automatically redeploy the pre-action version after failed `rollback_service`: it is the known suspected/faulty version and is not a safe baseline.
- Count evaluator cleanup as recovery: it bypasses the product's policy/execution boundary and invalidates the metric.
- Force `rollback_service` for every scenario: version rollback cannot safely repair dependency, resource-pool, or external configuration faults.

## Verification

State-machine tests cover every legal and illegal transition and prove every non-terminal state has an exit. Workflow tests prove rejected/expired approvals route to replanning or human wait, cancellation occurs only at safe boundaries, failed rollback verification never targets the faulty version, non-eligible scenarios produce no write execution, and future compensation remains unreachable without explicit reversible-tool metadata plus policy/approval.
