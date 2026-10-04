# Prompt Registry

Phase 6 starts with a framework-independent, immutable Prompt Registry contract. It records the
exact inputs needed to reproduce model behavior without making a Prompt or model an execution
authority.

## Versioned definition

Each `PromptDefinition` contains a stable Prompt ID and semantic version, one bounded purpose
(`DIAGNOSIS`, `REMEDIATION`, or constrained `POSTMORTEM`), normalized content, and a verified
SHA-256 content fingerprint. Exact provider/model settings include temperature and top-p in basis
points, maximum output tokens, and an optional bounded seed. Input and output schema versions are
explicit semantic versions rather than implicit application assumptions.

Creation metadata retains actor, correlation ID, causation ID, and UTC timestamp without embedding
request or response content. Lifecycle status is one of `DRAFT`, `EVALUATED`, `ACTIVE`, or
`RETIRED`. A rollback predecessor must reference an earlier version of the same Prompt family and
must resolve inside a constructed Registry.

## Fail-closed selection

`PromptRegistry` rejects empty or mutable-style inputs, duplicate identity/version pairs, purpose
changes within a family, multiple active versions, and unresolved rollback predecessors. Exact
resolution never falls back to another version. Active resolution fails when no single active
version exists. Catalog output is deterministically ordered and may be filtered by purpose.

This batch defines contracts only. Draft/evaluate/promote/rollback commands, persistence, RBAC,
regression gates, and production model invocation remain subsequent Phase 6 work. No inline Prompt
is approved for production use by this definition alone.

## Verification

Unit tests cover content/hash binding, UTF-8 byte limits, normalized line endings, semantic
versions, exact schema compatibility, complete model-parameter bounds, optional seed extremes,
typed trace links, lifecycle values, rollback ordering and resolution, duplicate versions, family
purpose drift, multiple active versions, exact lookup, active lookup, and deterministic catalogs.
