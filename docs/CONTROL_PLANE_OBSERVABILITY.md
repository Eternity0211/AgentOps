# Control-plane observability

Phase 11 uses a versioned, content-free observation contract for the platform that diagnoses and
controls incidents. This layer is distinct from diagnosed-system telemetry and from durable Audit
Events. OpenTelemetry describes timing and operational health; it does not authorize actions,
prove evidence, replace the correlation ledger, or declare recovery.

## Contract

`ControlPlaneObservation` schema `1.0` has no field capable of carrying a prompt, response, tool
arguments/result, Evidence content, exception text, SQL, URL, credential, or arbitrary payload. It
contains only:

- a closed component, operation, and outcome;
- tenant, Incident, correlation, causation, operation, and optional workflow-run identities;
- bounded integer duration and attempt metadata;
- conservative route/result/subject identifiers;
- the existing typed, content-free `ModelMetering` value for exact token and integer-nanounit cost
  accounting.

Started records cannot claim a duration. Terminal records require a bounded duration. Attempt
values are positive and capped; optional maximum attempts cannot be lower than the current attempt.
All identifiers retain the existing domain validation and all timestamps normalize to UTC.

The observer port belongs to the application layer and defaults to a no-op. `safely_record` catches
adapter failures, logs only component/operation names, and never lets telemetry alter graph state,
model-call persistence, Tool Gateway audit, retry behavior, or any recovery authority.

## OpenTelemetry signals

The infrastructure adapter owns isolated SDK providers and bounded OTLP/HTTP queues. It emits:

| Signal | Dimensions/content |
| --- | --- |
| `agentops.control_plane.operations` | closed component, operation, outcome, optional bounded route |
| `agentops.control_plane.duration` | the same low-cardinality dimensions; milliseconds for terminal records |
| `agentops.model.calls` / `agentops.model.errors` | registered provider/model and typed outcome |
| `agentops.model.tokens` | provider/model/outcome plus input, output, cached-input, reasoning, or total token category |
| `agentops.model.cost` | integer nanounits plus currency and measurement source |
| `agentops.tool.attempts` / `agentops.tool.retries` | registered tool/version and typed outcome |
| operation Span | bounded identities and metadata, with explicit observed duration and error status |
| `control_plane.operation` OTLP log | the same content-free attributes, linked to its operation Span |

Tenant/Incident/correlation/causation/operation identities are deliberately absent from metric
dimensions but present in Spans and logs. They enable reconstruction without creating unbounded
time-series cardinality. Model rate-card version and metering-unavailable reason remain trace/log
metadata rather than metric labels.

## Investigation instrumentation

Every executable Diagnosis graph node is wrapped at graph compilation. The observer records the
node's stable operation identity, duration, terminal route, safe cancellation, pause interrupt,
handoff, deterministic Evidence Gate pass/replan/handoff, or a fixed `UNHANDLED_EXCEPTION` code.
It never records exception text or graph state content. Evidence Gate is labeled as a deterministic
component, not an agent.

`ModelCallTraceManager` emits a start observation only after the immutable start record and audit
commit, and a terminal observation only after the terminal trace/audit commit. Terminal latency is
derived from the trace's authoritative UTC timestamps. Exact typed metering supplies token and cost
signals; unavailable metering remains explicit.

The Tool Gateway emits a start record after validation and start audit, then exactly one signal for
each adapter attempt: `RETRYING`, `SUCCEEDED`, `TIMED_OUT`, `FAILED`, or `CANCELLED`. Pre-dispatch
schema, version, permission, and diagnosis write/unsafe-argument refusal emits `REJECTED`. Result
codes are stable gateway classifications; adapter exception details and arguments/results are never
observable fields.

## Durable coordination instrumentation

PostgreSQL Diagnosis and Approval checkpointers now yield a transparent saver proxy. It delegates
the authoritative call first, then records `CHECKPOINT_SAVE` or `CHECKPOINT_RESTORE` with
`SAVED`/`HIT`/`MISS` or a fixed I/O failure code. Scope comes only from validated checkpoint config;
channel values, pending writes, serialized state, task errors, and interrupt payloads never enter
the observation.

Durable jobs persist tenant, Incident, and workflow-run identity in addition to correlation and
causation. The repository observes enqueue, claim, heartbeat, completion, bounded retry, stale lease
takeover, and exhausted stale routing. Attempts and maximum attempts are bounded to 128. Error text,
payload references, worker identities, and lease timestamps are excluded. Approval lifecycle
transitions emit only after aggregate/audit storage succeeds. The Approval graph separately emits
actual durable pause, authoritative resume, re-pause, or human-handoff outcomes.

## Recovery instrumentation

The rollback Executor emits one request-scoped start and a terminal result only after the relevant
authoritative boundary. A durable terminal execution reports `SUCCEEDED`, confirmed `FAILED`,
`TIMED_OUT`, or uncertainty routed to `NEEDS_HUMAN`; an exact durable replay reports `REPLAYED`
without implying another mutation. A disabled mutation capability is a fixed pre-effect refusal.
Cancellation and unexpected failures use fixed codes, never exception text, adapter results, target
references, versions, or snapshot content.

The persisted Health Verifier uses the successful ActionExecution as causation. It reports an
exact stored decision replay before collection, or reports `PASS`/`FAIL` only after collection,
Evidence/Artifact re-resolution, deterministic evaluation, audit creation, and decision persistence
complete. Collection timeout, cancellation, and fail-closed errors remain distinct fixed outcomes;
none can declare recovery or replace the durable decision.

A persisted failed-verification route emits `REDIAGNOSE` only when a bounded attempt was actually
consumed, otherwise `NEEDS_HUMAN`. The same completed route emits an explicit future-inverse guard
with `KNOWN_FAULTY_VERSION_REDEPLOY_BLOCKED`. This observation documents that `rollback_service`
has no authorized inverse; it does not create a compensation action, controller, policy, approval,
or execution surface. Observer failure occurs after the transaction-owned route and cannot change
the resulting Incident state.

## Composition boundary

All hooks default to no-op so a library test or incomplete process composition cannot create global
SDK state. A following Phase 11 batch owns one observer in each API/worker process, supplies it to
runtime compositions, and shuts it down within a bounded deadline. Process ownership and correlated
end-to-end signal proofs remain open; the recovery, verification, failure-route, and
future-inverse-guard boundaries themselves are now instrumented.

## Verification

Tests cover strict contract rejection, absence of content fields, adapter failure isolation,
credential-free configuration, signal-specific endpoints, disabled mode, bounded shutdown, linked
Span/log export, exact token/cost metrics, tool retry sequences, all Diagnosis node routes,
Evidence Gate pass, and pause/resume behavior. Existing model/tool/graph behavior and audits remain
unchanged when no observer is configured.

The durability suite additionally covers saver save/restore/miss/I/O failure delegation,
PostgreSQL migration and scoped foreign keys, concurrent disjoint job claims, heartbeat, retry,
completion, stale takeover, dead-letter/human handoff, Approval request/decision/expiry, and
new-worker Approval resume. Raising observers prove telemetry failure cannot change any result.

Recovery tests cover success, confirmed failure, timeout, uncertainty, capability refusal, exact
replay, cancellation, deterministic verification PASS/FAIL/timeout/replay, bounded re-diagnosis,
human handoff, and the explicit known-faulty-version inverse block. Raising observers prove that
execution persistence, idempotency, verification decisions, and Incident failure routing remain
authoritative.
