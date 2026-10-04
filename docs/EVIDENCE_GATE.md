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

The characteristic evaluator now rejects future or stale observation windows, expired Evidence,
quality below the configured basis-point floor, and records that do not explicitly attest
`source-available`. Independent-source counting uses supporting evidence only and deduplicates
direct observations by source type plus source instance. Derived observations, historical
references, and untrusted input never increase that count.

`evaluate_evidence_gate` combines reference and characteristic failures with explicit completeness
rules. Unresolved material counter-evidence and declared missing evidence fail closed by default.
The resulting decision records model confidence and includes it in the reproducibility fingerprint,
but confidence is never consulted when selecting `PASS` or `FAIL`: a complete zero-confidence claim
can pass, while an incomplete maximum-confidence claim fails.

`EvidenceGateRepository` stores the canonical input snapshot and immutable typed decision under the
owning tenant and Incident. The input fingerprint provides idempotent replay and conflict detection;
the same transaction appends an `evidence.gate_decided` audit event whose request and result hashes
bind the input snapshot and complete decision. Reads require tenant, Incident, candidate, and
fingerprint together, preventing cross-Incident substitution.

## Verification

Unit tests cover every field bound, semantic/schema versions, canonical ID ordering, duplicates,
support/counter overlap, missing-evidence bounds, outcome/reason consistency, duplicate reasons,
UTC normalization, fingerprints, and confidence values at both extremes without granting them
decision authority.
Application tests cover complete support/counter resolution, scoped reader calls, missing IDs,
cross-Incident/ID substitution, missing Artifacts, and content-hash alteration.
Characteristic tests cover fresh independent sources, future/stale/expired observations, low
quality, unavailable sources, derived-source non-counting, and duplicate or uncited inputs.
Decision tests cover unresolved counter-evidence, declared missing evidence, configurable rule
flags, canonical fingerprints, and both confidence extremes without changing deterministic outcomes.
PostgreSQL integration tests cover migration round trips, persisted input/decision reconstruction,
idempotent replay, audit binding, conflict rejection, and tenant/Incident scoping.
The Phase 5 adversarial matrix proves that fabricated references, missing or altered Artifacts,
stale or low-quality observations, correlated sources, declared missing evidence, and unresolved
counter-evidence all fail closed even when model confidence is at its maximum value.
