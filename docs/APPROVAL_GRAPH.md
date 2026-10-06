# Approval interrupt and durable resume

Phase 8 adds a dedicated LangGraph wait boundary between deterministic Policy evaluation and the
future deterministic Action Executor. The graph is orchestration, not an authorization source: it
cannot approve a proposal, alter an Approval, or execute recovery.

## Persisted state and interrupt

`ApprovalWaitState` is a strict, frozen, versioned state containing only bounded identifiers,
proposal and Policy-decision fingerprints, phase, error code, checkpoint sequence, and UTC update
time. Its PostgreSQL thread identity is a SHA-256 digest of tenant, Incident, and workflow-run
identity with an `approval-` prefix. Raw correlation fields remain checkpoint metadata for audit
reconstruction and are checked against restored state.

An `AWAITING_APPROVAL` node emits a durable `APPROVAL_REQUIRED` interrupt containing only:

- tenant and Incident references;
- Approval reference;
- proposal fingerprint; and
- Policy-decision fingerprint.

It contains no proposal body, credentials, model content, or caller-supplied approval result.
Resume accepts only the content-free `RECHECK` directive. An `approved: true` claim or any other
resume shape is rejected rather than interpreted as authority.

## Authoritative recheck

After resume, the node reloads the Approval and immutable invalidation marker from the configured
tenant-scoped store. It advances to `READY_TO_EXECUTE` only when the stored Approval:

1. exists under the expected tenant and Approval ID;
2. has no invalidation marker;
3. matches the Incident, proposal fingerprint, and Policy-decision fingerprint in checkpointed
   state;
4. is `APPROVED`; and
5. remains before its UTC expiry.

A still-pending record returns to the same durable interrupt with an incremented checkpoint
sequence. Missing or cross-tenant records, invalidation, binding mismatch, expiry, and rejection
route to `NEEDS_HUMAN` with a stable error code. None can reach execution readiness. This boundary
does not replace the future Executor's immediate RBAC, Policy, state, Approval, expiry,
idempotency, and lock checks.

## Crash recovery and verification

The graph uses the same pickle-disabled allowlisted serializer as Diagnosis checkpoints. Tests
cover exact interrupt disclosure, forged and malformed resume directives, repeated pending
resume, every terminal/refusal route, cross-tenant isolation, strict state validation, and stable
checkpoint identities. A PostgreSQL container test closes the first saver and graph while the
interrupt is pending, changes the external Approval to `APPROVED`, creates a new saver and graph,
and proves that the new worker restores the checkpoint and reloads the authoritative record before
entering `READY_TO_EXECUTE`.
