# Remediation Agent Proposal Contract

Phase 8 begins with a strict, versioned structured output for the Remediation Agent. It is a
proposal only: it cannot authorize policy, create an Approval, call a write tool, execute recovery,
or declare recovery successful.

## Bounded recovery scope

The only accepted action is `rollback_service`. Its parameters contain a conservative service
identifier and the Evidence ID that establishes the introducing deployment. There is deliberately
no command, URL, path, target version, Approval ID, or idempotency key. The stable predecessor and
current deployment are resolved later from server-owned records, outside model authority.

Every proposal binds its Incident, root-cause candidate, immutable Evidence Gate input fingerprint
and complete decision fingerprint, proposal identity/version, and schema version. Canonical JSON
over all fields produces a SHA-256 fingerprint; changing any material proposal field therefore
changes the approval/policy binding used by later phases.

`RemediationEvidenceGate` is the only current admission path. It re-loads the decision through a
tenant-, Incident-, candidate-, and input-fingerprint-scoped store port. The returned immutable
decision must match that scope, have outcome `PASS`, and reproduce the proposal's complete decision
fingerprint. Missing rows, failed decisions, cross-tenant lookups, stale inputs, changed decisions,
and high-confidence failed candidates all fail closed before policy or execution can exist.

## Preconditions, verification, and failure

Typed prerequisites require current-version Evidence, server-side stable-predecessor resolution,
policy authorization, human approval, and an execution lock. They cannot be disabled by model
output. Verification conditions explicitly bound error rate, P95 latency, health endpoint, deployed
stable version, new alerts, and a 60-to-3,600-second stability window. These remain proposed
conditions until the deterministic Phase 9 verifier evaluates real observations.

Failure handling permits either immediate human handoff or one to three bounded re-diagnosis
attempts followed by handoff. It always forbids redeploying the faulty version. Compensation
eligibility for `rollback_service` is literally and structurally `false`; generic compensation is
not part of this action.

Risk assumptions are unique, normalized, single-line strings with explicit count and length limits.
Extra fields and coercion are rejected, including execution-bearing or bypass fields.

## Verification

Schema tests cover strict JSON round trips, immutability, canonical fingerprint changes, exact
collection and numeric bounds, unsafe text, type coercion, unknown actions, model-supplied execution
targets, non-bypassable prerequisites, complete verification conditions, failure-route/budget
consistency, and the non-compensable rollback invariant.
Application and PostgreSQL integration tests additionally prove that a proposal is refused before
the decision is durably recorded, admitted after the exact passing decision commits, and refused
under another tenant.
