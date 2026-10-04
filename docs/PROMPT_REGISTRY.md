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

`PromptLifecycleManager` now implements the RBAC-protected draft, evaluate, promote, and rollback
state machine. Only principals with `admin:manage` may issue lifecycle commands. Evaluation requires
a non-empty, versioned, all-pass regression fixture result; promotion accepts only `EVALUATED`
versions and retires the prior active version atomically through the store port. Rollback never
mutates old content: it creates a newer version whose content/model/schema contract exactly copies
the retired target and whose predecessor binds the previously active version.

Every accepted transition carries a hash-bound `prompt.*` audit event into the same atomic store
operation. Request and result hashes contain Prompt fingerprints/statuses and bounded evaluation
results, not Prompt content. The PostgreSQL store adapter remains the next part of this lifecycle
TODO; production model invocation remains disabled. No inline Prompt is approved by these contracts.

## Verification

Unit tests cover content/hash binding, UTF-8 byte limits, normalized line endings, semantic
versions, exact schema compatibility, complete model-parameter bounds, optional seed extremes,
typed trace links, lifecycle values, rollback ordering and resolution, duplicate versions, family
purpose drift, multiple active versions, exact lookup, active lookup, and deterministic catalogs.
Lifecycle tests cover Admin-only access, failed regression refusal, illegal transition refusal,
first and replacement promotion, old-version retirement, copy-based rollback, and complete audit
emission with request/result hashes.
