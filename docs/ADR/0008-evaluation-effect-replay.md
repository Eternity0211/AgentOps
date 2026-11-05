# ADR 0008: Durable evaluation investigation effects

- Status: Accepted
- Date: 2026-11-05

## Context

LangGraph checkpoints retain references, not the autonomous adapter's compiled plan or read
results. Replacing a worker between nodes therefore requires independently committed effects.
Repeating a provider request after a lost acknowledgement also consumes unbounded resources.

## Decision

Keep the adapter in evaluation, consistent with ADR 0007. Reuse the existing PostgreSQL command
idempotency table under the isolated `evaluation.investigation.effect/v1` operation namespace.
No new runtime dependency, broker, table, or state-schema change is introduced. Existing business
API commands cannot select this namespace.

Use tenant/Incident/workflow/slot identities, with actor, correlation, causation, Prompt,
graph/schema versions, input window, alert hash, catalog, and exact adapter source hashes bound
to the request fingerprint. Require Operator permission and an existing same-tenant Incident.
An actor change cannot create a second record for the same workflow slot. Use a nonblocking
PostgreSQL advisory transaction lock to serialize claims, commit claim plus hash-only audit,
release the connection, then perform the bounded external effect. Commit the vetted typed
result, result hash, and append-only completion audit atomically. Replay verifies both the
result hash and independent audit binding. Provider bodies and prompts are not cache payloads;
tool data is redacted before persistence and injection quarantine remains in Evidence building.

Persist typed PLAN/DIAGNOSE results, read-tool results, and completed Evidence identifier sets.
Recompile restored plans through the existing compiler and compare checkpoint references and
query fingerprints before any dispatch. Rehydrate Evidence from SQL and its immutable Artifacts.
The job handler accepts this store explicitly; production startup remains disabled.

## Consequences

A claim without a committed result is uncertain and is never automatically stolen or retried.
This provides bounded refusal after an ambiguous effect, not exactly-once external execution
or guaranteed liveness. Worker replacement after completion can reuse the result before the
graph transition is checkpointed. A failure inside multi-record Evidence persistence can leave
immutable partial records; the uncertain claim prevents a second creation attempt. Operators
must inspect such failures. Source/input changes fail closed instead of replaying stale work.

## Alternatives

Storing mutable process dictionaries in checkpoints would couple graph state to adapter payloads.
Redis would add an unmeasured control-plane dependency. Blind retries would obscure ambiguous
provider calls. A future runtime-wide effect repository may replace this evaluation composition
through its own migration and ADR; this decision does not enable production provider invocation.

## Verification

Use real PostgreSQL, official PostgreSQL checkpoints, SQL Evidence/report/trace/progress stores,
and the leased job consumer. Inject failures before tool dispatch, before Evidence creation,
after PLAN, after Evidence commit, and after DIAGNOSE commit but before graph transitions.
After replacement, require exactly two model and two tool effects for each successful fixture.
Also test concurrent claims, changed input/actor/tenant, missing Incident, incomplete results,
redaction refusal, and tampering even when the attacker recomputes the cached payload hash.
Provider fixtures remain controlled substitutes and cannot count as real-model quality tests.
