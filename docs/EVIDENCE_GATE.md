# Deterministic Evidence Gate

Phase 5 begins with a framework-independent domain contract for the deterministic Evidence Gate.
It is not an agent and model confidence is never an authority signal.

## Versioned contract

`EvidenceGateRules` fixes the rule/schema version, minimum quality, maximum evidence age, minimum
independent-source count, counter-evidence resolution requirement, and declared-missing-evidence
policy. Every bound is finite and validated at construction.

`RootCauseEvidenceClaim` separates supporting Evidence IDs, counter-evidence IDs, declared missing
evidence, and whether counter-evidence was resolved. IDs are unique, disjoint, and canonically
ordered. Optional model confidence is retained only as reproducibility metadata; changing it does
not change evidence references or satisfy a rule.

`EvidenceGateDecision` is strictly `PASS` or `FAIL`. A pass cannot contain failure reasons, while a
failure must contain typed, stable `EvidenceGateReasonCode` values. The decision retains the exact
rules version, evaluated Evidence IDs, UTC evaluation time, and an input fingerprint for later
persistence and audit.

## Current boundary

`resolve_gate_evidence_references` now reads every supporting and counter-evidence ID through a
tenant/Incident-scoped port, then independently rechecks the returned Evidence ID, tenant, and
Incident. It retrieves the bound Artifact with the authenticated principal and verifies metadata,
content hash, and byte size. Missing IDs, ownership substitution, and absent or altered Artifacts
produce typed failure reasons and are excluded from the verified set.

Subsequent Phase 5 batches will evaluate freshness, quality, source independence, and
counter-evidence, then persist the full input snapshot/decision and emit audit events. No passing
decision is produced by reference resolution alone.

## Verification

Unit tests cover every field bound, semantic/schema versions, canonical ID ordering, duplicates,
support/counter overlap, missing-evidence bounds, outcome/reason consistency, duplicate reasons,
UTC normalization, fingerprints, and confidence values at both extremes without granting them
decision authority.
Application tests cover complete support/counter resolution, scoped reader calls, missing IDs,
cross-Incident/ID substitution, missing Artifacts, and content-hash alteration.
