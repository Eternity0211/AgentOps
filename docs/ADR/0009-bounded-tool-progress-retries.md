# ADR 0009: Bounded tool progress retry history

- Status: Accepted
- Date: 2026-11-05

## Context

A parallel graph wave can fail before one read is dispatched. Its progress projection already
records FAILED or CANCELLED, while the durable effect cache correctly contains no claim. A
replacement worker may safely dispatch this pending read, but cannot overwrite its terminal
progress. Ignoring the old failure would erase useful operational history.

## Decision

Introduce progress schema 1.1.0 with at most three immutable prior attempt summaries per step.
Keep terminal-success replay unchanged. Only a recorder explicitly configured for bounded retries
may start a new attempt after FAILED/CANCELLED; it appends the previous status, failure code and
timestamps before starting the new attempt. The default recorder still forbids terminal changes.
The evaluation composition enables two retries, matching its three-attempt Job budget. This
projection is never execution authority: ADR 0008's effect store independently refuses uncertain
dispatch and reuses confirmed results.

Read legacy 1.0.0 progress only after verifying its original identity and canonical fingerprint;
return a 1.1.0 projection and persist the upgraded form on the next update. No history is invented
for legacy snapshots. Prior attempts remain visible in the persisted projection and fingerprint.

## Consequences

Retry history is bounded and content-free. A failed physical call is never silently replaced by
a success: the previous attempt remains inspectable. Progress retry does not authorize another
network call, change tool budgets, approve recovery, or guarantee liveness after an uncertain effect.

## Alternatives

Overwriting terminal fields loses failure history. Refusing every partially completed wave prevents
safe restart of reads that were never dispatched. Automatically repeating uncertain reads obscures
outcomes and cost. Replanning an entire investigation merely to repair a projection adds calls.

## Verification

Test opt-in bounds, retained failure/cancellation attempts, terminal-success replay, legacy hash
verification/migration and malformed history. Real PostgreSQL job/checkpoint tests must recover a
wave containing a completed read and an undispatched read without duplicate calls, while refusing
a wave containing an uncertain dispatched read. Replanning must retain earlier Evidence.
