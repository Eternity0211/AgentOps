# Proposal-bound Approval lifecycle

Phase 8 implements Approval as a deterministic, tenant-scoped aggregate. It is not an agent and
cannot relax a Policy decision. A request can be created only from an exact
`APPROVAL_REQUIRED` decision whose input and proposal fingerprints match the supplied Policy input.
The request clock cannot precede Policy evaluation, and expiry is calculated from the Policy
evaluation time so delayed request creation never extends the authorized lifetime.

## Immutable binding

Every Approval binds its tenant, Incident, proposal ID/version/fingerprint, Policy decision
ID/fingerprint, Policy input fingerprint, proposer, risk level, separation requirement, request
time, and expiry. Its complete canonical state has a SHA-256 fingerprint. The mutable surface is
limited to status, optimistic version, decision time, deciding actor, and bounded reason.

The finite lifecycle is:

```text
PENDING -> APPROVED
PENDING -> REJECTED
PENDING -> EXPIRED
```

Terminal records cannot be decided again. Human approval or rejection at or after the deadline is
converted to `EXPIRED`; it never produces a late approval. Expiry uses a configured deterministic
service actor and reason. PostgreSQL constraints independently enforce timestamp ordering, status/
decision-field consistency, fingerprint form, positive versions, and one Approval per exact Policy
decision fingerprint in a tenant.

## Authorization and separation

Creating a request requires `remediation:request`, exact actor/role equality with the Policy input,
and matching tenant ownership. Human decisions require `approval:decide`. Medium, high, and
critical risk always require an Approver whose Actor ID differs from the proposer; policy can also
require that separation for low risk. Only a low-risk Policy input that explicitly disables
separation can be approved by one identity holding both explicitly assigned roles.

## Atomic audit

Each command row-locks and compares the expected aggregate before changing it. The aggregate,
append-only before/after lifecycle snapshot, and content-free `approval.requested`,
`approval.approved`, `approval.rejected`, or `approval.expired` audit event share the caller's
transaction. Audit request/result hashes bind the prior and next Approval fingerprints; request
creation additionally binds the Policy decision fingerprint. A duplicate audit ID or stale state
rolls the entire transaction back.

This lifecycle does not execute recovery. Later batches must invalidate approval after proposal
mutation, resume the durable workflow, and revalidate the exact record immediately before the
deterministic Executor runs.

## Verification

Unit tests cover request, approve, reject, explicit and lazy expiry, terminal-state refusal,
proposal/Policy mismatch, stale and future Policy decisions, anonymous/wrong-role/cross-tenant/
self-approval refusal, configurable low-risk separation, invariants, immutability, and audit hash
binding. PostgreSQL integration tests cover migration round trips, tenant-scoped reads, lifecycle
history, state/audit transactionality, and rollback on audit conflict.
