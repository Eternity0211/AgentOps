# AgentOps Incident Commander

AgentOps Incident Commander is an evidence-driven platform for diagnosing microservice incidents and performing controlled recovery. It combines metrics, logs, traces, topology, and deployment history; a constrained Diagnosis Agent builds verifiable root-cause hypotheses; a constrained Remediation Agent proposes recovery only after a deterministic evidence gate passes. Deterministic policy, approval, execution, health verification, and failure routing retain authority over every state change.

> Status: Phase 0 through Phase 11 are complete, and Phase 12 is in progress. Measured [rules](evaluation/results/rules/v1/README.md), [single-Agent](evaluation/results/single-agent/v1/README.md), and [controlled LangGraph](evaluation/results/controlled-graph/v1/README.md) baselines are committed from their exact runner revisions. The fourth memory-aware graph runner is implemented with the same graph/model/budgets/safety chain and only versioned `HISTORICAL_REFERENCE` context; its measured artifacts remain pending execution from the committed revision. The rules baseline records 6/6 correct handoffs; both measured model baselines honestly record 0/6 because the shared mock model's single-source candidates fail the Gate and do not match scenario-specific handoff reasons. Graph orchestration alone produced no claimed diagnosis-quality gain. All three record 5/6 recovery safe outcomes and 1/2 eligible automated recoveries, with explicit denominators and no production-scale claim. The reproducible simulator and live local Compose verification remain documented in the versioned [Phase 1 verification record](docs/PHASE_1_VERIFICATION.md). The control plane includes the framework-free [typed domain model](docs/DOMAIN_MODEL.md), complete Incident lifecycle, deterministic Alert triage, a [PostgreSQL/pgvector persistence foundation](docs/PERSISTENCE.md) with append-only audit, transactional outbox, durable JobLease queue, tenant ownership, command idempotency, and immutable Evidence Gate decisions, separate [API/worker process composition](docs/CONTROL_PLANE_PROCESSES.md) with bounded runtime controls, tenant-scoped [authentication/RBAC contracts](docs/AUTHORIZATION.md), and a fail-closed [versioned business API](docs/API_V1.md) with a committed OpenAPI snapshot and stable problem-detail conventions. Phase 3 includes [immutable Artifact storage](docs/ARTIFACT_STORAGE.md), a tenant-scoped [Evidence model, normalization, quality, verification, redaction, untrusted-telemetry quarantine, and budgeted Context Builder pipeline](docs/EVIDENCE_MODEL.md), five bounded [deterministic collectors](docs/COLLECTORS.md), log error clustering, metric trend summaries, trace critical-path/error summaries, Incident-window deployment correlation with raw Artifact provenance, and tenant-scoped Evidence/Artifact read APIs with verified content bindings. Phase 4 includes the immutable, fail-closed [versioned ToolDefinition registry and deterministic Tool Gateway](docs/TOOL_GATEWAY.md) with conservative schema compatibility, validation, RBAC, exact dispatch, bounded timeout/retry/result controls, hash-only audit events, five bounded live read-tool v1 adapters, the disabled historical-reference-only `search_similar_incidents` v1 contract, and a diagnosis-only read catalog with recursive URL/path/command rejection. Phase 5 includes the versioned [deterministic Evidence Gate](docs/EVIDENCE_GATE.md), resolvable/owned/fresh/independent evidence checks, explicit counter/missing-evidence handling, confidence non-authority, reproducible persistence, audit binding, and adversarial fail-closed coverage. A production authentication adapter and production Artifact backend remain open; no production-scale or reliability claim is implied.

> Phase 12 evaluation update: all four predeclared baselines are now measured and committed. The
> [memory-aware graph result](evaluation/results/controlled-graph-memory/v1/README.md) supersedes
> the earlier pending-execution sentence above: it records the same 0/6 correct handoffs, 5/6
> recovery-safe outcomes, and 1/2 eligible automated recoveries as the controlled graph, while its
> only measured resource change is 192 additional input tokens for historical-reference context.
> The generated [four-baseline comprehensive report](evaluation/results/comprehensive/v1/run-001/README.md)
> now records exact diagnostic, safety, recovery, resource, and worker-resilience denominators;
> duplicate execution is explicitly reported as unmeasured (`0/0`) because the baseline adapter
> did not dispatch the fixture's declared duplicate deliveries.
> A versioned [promotion regression gate](docs/EVALUATION_PLAN.md#promotion-gates) now binds these
> measured results and fails closed for Prompt, model, or policy regressions with stable reasons.
> Phase 12 is now complete. The [bounded local load report](evaluation/results/load/v1/run-001/README.md)
> records exact API, PostgreSQL Job/Evidence, and worker observations without making production
> capacity or reliability claims; Phase 13 release hardening remains in progress.

Phase 6 now includes the versioned [Prompt Registry](docs/PROMPT_REGISTRY.md),
[content-free model-call tracing](docs/MODEL_CALL_TRACING.md), strict
[Diagnosis Agent schemas](docs/DIAGNOSIS_SCHEMAS.md), the
[versioned graph-state contract](docs/GRAPH_STATE.md), and all-or-nothing
[diagnosis-plan compilation](docs/DIAGNOSIS_PLANNING.md) against the server tool catalog and hard
resource budgets. The executable [bounded Diagnosis LangGraph](docs/DIAGNOSIS_GRAPH.md) now routes
context loading, planning, parallel read tools, evidence persistence, hypotheses, deterministic
gating, bounded replanning, repeated-equivalent-query refusal, and human handoff. Production
provider invocation remains disabled. The official PostgreSQL LangGraph checkpointer now provides
strictly serialized, thread/run-correlated history and restore. Every Diagnosis node now supports
durable pre-effect pause/resume, safe-boundary cancellation, and stable operation identities for
exact effect replay. A checkpoint-aware runner now distinguishes new work from continuation,
survives worker replacement at every durable Diagnosis boundary, and exposes bounded content-free
checkpoint observations. The credential-free [deterministic mock model](docs/MOCK_MODEL.md) now
supplies versioned valid, malformed, timeout, refusal, fabricated-reference, and
injection-resistant fixtures; production service composition and provider invocation remain
disabled. Every Diagnosis node now resolves the exact tenant-scoped Prompt version and confirms
that it is the single active `DIAGNOSIS` registration before control handling or any node effect;
unregistered, stale, non-active, wrong-purpose, or fingerprint-mismatched references fail closed.

Phase 7 now includes the immutable confirmed Incident-memory projection and its transactionally
bound, versioned [pgvector index](docs/INCIDENT_MEMORY.md), plus authorized same-tenant similarity
retrieval with explicit freshness and leakage controls and an enabled Tool Gateway v2 adapter.
Only authoritative closed Incidents can enter it; source Evidence, Diagnosis Report, Evidence Gate,
confirmation, outcome, trust, and content fingerprint metadata remain bound. Its trust is always
`HISTORICAL_REFERENCE`, so old incidents remain advisory. The enabled Tool Gateway v2 adapter
accepts only a bounded result count; its query vector, tenant, current Incident, clock, and
freshness window are server owned. The immutable disabled v1 contract remains available for exact
replay. Evidence Gate ruleset `1.1.0` explicitly fails any candidate that cites historical memory
as current supporting or counter Evidence.
Memory-aware Prompt versions declare the exact memory-context schema they consume and cannot leave
`DRAFT` until every regression fixture has safe, complete no-memory/with-memory results. The paired
gate rejects missing modes, failed fixtures, unsupported conclusions, fabricated references,
authorization violations, and any Ground Truth exposure; accepted snapshots are hash-bound and
persisted with the lifecycle audit before promotion is possible.

Phase 8 begins with the strict [Remediation Agent proposal contract](docs/REMEDIATION_PROPOSAL.md).
It permits only a bounded `rollback_service` proposal, keeps deployment versions and execution
credentials outside model authority, requires non-bypassable policy/approval/lock prerequisites,
defines deterministic-verifier inputs and safe failure routing, and makes compensation eligibility
structurally false for this recovery action. A deterministic admission gate now re-resolves the
exact tenant/Incident/candidate Evidence Gate record and accepts only a fingerprint-matching
immutable `PASS`; absent, failed, stale, changed, or cross-tenant decisions cannot reach policy.
The versioned [deterministic Policy Engine contracts](docs/POLICY_ENGINE.md) now bind proposal,
Evidence Gate, actor/role, environment, target, blast-radius, maintenance, and separation inputs to
stable fingerprints, with closed risk/outcome enums, structured reasons, and bounded approval
lifetimes. Its server-owned rules evaluate those controls in fixed order, retain every denial
reason, derive risk deterministically, and can only advance a valid rollback to
`APPROVAL_REQUIRED`; it never authorizes or executes a mutation.
The [proposal-bound Approval lifecycle](docs/APPROVALS.md) now enforces expiring hash bindings,
Approver RBAC, medium/high/critical-risk separation of duties, finite terminal transitions,
optimistic persistence, and transactionally matched lifecycle/audit records. Approval remains a
human control record only and cannot invoke recovery.
Any accepted material proposal revision now creates an immutable approval-invalidation marker,
rejects version-only or identity-changing edits, and reruns strict schema validation, exact
Evidence Gate admission, and complete Policy evaluation. Gate/Policy failure cannot revive the old
approval, while a successful re-evaluation still requires a newly issued human Approval.
The versioned [Approval interrupt graph](docs/APPROVAL_GRAPH.md) now persists a content-free human
wait in PostgreSQL and accepts only a `RECHECK` resume directive. Every resume reloads the
tenant-scoped Approval and invalidation marker; only an unexpired, non-invalidated, exact
fingerprint match can become execution-ready, while all refusal routes remain non-executable.
The strict [`rollback_service` v1 contract](docs/ROLLBACK_SERVICE.md) now requires Incident,
Approval, and idempotency identities while excluding commands and caller-selected targets. Its
tenant/service/environment target and stable version resolve only from a server-owned allowlist;
the mutation adapter remains deliberately unregistered until the Executor and verifier safety
gates are complete.
The immutable [ActionExecution lifecycle](docs/ACTION_EXECUTION.md) now binds authority,
server-resolved target, before/after Artifact snapshots, outcome, timing, and canonical fingerprint;
success requires snapshot proof of the configured stable version. PostgreSQL now persists execution
and lifecycle records, serializes concurrent idempotency/target claims, replays stored terminal
results, records each explicitly observed replay as a separate hash-bound audit event, and
atomically releases target locks on completion. The framework-independent execution preflight
reloads Incident/Approval/invalidation authority, replays Evidence Gate and Policy, enforces
execution RBAC and approval expiry/hash bindings, and resolves observed current and stable versions
only through server-owned ports. The crash-safe Executor application path now composes that
preflight with an idempotent before snapshot, a transaction-owning PostgreSQL claim, atomic replay
audit, one bounded typed dispatch, and terminal persistence. A durable claim always commits before
the adapter call; every concurrent or retried duplicate returns the stored execution without a
second mutation. The server kill switch remains disabled by default, and only the deterministic
verifier may declare recovery. The Phase 8 safety matrix
now includes a PostgreSQL concurrent-approval race plus rejection/expiry, mutation
classification, replay, duplicate delivery, timeout, authorization, and bypass coverage; its
server-side mutation flag remains off unless trusted worker configuration explicitly enables it.

Phase 9 now has the first versioned [deterministic health-verification contract](docs/HEALTH_VERIFICATION.md).
It binds a successful ActionExecution to one of the two rollback-eligible scenarios, exact
server-owned target scope, five distinct Evidence references, bounded per-sample observations, and
a continuous stability window. Every sample must satisfy error-rate, P95 latency, health endpoint,
stable-version, and zero-new-alert rules; stale, incomplete, gapped, flapping, or substituted input
fails closed with stable reason codes. The application path now resolves all five series through
owned, fresh, direct Evidence and hash-verified immutable Artifacts, checks controlled source/query
purpose, and compares every timestamp and value before it permits deterministic evaluation. A
bounded all-or-nothing collector now obtains aligned error-rate, P95, health-probe, active-version,
and new-alert samples through fixed read-only ports and emits the five canonical Evidence/Artifact
series. PostgreSQL now persists each accepted observation and decision with same-scope foreign
keys to the successful ActionExecution and all five Evidence records, exact replay semantics,
ordered reasons, hash-bound audit, and corruption detection. An authorized deterministic success
router now locks the persisted PASS and Incident, then atomically records the legal
`VERIFYING -> RESOLVED -> CLOSED` transitions and a hash-bound audit; duplicate and concurrent
delivery replay the same closure without extra transitions. Persisted FAIL decisions now follow a
separate non-compensable route: one proposal-bound budgeted attempt returns to `INVESTIGATING`,
while exhaustion or an explicit zero budget enters `NEEDS_HUMAN`; neither route can redeploy the
faulty version or enter compensation. The architecture gate also rejects executable compensation
modules, controllers, functions, or tool identifiers from the MVP application, workflow, and
infrastructure layers while retaining the explicitly future-only domain states. A single deterministic
recovery coordinator now composes the authorized executor, persisted verifier, and exclusive
success/failure routers: unsuccessful execution never reaches
verification, every authority and decision fingerprint remains exact, `PASS` alone may close,
and `FAIL` alone may re-diagnose or hand off. PostgreSQL integration now proves both composed
routes and exact replay without duplicate route audit. The live persisted verifier now composes
five-signal collection, immutable Artifact/Evidence persistence, full re-resolution,
deterministic evaluation, hash-bound audit, and exact decision replay. A narrow server-bound
rollback adapter now admits only the preflight-resolved typed target and Idempotency Key and reads
back the deployed semantic version; it exposes no command, URL, manifest, namespace, credential,
or caller-selected target. Before and
after deployment observations now persist as deterministic-identity, immutable, hash-bound Artifact
snapshots; exact retries reuse validated content while version, scope, and operation substitutions
fail closed. A deterministic local-simulator-only deployment backend now provides exact-target,
concurrent-idempotent state transition and live `/versionz` observation for the recovery E2E
suite; it is not a production provider and does not enable the default-off mutation switch.
The lifecycle-aware PostgreSQL execution store now commits a new action claim with the Incident's
entry into `EXECUTING`, then commits the terminal execution with its deterministic next state:
success enters `VERIFYING`, confirmed pre-effect failure re-diagnoses, and timeout or uncertainty
requires a human. Exact replays cannot duplicate or rewind those audited transitions.
The final authorized local E2E now explicitly enables the test-only capability and composes the
server-bound adapter, simulator deployment state, immutable before/after snapshots, lifecycle-aware
execution, live five-signal persistence, deterministic `PASS`, and success routing. It proves one
deployment mutation, one ActionExecution, five Evidence records, one verification decision, and the
four legal Incident transitions through `CLOSED`; exact replay reuses those results without a
second mutation, collection, verification, or closure. After that gate, the worker-owned recovery
composition now wires an injected typed deployment backend through the same Executor, verifier,
and transaction-owning PASS/FAIL routers. `AGENTOPS_RECOVERY_MUTATION_ENABLED` remains false by
default and a disabled attempt stops before preflight or any effect; the repository intentionally
ships no production Kubernetes controller or API write endpoint.
Phase 9 also includes [constrained postmortem drafting](docs/POSTMORTEM.md) for closed Incidents.
It accepts only bounded, pre-confirmed facts backed by resolvable current-Incident Evidence and
hash-verified Artifacts. The registered postmortem model may arrange fact IDs into typed sections
but cannot author factual prose; the server rejects fabricated, omitted, duplicated, cross-scoped,
historical, stale, injected, or tampered references and renders the exact confirmed statements and
Evidence IDs deterministically. Prompt identity, request/response hashes, status, token/cost
metadata, actor, and workflow correlation are traced. Versioned human revisions and their
authorship/audit are persisted as immutable consecutive history with server-derived Operator
authorship, inherited source Fact/Evidence references, optimistic concurrency, append-only database
protection, and atomic hash-only audit. Anonymous, read-only, cross-tenant, stale, forged-parent,
substituted-reference, and corrupt-history paths fail closed.

Phase 11 begins with the versioned [trace, correlation, and causation contract](docs/CORRELATION.md).
It defines strict nonzero W3C Trace IDs, one tenant/Incident-owned Correlation stream, resolvable
event-level Causation, and the closed Alert-to-verification component vocabulary. A concurrency-safe
PostgreSQL ledger now persists content-free links with exact replay, scope isolation, canonical
fingerprint verification, and tamper detection. A worker-owned deterministic workflow now admits
only typed authoritative Alert, Incident, graph, tool, model, Approval, successful execution, and
bound verification records; it enforces causation and safety-chain order, supports repeated bounded
investigation events, and resumes from short transaction-owned PostgreSQL operations.

The diagnosed simulator layer is now hardened across all four services. Incoming W3C context is
extracted before server spans are created, internal calls propagate the same trace and validated
correlation ID, and bounded server/client/dependency metrics and OTLP logs expose success, HTTP
failure, malformed response, transport failure, PostgreSQL, and Redis behavior without payloads,
URLs, exception text, credentials, or scenario labels. Startup and live rollback transitions emit
the same versioned deployment marker with environment and UTC observation time; telemetry observer
failure cannot change deployment state or recovery outcomes. See
[simulator observability](docs/OBSERVABILITY.md) for the exact signal vocabulary.

The first control-plane observability hardening batch adds a versioned
[content-free operation contract](docs/CONTROL_PLANE_OBSERVABILITY.md) and an isolated OpenTelemetry
adapter for correlated Spans/logs, operation latency, model errors/tokens/integer cost, and Tool
Gateway attempts/retries. Diagnosis graph nodes/routes, the deterministic Evidence Gate boundary,
model-call persistence, and tool validation/dispatch now have fail-open injection hooks. Process
ownership plus the remaining deterministic recovery, verification, failure-route, and explicit
future-inverse guard instrumentation remain tracked sub-batches; no complete Phase 11 claim is made.

The second control-plane batch wraps the authoritative PostgreSQL LangGraph saver so checkpoint
save, restore, miss, resume, and I/O failure are observable without exposing checkpoint payloads.
Durable jobs now carry required tenant, Incident, workflow-run, correlation, and causation scope;
enqueue, claim, heartbeat, retry, completion, stale-worker takeover, and terminal handoff/dead-letter
routes emit fail-open observations. Approval request/decision/expiry and the durable approval
interrupt/resume routes use the same contract.

The third control-plane batch instruments rollback execution classifications and exact replay,
persisted deterministic verification PASS/FAIL/timeout/replay, bounded failed-verification routing,
and the explicit block against automatically redeploying the known faulty version. Signals are
content-free and occur after their authoritative persistence boundary; raising observers cannot
change recovery, idempotency, verification, or Incident routing. Process-owned observer lifecycle
and correlated end-to-end signal proofs were retained for the next sub-batch.

The fourth control-plane batch gives API and worker exactly one role-scoped observer lifecycle.
API Approval handling, every worker work item, and the complete rollback runtime receive the same
process object; the verifier must be built by an observer-bound factory. Bounded fail-open shutdown
cannot alter process results. Tests preserve one Correlation ID across exported success, refusal,
retry, pause/resume, and failure signals, and the PostgreSQL recovery E2E proves refusal, success,
verification, and replay all reach the one worker observer.

The fifth observability batch provisions two repository-owned Grafana dashboards: one for diagnosed
service RED/dependency/log signals and one for graph/model/tool/durability/approval/recovery health.
Prometheus evaluates nine versioned, severity/layer-labeled rules with sustained-volume guards and
direct operational runbook links. Grafana's Prometheus, Loki, and Tempo data sources are fixed,
internal, and read-only; anonymous local access is Viewer-only, the administrator uses a file
secret, and background plugin downloads are disabled. Dashboards and alerts remain operational
signals only and cannot replace Incident-owned Evidence, policy, approval, execution, or health
verification.

The sixth observability batch adds the shared [structured logging safety
contract](docs/STRUCTURED_LOGGING.md). All simulator and control-plane Python/OTLP logs now use one
versioned flat event schema, secret redaction, control-character removal, 256-byte UTF-8 string
limits, a 4,096-byte record cap, deterministic identity-preserving truncation, and content-free
payload refusal. Simulator Span/metric external values and control-plane Span/log/model-tool
dimensions share the same sanitizer. Seeded-secret tests prove the secret is absent from all three
signal types while correlation survives; telemetry remains fail-open and non-authoritative.

The seventh Phase 11 batch hardens the [audit ledger](docs/AUDIT_LEDGER.md) with transactional
per-tenant sequencing, canonical immutable-event fingerprints, application-role mutation denial,
head-checked fail-closed reads, and reproducible bounded export manifests. The accompanying
retention runbook states the current indefinite online behavior, deployment-owned archive and legal
hold responsibilities, and the explicit absence of external anchoring rather than overstating the
database-owner threat boundary.

The final Phase 11 batch adds the versioned `audit-completeness/v1` contract and a closed catalog
of 33 authoritative workflow boundary outcomes. It checks exact tenant, target, correlation and
optional causation bindings, event/schema versions, cardinality, mutually exclusive events, and
cross-boundary ordering over fingerprint-verified audit records. Classified Tool Gateway retries
now append `tool.call_retried` events containing only bounded attempt/error metadata hashes. The
catalog covers investigation controls, tool/model outcomes, Diagnosis gate routes, approval
pause/resume/reject/expiry/invalidation, execution and replay, verification closure/re-diagnosis/
handoff/cancellation, and postmortem history. Deterministic domain records select the path; the
completeness checker cannot infer an outcome, authorize an action, or declare recovery.

Phase 12 begins with the versioned [core unit safety matrix](docs/PHASE_12_TEST_MATRIX.md). The
allowlisted `test --suite unit` task now collects only `tests/unit`, disables incidental Pytest
cache writes, resets inherited coverage selection, and enforces 100% statement and branch coverage
over the framework-independent domain plus the Evidence Gate, Policy Engine, schema/state,
idempotency, and Tool Gateway application boundaries. The repository-wide quality task remains a
separate superset and continues to cover infrastructure and integration-owned paths.
The same matrix now includes a separately allowlisted `agent-output` property suite. Locked
Hypothesis generators exercise both decision agents' strict outputs without a provider: valid
plans, reports, and remediation proposals round-trip with stable fingerprints, while unsupported
versions, type coercion, invalid IDs, authority-bearing fields, prompt-like text, and fabricated
Evidence references fail at the schema or deterministic Evidence Gate boundary.
Its closed `workflow` gate binds every required Phase 12 path to the actual Diagnosis and Approval
LangGraphs plus their deterministic recovery continuation. It exercises success, replan, refusal,
handoff, approval rejection/expiry, verification re-diagnosis/handoff, every pre-effect cancel
boundary, pause-to-cancel resume, and both runtime and source-level compensation guards.
The allowlisted `integration` gate now checks Docker before running 100 Testcontainers cases
against the same PostgreSQL 18/pgvector image as the control plane. It proves migrations, real
vector behavior, transaction and concurrency controls, PostgreSQL LangGraph checkpoint recovery,
the persisted Tool Gateway retry/audit route, and the complete deterministic recovery persistence
chain. Prometheus/Loki/Tempo topology remains a Compose contract and their telemetry adapters
remain isolated adapter tests; the repository does not claim those external stores are covered by
Testcontainers.
The `e2e` gate now executes all six fault scenarios from typed Alert triage through evidence-bound
Diagnosis and the terminal safety route. HTTP 500 and deployment-linked memory leak alone reach
approval-required rollback, deterministic closure, and constrained postmortem drafting; pool
exhaustion, Redis timeout, downstream latency, and configuration drift each produce their exact
human-handoff reason with zero write execution. An included PostgreSQL full-chain case proves the
eligible route uses the real Executor, five-signal Verifier, audit, and exact replay boundaries.
The fixed `resilience` gate now replaces workers at every Diagnosis checkpoint and Approval
interrupt, injects exits around action claim/dispatch/terminal persistence and verification
Evidence/decision/routing commits, and races eight workers for one expired Job lease. It proves
durable replay without a second write, one recovery owner, old-owner refusal, and bounded
terminal routing when the final lease expires.
The fixed `concurrency` gate now races API commands, Alert/Correlation ingestion, audit appends,
Outbox and Job claims, Approval terminal decisions, Action claims/dispatch, and verification
closure. Exact duplicates converge on one authoritative result; conflicting key reuse fails
closed; approve/reject/expire races commit one terminal Approval and one matching audit; and eight
identical rollback deliveries invoke the adapter once.
The fixed `failure` gate binds model and tool timeout/refusal/malformed-output handling, classified
retry and exhaustion, action and verification timeouts, constrained postmortem failures, simulator
PostgreSQL/Redis outages, readiness failures, and the real persisted Tool Gateway retry/audit path
into one closed matrix. It proves these failures remain bounded, typed, non-authoritative, and free
of partial Evidence or write success.
The fixed `security` gate binds prompt injection, secret redaction, Evidence forgery/tampering,
exact/conflicting replay, SSRF/path/command/target injection, Approval bypass, and RBAC/cross-tenant
bypass to their real unit, property, and PostgreSQL nodes. It proves untrusted content remains data,
authority stays server-owned, and adversarial inputs cannot create Evidence, approval, or execution
authority.
The Phase 12 [evaluation foundation](docs/EVALUATION_PLAN.md) now provides a versioned, label-free
six-scenario diagnosis dataset, independent fixed recovery-safety fixtures, immutable validation
rules, and closed track-specific JSON Schemas. The Ground-Truth-blind Harness exposes separate
diagnosis and recovery-safety entry points: diagnosis cannot emit recovery fields, while recovery
cannot receive ranks, candidate Evidence, scenario identity, or diagnosis results. Each raw run
binds its dataset or fixture plus rules by version and SHA-256 and records
code/scenario/baseline versions, the Ground Truth manifest-set and model-settings hashes, prompt,
policy, tool Schemas, environment, concurrency, seed, and run-window metadata without passing any
of it into system input. Track-specific reports deliberately expose only raw counts and
distributions; scoring, measured baselines, and comparative claims remain separate unfinished
items. The Harness also enforces a closed, versioned baseline-fairness policy and a hash-bound
concrete comparison plan. All four required profiles share the exact dataset/split/observations,
read-tool Schemas, and deterministic recovery safety chain; model profiles share model/settings and
complete aggregate budgets, while the rules profile has only the explicit zero-model-budget
exemption. Each required pair declares one independent variable, aggregate reported usage is
bounded, and raw results bind the policy and plan hashes. No baseline has been run and no
comparative result is claimed by this contract-only batch. Diagnosis failures therefore cannot
silently alter Executor or Verifier safety measurements.
The isolated scorer now loads Ground Truth only after both raw tracks exist, verifies their exact
manifest-set binding, and emits a create-only hash-bound safe-outcome artifact. Exact typed
refusal/handoff reasons receive safe credit. Automated-recovery denominators contain only the two
`automation_eligible=true` scenarios; the other four are explicitly excluded, and successful-
looking unapproved or duplicate executions receive no recovery credit. These are scoring-contract
tests, not claimed baseline measurements.

## Why this project exists

- Shorten time to diagnose microservice failures.
- Improve the completeness and traceability of root-cause evidence.
- Reduce recovery risk with typed plans, policy enforcement, human approval, idempotency, health verification, and explicit safe failure routing.
- Make the agent system itself observable and auditable.

## Safety boundary

```text
Alert -> deterministic triage -> Diagnosis Agent -> read-only tools -> Evidence Store
      -> deterministic Evidence Gate -> Remediation Agent -> schema validation
      -> Policy Engine -> human approval -> deterministic Executor
      -> deterministic Health Verifier -> close, re-diagnose, or human handoff
```

An LLM can propose; it cannot execute arbitrary commands, mutate infrastructure directly, approve its own proposal, declare success, or invent evidence. Ground Truth is available only to the evaluation harness.

## Planned stack

Python 3.12, FastAPI, LangGraph, Pydantic, SQLAlchemy, Alembic, PostgreSQL/pgvector, OpenTelemetry, Prometheus, Loki, Tempo, Grafana, Docker Compose, Pytest, Testcontainers, and a small Next.js/React console.

## Administration console

The console scaffold lives in `console/` and is pinned to Node.js 22.17.0, npm 10.9.2, and exact
package versions in `package-lock.json`. It remains a presentation and intent-capture layer: the
API continues to own authentication, RBAC, policy, approval, execution, and verification.
The authenticated shell bootstraps exclusively from the server-resolved `/api/v1/session` response,
renders navigation from its derived permissions, and fails closed on missing or invalid identity.
Its incident workspace lists only tenant-authorized records and keeps severity, lifecycle-state,
service, and opaque-page filters in the URL. The API, rather than the browser, validates every
filter and remains the source of pagination and authorization truth. Each authorized incident
links to a responsive detail view that renders the API-owned lifecycle fields and a cursor-paged
history of state transitions and cancellation requests, including actor, reason, version,
correlation, and causation metadata. The same view renders a fingerprint-verified, server-persisted
Diagnosis projection with plan attempts, per-tool status, exact resource-budget consumption,
bounded replan history, failure/exhaustion, and human-handoff state. Detail, timeline, and
investigation failures remain read-only and never cause the client to infer a state or dispatch a
control action. The same page preserves the verified Diagnosis report's server ranking, supporting
and counter-evidence, missing evidence, uncertainty, and deterministically matched Evidence Gate
result while labeling model confidence as non-authoritative. The detail view also validates and
pages Incident-owned Evidence provenance,
including query/time/hash/version/quality/expiry/trust/lineage fields. Artifact content is fetched
only on explicit user intent, checked against its immutable Evidence binding and safe response
headers, and rendered only as bounded escaped text or JSON; unsupported, oversized, expired, or
unverifiable content remains closed without any workflow mutation.
The tenant-scoped Approval center renders only hash-verified immutable proposal and Policy
snapshots, including risk, every structured Policy reason, expiry, and server-derived
separation-of-duties feedback. Material revisions retain the original review and show a
server-generated field diff to the persisted replacement proposal while disabling the stale
Approval. Approve and reject intents carry an optimistic version and Idempotency Key to the
authoritative Approval lifecycle; the console never predicts a terminal state or treats a late,
self-approved, invalidated, stale, or corrupt record as authority.
The Incident detail view also consumes a tenant-scoped, integrity-checked recovery projection. It
compares immutable execution before/after deployment snapshots, shows the deterministic verifier's
first and last values across all five required health signals, links each signal to its Evidence
record, and renders the persisted closure, bounded re-diagnosis, human-handoff, or cancellation
route. It never infers recovery from the executor result, and it explicitly shows that
`rollback_service` has no separately authorized compensation path and never redeploys the known
faulty version after failed verification.
The same detail view now renders a bounded, content-free agent-platform projection: exact
Prompt/model/node trace metadata, latency, token categories, per-currency integer cost, latest
durable Diagnosis checkpoint projections, and a backend-computed model-call audit completeness
decision. Truncation is explicit, raw prompts/responses are absent, and the UI never upgrades this
scoped `model.call_started`/`model.call_finished` coverage into a full workflow claim. Full path
assertions use the separate closed catalog and authoritative record bindings described in the
[audit ledger contract](docs/AUDIT_LEDGER.md).

From `console/`, use `npm ci` for a locked install, `npm run verify` for formatting, linting,
strict type checks, unit coverage, and a production build, and `npm run test:browser` for the
desktop/mobile Chromium smoke and WCAG contract. See
[console development](console/README.md) for setup, the `/api/v1` base URL contract, and the
[Phase 10 verification record](docs/PHASE_10_VERIFICATION.md) for the tested authorization,
accessibility, and critical-flow boundary.

## Python 3.12 bootstrap

The project is pinned to Python 3.12.14 in `.python-version`; Python 3.14 is not an accepted substitute. `uv` is the bootstrap tool. A normal developer/CI setup is:

```text
uv python install 3.12.14
uv venv --python 3.12.14 .venv
```

Activate `.venv` using the shell's normal command, then verify the invariant with:

```text
python -c "import sys; assert sys.version_info[:2] == (3, 12), sys.version; print(sys.version)"
```

On this Windows host, the registered Store Python 3.12 launcher was broken. The verified fallback installs the runtime inside the ignored `.python/` directory and creates `.venv` from its explicit interpreter path; the resulting interpreter is Python 3.12.14. The future bootstrap command will automate that fallback without relying on the Store launcher.

```text
uv python install 3.12.14 --install-dir .python --no-bin --no-registry
uv venv --python .python/cpython-3.12.14-windows-x86_64-none/python.exe .venv
.\.venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12); print(sys.version)"
```

## Local runtime commands

After creating the local secret files described below and starting Docker Engine, the fixed task runner controls the simulator and observability profiles:

```text
python scripts/dev.py doctor
python scripts/dev.py up
python scripts/dev.py status
python scripts/dev.py down
```

`doctor` performs read-only, bounded checks for Python 3.12, the Compose contract, all four local
runtime secret files, Docker Engine/Compose, and the rendered profile configuration; it never
changes containers or volumes. `up` validates the same static and daemon boundaries, builds/starts
with Compose `--wait`, then checks Gateway readiness/version, Prometheus/Loki/Tempo/Grafana
readiness, and the Collector's Prometheus target. A post-start failure automatically stops partial
containers without deleting named volumes. `status` repeats the observable health contract. `down`
removes containers and orphans but deliberately does not remove persistent volumes. Grafana is
available at `http://127.0.0.1:3000` by default and loads the two AgentOps dashboards without manual
import.

The fault controller syntax and safe state/cleanup framework are available for all six scenarios.
The focused in-process smoke suite verifies the four-service baseline, each fault symptom, and
restoration to a fresh baseline without requiring Docker. The six-scenario product E2E and the
credential-free evaluation reproducibility gate use the same fixed Python task runner on Windows
and in CI:

```text
python scripts/dev.py fault inject --scenario http-500
python scripts/dev.py fault inject --scenario db-pool-exhaustion
python scripts/dev.py fault inject --scenario redis-timeout
python scripts/dev.py fault inject --scenario downstream-latency
python scripts/dev.py fault inject --scenario memory-leak
python scripts/dev.py fault inject --scenario bad-configuration
python scripts/dev.py fault clean
python scripts/dev.py test --suite smoke
python scripts/dev.py test --suite e2e
python scripts/dev.py eval --model mock
```

See [Deterministic fault control](docs/FAULT_INJECTION.md) for run IDs, concurrency, recovery state, cleanup, and the scenario enablement boundary.

The repository-owned Python task runner below is the single cross-platform entry point for Windows, POSIX shells, and CI; `make` may be offered later only as an optional convenience wrapper.

## Python quality commands

The Python workspace uses the committed `uv.lock`. After bootstrapping Python 3.12.14:

```text
uv sync --frozen --all-groups
uv lock --check
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen python scripts/check_architecture.py
uv run --frozen python scripts/check_compose.py
uv run --frozen python scripts/check_supply_chain.py
uv run --frozen mypy src scripts tests
uv run --frozen pytest
uv run --frozen pre-commit run --all-files
uv build --offline --no-sources
```

The same commands run in the `Python Quality / quality` GitHub Actions job. The current package is intentionally minimal; simulator and application code arrive in later atomic batches.

If the host restricts the normal user cache directory, set `PRE_COMMIT_HOME` to the ignored repository-local `.pre-commit-cache` directory before running pre-commit. The project task runner normalizes this automatically.

## Cross-platform task runner

The repository now provides one fixed-command development entry point used by Windows and CI:

```text
python scripts/dev.py sync
python scripts/dev.py quality
python scripts/dev.py format
python scripts/dev.py format --write
python scripts/dev.py lint
python scripts/dev.py architecture
python scripts/dev.py compose
python scripts/dev.py supply-chain
python scripts/dev.py typecheck
python scripts/dev.py test --suite unit
python scripts/dev.py test --suite agent-output
python scripts/dev.py test --suite workflow
python scripts/dev.py test --suite integration
python scripts/dev.py test --suite e2e
python scripts/dev.py test --suite resilience
python scripts/dev.py test --suite concurrency
python scripts/dev.py test --suite failure
python scripts/dev.py test --suite security
python scripts/dev.py test --suite smoke
python scripts/dev.py docs
python scripts/dev.py build
python scripts/dev.py pre-commit
python scripts/dev.py eval --model mock
python scripts/dev.py mock
python scripts/dev.py doctor
python scripts/dev.py up
python scripts/dev.py status
python scripts/dev.py down
```

The runner never forwards arbitrary shell text: every task maps to an immutable argument list, runs
without a shell, has a timeout, stops on first failure, and emits start/pass/fail timing lines. The
`architecture` task rejects domain imports of FastAPI, SQLAlchemy, LangGraph/LangChain,
model-provider SDKs, or higher internal layers. The unit suite owns the versioned Phase 12
core-unit coverage scope and requires 100% statement and branch coverage; `agent-output` runs the
deterministic generated schema/adversarial contract, `workflow` runs the closed all-path gate,
`integration` checks Docker and runs only the Testcontainers adapter boundary, `e2e` runs the
six-scenario eligibility/handoff matrix plus a real recovery chain, `resilience` runs the fixed
worker-crash and stale-lease matrix, `concurrency` runs duplicate-delivery and authority-race cases,
`failure` runs the closed timeout/retry/malformed-payload/dependency-outage matrix, and `security`
runs the closed adversarial authority-boundary matrix. The smoke suite is deliberately in-process.
`eval --model mock` runs the fixed four-baseline, comprehensive-metrics, regression, bounded-load
result, and Ground Truth isolation test set; it accepts no provider credential, output path, or
arbitrary test selection. The quality task still runs the complete repository suite.

`python scripts/dev.py mock` is the user-runnable deterministic model mode. It invokes the real
`diagnosis-mock/1.0.0` adapter repeatedly for planning and reporting against fixed adversarial
context, compares the injection-resistant scenario, requires byte-stable response fingerprints and
zero model cost, and prints only bounded usage/fingerprint metadata. It imports no provider SDK,
reads no external model credential, makes no network call, and grants no execution authority.
Production-provider invocation remains disabled.

## Compose foundation

Copy `.env.example` to the ignored `.env` file, then create the four ignored runtime secret files referenced by `CONTROL_DB_PASSWORD_FILE`, `SIMULATOR_DB_PASSWORD_FILE`, `SIMULATOR_REDIS_PASSWORD_FILE`, and `GRAFANA_ADMIN_PASSWORD_FILE`. Each file must contain a distinct, non-empty local-only credential. The isolated evaluator additionally uses `GROUND_TRUTH_ACCESS_FILE` only with `compose.evaluation.yaml`. The repository does not commit working credentials or unsafe fallback passwords; absent secret files prevent profile startup.

The current topology is intentionally profile-scoped: `control-plane` provides its isolated PostgreSQL store, `simulator` provides the diagnosed PostgreSQL and Redis dependencies, and `observability` provides Prometheus, Loki, Tempo, Grafana, and the OpenTelemetry Collector. Persistent stores use named volumes; runtime root filesystems are read-only; CPU, memory, and process counts are bounded; and published observability ports bind to `127.0.0.1` by default. `python scripts/dev.py compose` renders every profile with synthetic secret sentinels and verifies those invariants without starting containers or exposing the sentinels.

Registry images and both Python bases are locked by readable release tag plus immutable manifest
digest. The locally built simulator and evaluator use fixed non-root numeric identities, drop all
capabilities, run with read-only roots, and disable privilege escalation. The commit-pinned CI
supply-chain job scans vulnerabilities, secrets, and misconfiguration and retains a commit-bound
CycloneDX repository SBOM. See [Supply-chain security](docs/SUPPLY_CHAIN.md) for the reviewed update
policy, scanner limitations, upstream-image permission exceptions, and the explicitly future
release provenance plan.

The simulator includes API Gateway, Order, Inventory, and Payment services plus isolated PostgreSQL and Redis dependencies. Order writes are idempotent, Inventory reservations are atomic and idempotent, and dependency-aware readiness fails closed. Services emit bounded traces, HTTP metrics, and trace-linked logs through the OpenTelemetry Collector toward Prometheus, Loki, and Tempo. Six deterministic scenarios cover deployment-induced HTTP 500s, database pool exhaustion, Redis timeout, downstream latency, memory leak, and bad configuration. Their labels live behind a separate evaluator image, Compose file/profile, internal network, read-only path, and credential; runtime/model-capable paths are protected by leakage-canary tests.

## Documentation

- [Project specification](docs/PROJECT_SPEC.md)
- [Architecture and workflows](docs/ARCHITECTURE.md)
- [Decision history and rationale](docs/DECISION_HISTORY.md)
- [Comparison with Programming Tutor](docs/COMPARISON_WITH_PROGRAMMING_TUTOR.md)
- [Data model](docs/DATA_MODEL.md)
- [Operational persistence foundation](docs/PERSISTENCE.md)
- [Trace, correlation, and causation](docs/CORRELATION.md)
- [Control-plane API and worker processes](docs/CONTROL_PLANE_PROCESSES.md)
- [Authentication principal and RBAC](docs/AUTHORIZATION.md)
- [Versioned control-plane API](docs/API_V1.md)
- [Immutable Artifact storage](docs/ARTIFACT_STORAGE.md)
- [Immutable Evidence model](docs/EVIDENCE_MODEL.md)
- [Deterministic Evidence collectors](docs/COLLECTORS.md)
- [Versioned Tool Gateway contracts](docs/TOOL_GATEWAY.md)
- [Deterministic Evidence Gate](docs/EVIDENCE_GATE.md)
- [Versioned Prompt Registry](docs/PROMPT_REGISTRY.md)
- [Content-free model-call tracing](docs/MODEL_CALL_TRACING.md)
- [Deterministic Diagnosis mock model](docs/MOCK_MODEL.md)
- [Versioned Diagnosis graph state](docs/GRAPH_STATE.md)
- [Diagnosis Agent structured schemas](docs/DIAGNOSIS_SCHEMAS.md)
- [Deterministic diagnosis-plan compilation](docs/DIAGNOSIS_PLANNING.md)
- [Bounded Diagnosis LangGraph](docs/DIAGNOSIS_GRAPH.md)
- [Confirmed historical Incident memory](docs/INCIDENT_MEMORY.md)
- [Remediation Agent proposal contract](docs/REMEDIATION_PROPOSAL.md)
- [Deterministic Policy Engine contracts](docs/POLICY_ENGINE.md)
- [Proposal-bound Approval lifecycle](docs/APPROVALS.md)
- [Typed rollback_service contract](docs/ROLLBACK_SERVICE.md)
- [Recovery ActionExecution lifecycle](docs/ACTION_EXECUTION.md)
- [Deterministic health verification](docs/HEALTH_VERIFICATION.md)
- [Constrained postmortem drafting and versioned human revisions](docs/POSTMORTEM.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Supply-chain security](docs/SUPPLY_CHAIN.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Repository CI and branch governance](docs/REPOSITORY_GOVERNANCE.md)
- [Local Compose foundation](docs/COMPOSE.md)
- [Simulator service contracts](docs/SIMULATOR_SERVICES.md)
- [Simulator observability baseline](docs/OBSERVABILITY.md)
- [Control-plane observability contract](docs/CONTROL_PLANE_OBSERVABILITY.md)
- [Structured logging safety contract](docs/STRUCTURED_LOGGING.md)
- [Audit ledger integrity, export, and retention](docs/AUDIT_LEDGER.md)
- [Phase 12 unit and Agent-output test matrix](docs/PHASE_12_TEST_MATRIX.md)
- [Observability alert runbooks](docs/OBSERVABILITY_RUNBOOKS.md)
- [Deterministic fault control](docs/FAULT_INJECTION.md)
- [Evaluation-only Ground Truth](docs/GROUND_TRUTH.md)
- [Phase 1 live verification](docs/PHASE_1_VERIFICATION.md)
- [Phase 10 console verification](docs/PHASE_10_VERIFICATION.md)
- [Architecture decisions](docs/ADR/README.md)
- [Delivery plan](TODO.md)

## Repository discipline

Work is delivered in small, verifiable Conventional Commits. A TODO is checked only after its acceptance checks pass. Every completed batch must record its checks, commit SHA, and push status. Secrets, personal data, unredacted model data, and generated runtime artifacts are excluded from Git.

## Name note

The repository remains named `AgentOps`, while the documentation and portfolio display name is **AgentOps Incident Commander**. This standalone project is not affiliated with other products or repositories named AgentOps.
