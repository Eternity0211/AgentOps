# Model Call Tracing

Phase 6 records every attempted model invocation before provider dispatch and completes it exactly
once afterward. The trace is metadata-only: Prompt text, context, response text, provider exception
messages, authorization data, and raw telemetry have no persistence fields.

## Reproducibility contract

Each trace binds a stable Call ID to tenant, Incident, workflow run, graph node, attempt, correlation
and causation IDs. It copies the exact active Prompt ID, semantic version, content SHA-256,
provider/model, temperature and top-p basis points, maximum output tokens, optional seed, and input
and output schema versions. The repository independently resolves that tenant-scoped Prompt version
and refuses a trace whose fingerprint, lifecycle status, settings, or schemas differ.

Request and response bodies are represented only by caller-computed SHA-256 digests. A trace starts
as `STARTED` before external dispatch and may finish once as `SUCCEEDED`, `FAILED`, `TIMED_OUT`, or
`REFUSED`. This leaves an observable incomplete record after a worker crash instead of silently
losing the attempted call.

## Token and cost accounting

Provider token use records input, output, cached-input, reasoning, and total counts. The total must
equal input plus output; cached and reasoning counts must remain within their respective totals.
Cost uses bounded integer nanounits, an uppercase three-letter currency, a source classification,
and a semantic rate-card version. Floating-point cost is prohibited. If a failed call cannot be
metered, both token and cost values remain absent and a typed unavailability reason is mandatory;
the platform does not replace missing provider data with invented zeroes.

## Persistence and audit

Alembic revision `20261005_0010` adds `model_call_traces`. Composite foreign keys bind every row to
the owning tenant/Incident and exact registered Prompt version. Database checks enforce hashes,
settings, terminal state shape, token arithmetic, cost provenance, and explicit missing-metering
semantics. Tenant/Incident and tenant/workflow indexes support later timeline and observability
queries.

`model.call_started` and `model.call_finished` append-only audit events commit in the same
transactions as their corresponding trace state. Their request/result hashes bind canonical trace
metadata, never model content. Row locks and an exact expected-state comparison reject duplicate or
stale completion.

Production provider invocation remains disabled until the Diagnosis graph and mock/provider
adapters are implemented. Those adapters must use this start/finish port; they may not create an
untraced model path.

## Verification

Unit tests cover exact settings, complete and unavailable metering, integer cost, token arithmetic,
registered-active Prompt enforcement, all terminal outcomes, duplicate completion, bounded failure
codes, and the absence of payload fields. PostgreSQL integration tests cover migration round trips,
Prompt/Incident binding, tenant-scoped reads, exact persisted metering, hash-only data, audit counts,
Prompt metadata forgery refusal, and stale completion refusal.
