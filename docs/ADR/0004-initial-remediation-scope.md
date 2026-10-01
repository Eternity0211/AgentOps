# ADR 0004: Initial Remediation Scope

- Status: Accepted
- Date: 2026-10-01

## Context

An extensible write surface makes early safety reasoning and end-to-end validation too broad. The simulator has a natural recovery primitive for deployment regressions.

## Decision

The only initial write tool is a versioned, typed, allowlisted `rollback_service`. It requires Incident ID, Approval ID, and Idempotency Key and resolves service/version targets through server-owned records. It cannot accept shell, arbitrary URL, path, or free-form provider arguments. It remains subject to schema, evidence gate, policy, approval, execution lock, verification, and rollback/failure handling.

## Consequences

The first version demonstrates the entire safety chain deeply rather than many shallow actions. Additional write tools need a separate ADR, threat review, policy rules, executor adapter, verification contract, rollback behavior, and adversarial tests.

## Verification

Contract and E2E tests reject missing/mismatched IDs, stale or modified approvals, replay with changed parameters, unauthorized roles, unknown services/versions, and bypass attempts; concurrent identical calls produce one mutation and a stable stored result.
