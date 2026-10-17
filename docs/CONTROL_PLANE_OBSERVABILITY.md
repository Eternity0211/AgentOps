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

All local and OTLP logs additionally use the shared [structured logging safety
contract](STRUCTURED_LOGGING.md). The control-plane operation Span and model/tool metric dimensions
are derived from the same sanitized flat record used by its log. Unknown or nested values cannot
be represented; seeded credential patterns are redacted before any of the three signal types can
export them. Record truncation preserves the correlation identities required for reconstruction.

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

All hooks still default to no-op for isolated library use. The API process now creates exactly one
`agentops-api` observer, stores it on application state, injects it into the API router's Approval
lifecycle, and closes it from the FastAPI lifespan. The worker process creates exactly one
`agentops-worker` observer per `serve` lifecycle and passes that same instance explicitly to every
leased-work handler. Handlers therefore have one source for Diagnosis graph contexts, model traces,
Tool Gateway calls, Evidence Gate evaluation, PostgreSQL checkpoint wrappers, Job repositories,
Approval contexts, and other workflow compositions rather than creating SDK providers themselves.

The rollback runtime additionally requires a verifier factory that receives the process observer.
It supplies the same object to the Executor, persisted verifier, and transaction-owning failed-
verification router and exposes the binding for composition verification. This prevents a verifier
from being prebuilt around an unrelated observer. API and worker shutdown use the adapter's bounded
flush deadline; unexpected shutdown failures are logged with process role only and cannot fail
request handling, worker completion, or authoritative persistence.

## Verification

Tests cover strict contract rejection, absence of content fields, cross-signal seeded-secret
redaction, Unicode/whole-record payload bounds, adapter failure isolation,
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

Process-composition tests prove a single role-scoped factory call, identity-preserving injection
into API Approval and worker handlers, one bounded shutdown, and fail-open shutdown behavior. The
PostgreSQL recovery E2E proves the same observer receives capability refusal, execution success,
verification PASS, and exact replay. A full adapter export test sends success, refusal, retry,
pause, resume, and failure records under one Correlation ID and proves every emitted Span/log keeps
that identity without a payload field.

The Phase 12 external-integration gate includes the PostgreSQL-owned correlation, audit, job,
checkpoint, Approval, execution, verification, and observer-failure paths. Prometheus, Loki,
Tempo, and OTLP exporters are not persistence adapters in the Python control plane; their external
process wiring remains verified by the Compose contract and their export semantics by isolated
adapter tests, so no Testcontainers claim is made for those stores.

## Dashboard and alert contract

The immutable **AgentOps / Agent platform** Grafana dashboard uses the same process-owned export
stream to show operation outcome/rate/P95, model calls/errors/tokens/integer-nanounit cost, Tool
Gateway attempts/retries, active platform alerts, and content-free Loki logs. Its Prometheus queries
use only the contract's bounded dimensions; tenant, Incident, correlation, causation, operation, and
workflow identities remain in logs/Spans rather than metric labels.

Versioned Prometheus rules cover sustained platform failure ratio, stale Job recovery, unsuccessful
recovery execution, Tool retry ratio, model-call errors, and shared Collector loss. Expected policy
refusals/rejections are not counted as platform failures. Volume and hold-window guards avoid sparse
single-event alerting except for safety-critical recovery failure/stale recovery. Each rule includes
layer/severity metadata and a direct [operational runbook](OBSERVABILITY_RUNBOOKS.md). Responders must
inspect durable correlation/audit/action/verification records; neither a dashboard nor an alert may
replay work, authorize mutation, or declare recovery.
