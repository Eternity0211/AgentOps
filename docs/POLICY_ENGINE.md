# Deterministic Policy Engine Contracts

Phase 8 defines framework-independent, versioned input, rules, and decision contracts. The Policy
Engine is deterministic and is never an agent.

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

## Rules and evaluation

`PolicyRules` is a server-owned, immutable ruleset with a semantic version, environment/role/action/
service/blast-radius allowlists, maintenance-window and separation-of-duties switches, and a bounded
approval lifetime. Allowlists may deliberately be empty as a fail-closed kill switch. Service names
must already be normalized and the collection is bounded.

Evaluation checks every category in a fixed order so repeated runs produce an explainable, stable
reason sequence:

1. environment;
2. requester role;
3. action;
4. service target and action-to-proposal binding;
5. exact tenant, Incident, proposal, candidate, immutable passing Evidence Gate, and fingerprint
   binding;
6. blast radius;
7. active maintenance window when required; and
8. separation of duties when required.

Every failed check is retained in the denied decision; denial has no approval lifetime. Risk is
deterministic: multi-service scope is `CRITICAL`, otherwise production is `HIGH`, staging is
`MEDIUM`, and development is `LOW`. A rollback satisfying every rule still returns only
`APPROVAL_REQUIRED`. This evaluator never emits `ALLOW`, creates an approval, or invokes an
executor, preserving the mandatory human-approval boundary.

## Verification

Tests cover every enum and type boundary, proposal and Evidence Gate bindings, normalization,
timezone stability, canonical fingerprints, role ordering, numeric and collection bounds,
immutability, reason uniqueness, result/reason consistency, approval-lifetime limits, every rule
in isolation, combined failure ordering, optional constraints, deterministic risk, and the
non-bypassable approval-required outcome.
