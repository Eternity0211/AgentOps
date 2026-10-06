# Deterministic Policy Engine Contracts

Phase 8 defines framework-independent, versioned input and decision contracts before adding policy
rules. The Policy Engine is deterministic and is never an agent.

## Evaluation input

`PolicyEvaluationInput` binds the tenant, Incident, immutable proposal identity/version/fingerprint,
passing Evidence Gate decision fingerprint, requesting actor and roles, environment, allowlisted
action, service target, blast-radius class, maintenance-window status, separation-of-duties flag,
and UTC request time. The schema is versioned and the complete canonical value has a stable SHA-256
fingerprint. Role ordering and equivalent timezone representations cannot change that fingerprint.

The only current action identity is `rollback_service`. Risk levels are `LOW`, `MEDIUM`, `HIGH`,
and `CRITICAL`; environment, blast radius, and maintenance status are closed enums rather than
model-generated prose.

## Decision output

`PolicyDecision` binds a semantic policy version, exact input and proposal fingerprints, risk level,
outcome, structured reasons, UTC evaluation time, and optional approval lifetime. Outcomes are
`ALLOW`, `DENY`, or `APPROVAL_REQUIRED`. Allowed results carry only a `POLICY_SATISFIED` reason;
approval-required results include `APPROVAL_REQUIRED` and a one-minute-to-24-hour lifetime; denied
results cannot contain either success marker and never carry an approval lifetime.

Reason codes cover environment, role, action, target, Evidence Gate, blast radius, maintenance
window, and separation-of-duties failures. Text is bounded single-line audit context, not an
execution instruction. Inputs, reasons, and decisions are immutable and hash-bound.

This batch defines contracts only. The next batch implements the exact deterministic rule ordering
and outcome/risk calculation.

## Verification

Tests cover every enum and type boundary, proposal and Evidence Gate bindings, normalization,
timezone stability, canonical fingerprints, role ordering, numeric and collection bounds,
immutability, reason uniqueness, result/reason consistency, and approval-lifetime limits.
