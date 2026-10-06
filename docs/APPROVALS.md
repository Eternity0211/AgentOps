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

## Material revision invalidation

An accepted material revision writes a separate immutable invalidation marker rather than rewriting
an already approved record or mislabeling it as rejected. The marker binds the Approval fingerprint,
prior proposal fingerprint, replacement proposal identity/version/full fingerprint, replacement
material fingerprint, actor, time, and audit event. One marker per Approval is enforced in
PostgreSQL. Any later execution check must treat the marker as authoritative even though the
historical Approval retains its original human decision.

Revision processing accepts only the same proposal ID and Incident with a strictly higher version
and a changed material fingerprint; a version-only bump is rejected. It validates the complete
Pydantic proposal schema before recording invalidation, then re-resolves the exact passing Evidence
Gate decision and rebuilds the complete Policy input from the replacement proposal and current
requester/context. Gate rejection or Policy denial leaves the old Approval invalidated. A passing
Policy result can only request a brand-new Approval; the old approval is never copied forward.

This lifecycle does not execute recovery. The durable
[Approval interrupt](APPROVAL_GRAPH.md) now reloads the exact Approval and invalidation marker
after each resume and permits only a valid, unexpired, fingerprint-matched `APPROVED` record to
reach execution readiness. A later Executor batch must independently repeat all required checks
immediately before mutation.

## Verification

Unit tests cover request, approve, reject, explicit and lazy expiry, terminal-state refusal,
proposal/Policy mismatch, stale and future Policy decisions, anonymous/wrong-role/cross-tenant/
self-approval refusal, configurable low-risk separation, invariants, immutability, and audit hash
binding. Revision tests cover malformed schemas, identity/version tricks, version-only edits,
material changes, duplicate invalidation, Gate rejection, Policy denial, and fresh-approval
routing. PostgreSQL integration tests cover migration round trips, tenant-scoped reads, lifecycle
history, invalidation markers, state/audit transactionality, and rollback on audit conflict.
Approval-graph tests additionally cover forged resume data, pending re-interrupt, missing,
cross-tenant, invalidated, mismatched, rejected, and expired records plus new-worker PostgreSQL
checkpoint restoration.
