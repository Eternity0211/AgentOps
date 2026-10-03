# AgentOps Delivery Plan

Checkboxes are completion claims. Check an item only when its acceptance criteria and listed verification pass. Record measured results in committed reports; do not invent numbers.

> Implementation status: **approved**. Phase 0 and Phase 1 exit checks pass; Phase 2 is in progress.

## Execution protocol and dependency order

The default critical path is:

`Phase 0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10 -> 11 -> 12 -> 13`

- Finish each phase's exit gate before depending on it in the next phase. A narrowly scoped task from a later phase may be pulled forward only when it is a prerequisite, remains independently verifiable, and the reason is recorded in the commit/TODO.
- Deliver one atomic vertical batch at a time: contract/schema, implementation, negative paths, telemetry/audit, tests, documentation, TODO update, Conventional Commit, and immediate push.
- Run the smallest relevant checks during development and the phase exit suite before closing a phase. A failed required check keeps the item open.
- Build observability, authorization, audit, timeout, and failure behavior with each capability; Phase 11 hardens and joins them rather than adding them for the first time.
- Keep runtime Ground Truth-blind. Evaluator cleanup, fixtures, or labels may never become a shortcut in application code.
- Do not expose a write endpoint or enable real mutation until Phase 9 verification and failure-routing gates pass.

## Phase 0 — Repository and governance baseline

- [x] Initialize local Git repository on `main`.
- [x] Add `AGENTS.md`, `README.md`, project specification, architecture/workflow diagrams, data model, threat model, evaluation plan, ADR directory, and this complete phased TODO.
- [x] Preserve product decision rationale and the non-duplication boundary with Programming Tutor in maintained comparison/history documents.
- [x] Resolve recovery-versus-compensation semantics, complete the Incident lifecycle, define scenario automation eligibility, and specify fair baseline evaluation.
- [x] Add secret/runtime-safe `.gitignore`.
- [x] Connect the uniquely confirmed existing GitHub `AgentOps` repository as `origin`; never create a duplicate.
- [x] Run planning-document checks and create the initial Conventional Commit.
- [x] Push the initial planning commits to `origin/main` and establish upstream tracking.
- [x] Establish a verified Python 3.12.14 runtime and `.venv` via `uv`, pin `.python-version`, and record bootstrap/verification commands without substituting Python 3.14.
- [x] Add a locally reproducible planning-document CI workflow and branch-protection guidance that distinguishes repository implementation from unverified GitHub administrator settings.
- [x] Obtain explicit user approval of this implementation plan before creating business-code scaffolding.

Verification: clean diff review, Markdown/link checks, secret scan, `git status`, remote verification, commit SHA, and push confirmation.

## Phase 1 — Reproducible simulator and observability foundation

### Phase 1A — Toolchain and repeatable local control

- [x] Scaffold Python 3.12 backend/workspace, locked dependencies, formatting, lint, typing, Pytest, and pre-commit/CI commands.
- [x] Implement the cross-platform `python scripts/dev.py` task runner used by Windows and CI; optional wrappers may delegate to it but cannot be required.
- [x] Add architecture/import-boundary checks so domain modules cannot depend on FastAPI, SQLAlchemy, LangGraph, or model-provider adapters.

### Phase 1B — Simulator topology and baseline signals

- [x] Define Compose networks, health checks, volumes, profiles, resource bounds, `.env.example`, and secret-safe local defaults.
- [x] Implement API Gateway, Order Service, Inventory Service, and Payment Service with deterministic request correlation.
- [x] Add simulator PostgreSQL and Redis dependencies with observable client behavior.
- [x] Instrument services using OpenTelemetry and route metrics/logs/traces through OTel Collector to Prometheus, Loki, and Tempo.
- [x] Record deployment/version change events usable by diagnosis.
- [x] Provide task-runner start/stop and health/readiness validation.

### Phase 1C — Reproducible faults and evaluation-only labels

- [x] Implement task-runner fault injection and cleanup with run/scenario IDs and repeatable reset.
- [x] Implement deployment-induced HTTP 500 scenario.
- [x] Implement database connection-pool exhaustion scenario.
- [x] Implement Redis timeout scenario.
- [x] Implement downstream-service high-latency scenario.
- [x] Implement memory-leak scenario with bounded safe resource settings.
- [x] Implement bad-configuration scenario.
- [x] Define separate Ground Truth manifests for all six scenarios: cause, symptoms, key metrics/logs/traces, deployment change, automation eligibility, expected safe outcome/handoff reason, recovery action, verification, evaluator cleanup, and future-tool requirement.
- [x] Enforce Ground Truth isolation through separate profile/path/network/credentials and canary leakage tests.
- [x] Add simulator smoke tests and deterministic scenario setup/cleanup tests.
- [x] Record a live clean-start, six-scenario reset, telemetry-query, final-health, and clean-shutdown verification run.

Exit: Compose starts cleanly, each fault reproduces and resets, telemetry is queryable, and runtime/model paths cannot access Ground Truth.

## Phase 2 — Domain model, persistence, and API/worker foundation

- [x] Implement pure typed domain identifiers, enums, errors, and UTC time handling.
- [x] Implement the complete Incident state machine with `CLOSED`/`CANCELLED` terminals, durable waits, safe-boundary cancellation, no dead-end non-terminals, optimistic versioning, and exhaustive transition/liveness tests.
- [x] Implement deterministic Alert fingerprinting, deduplication, merging, and triage with race/concurrency tests.
- [x] Implement SQLAlchemy models/repositories and initial Alembic migrations for operational aggregates.
- [x] Enable PostgreSQL pgvector extension and versioned embedding metadata.
- [x] Implement append-only AuditEvent model with correlation/causation IDs and restricted mutation path.
- [x] Implement transactional outbox where cross-process event intent is required.
- [x] Separate FastAPI API and worker process composition.
- [x] Implement PostgreSQL job claim/lease/heartbeat/retry/dead-letter-or-human-handoff behavior using transactional locking.
- [x] Add worker concurrency limits, graceful shutdown, stale-lease recovery, and cancellation checks.
- [x] Add authentication principal abstraction and RBAC roles Viewer, Operator, Approver, Admin.
- [ ] Implement versioned `/api/v1` incident, timeline, control, and audit endpoints with pagination, idempotency, and authorization.
- [ ] Add OpenAPI contract snapshots and API error/idempotency conventions.

Exit: migrations apply/rollback in test, API and workers run separately, state/RBAC/job invariants pass unit and Testcontainers integration tests.

## Phase 3 — Evidence Store, artifacts, collectors, and Context Builder

- [ ] Implement immutable Artifact storage interface, local development backend, hashes, size/type/version, retention metadata, and safe retrieval authorization.
- [ ] Implement Evidence schema with ID, incident ownership, source, normalized query, time range, content hash, Artifact, lineage, version, quality, trust, and expiry.
- [ ] Implement evidence normalization, provenance, content verification, quality reasons, and expiration evaluation.
- [ ] Implement deterministic collectors/adapters for metrics, logs, traces, deployments, and topology; keep them non-agent components.
- [ ] Implement log error-pattern clustering/deduplication with raw Artifact links.
- [ ] Implement metric trend summaries with interval/baseline/source metadata.
- [ ] Implement trace critical-path/error summaries with trace/span references.
- [ ] Implement deployment change summaries correlated to incident windows.
- [ ] Implement sensitive-data redaction with transformation lineage and seeded-secret tests.
- [ ] Implement untrusted telemetry/prompt-injection detection, delimiting, and quarantine.
- [ ] Implement token-budgeted Context Builder with provenance labels, deterministic truncation, and recorded omissions.
- [ ] Ensure raw telemetry is not embedded unbounded in LangGraph state or model prompts.
- [ ] Add Evidence/Artifact API and authorization tests.

Exit: known telemetry fixtures produce stable normalized evidence and safe budgeted contexts with resolvable source artifacts.

## Phase 4 — Versioned Tool Gateway and read-only investigation

- [ ] Define ToolDefinition registry: semantic/schema version, input/output schemas, read/write class, risk, RBAC, timeout, bounded retry, idempotency, audit.
- [ ] Implement Tool Gateway validation, authorization, dispatch, timeout, retry classification, result limits, and audit events.
- [ ] Implement `query_metrics` adapter and contracts.
- [ ] Implement `query_logs` adapter and contracts.
- [ ] Implement `query_traces` adapter and contracts.
- [ ] Implement `query_deployments` adapter and contracts.
- [ ] Implement `get_service_topology` adapter and contracts.
- [ ] Register the versioned `search_similar_incidents` contract with historical-reference labeling and a typed disabled/empty result until Phase 7 enables the memory backend.
- [ ] Prevent raw URLs, arbitrary paths/commands, unknown tool versions, and write calls from diagnosis.
- [ ] Add schema compatibility, timeout, bounded retry, permission, payload-limit, injection, and audit tests.

Exit: five live observability/topology/deployment tools and the disabled-memory `search_similar_incidents` contract return versioned, incident-scoped results through the gateway, including negative/security paths.

## Phase 5 — Deterministic Evidence Gate

- [ ] Define versioned gate rules and typed decision/reason schema.
- [ ] Validate every cited Evidence ID exists and content hash resolves.
- [ ] Validate incident ownership and prevent cross-incident evidence substitution.
- [ ] Validate time relevance, freshness, expiry, quality floor, and source availability.
- [ ] Evaluate independent-source requirements without double-counting derived evidence.
- [ ] Require explicit treatment of material counter-evidence and missing evidence.
- [ ] Keep model confidence as non-authoritative metadata.
- [ ] Persist gate inputs, rules version, decision, and audit trace.
- [ ] Add fabricated, missing, altered, stale, low-quality, correlated-source, and unresolved-counter-evidence tests.

Exit: only candidates satisfying deterministic rules pass; false citations and confidence-only claims always fail.

## Phase 6 — Prompt Registry, Diagnosis Agent, and durable LangGraph investigation

- [ ] Define Prompt Registry with Prompt ID, semantic version, immutable content fingerprint, model parameters, schema compatibility, trace links, lifecycle status, and rollback predecessor.
- [ ] Implement prompt draft/evaluate/promote/rollback lifecycle with RBAC, immutable versions, audit, and a minimal regression-fixture gate.
- [ ] Trace the exact prompt/model/settings/token/cost metadata for every model call without leaking sensitive content.
- [ ] Define versioned Pydantic graph state and migration/compatibility strategy.
- [ ] Implement Diagnosis Agent structured schemas for bounded plan, candidates, support, counter-evidence, missing evidence, and uncertainty.
- [ ] Implement tool-catalog constrained planning with maximum steps, parallelism, time, tokens, and cost.
- [ ] Implement LangGraph nodes/routes for context load, plan, parallel read-only tools, evidence persistence, hypothesis, gate, replan/handoff.
- [ ] Detect repeated/equivalent queries and enforce finite replan/attempt budgets.
- [ ] Integrate PostgreSQL LangGraph checkpoints with thread/run correlation.
- [ ] Implement pause, resume, cancel, and idempotent node replay semantics.
- [ ] Implement worker-crash continuation and checkpoint observability.
- [ ] Add deterministic mock-model mode covering valid, malformed, timeout, refusal, fabricated-reference, and injection-resistant outputs.
- [ ] Require every Diagnosis node invocation to load an approved Prompt Registry version; prohibit unregistered inline production prompts.
- [ ] Add Agent schema tests and all Diagnosis graph path tests.
- [ ] Add parallel investigation and model/tool timeout/failure tests.

Exit: a worker can crash at each durable boundary and resume without evidence loss, illegal writes, unbounded loops, or duplicate effects.

## Phase 7 — Incident memory and similar-incident retrieval

- [ ] Define confirmed closed-incident memory projection with source/outcome/trust metadata.
- [ ] Generate and store pgvector embeddings with embedding model/version and reindex support.
- [ ] Implement scoped similar-incident retrieval with authorization, freshness, and leakage controls.
- [ ] Implement and enable the `search_similar_incidents` Tool Gateway adapter against the confirmed-memory projection.
- [ ] Ensure historical incidents are labeled reference-only and cannot satisfy current Evidence Gate facts.
- [ ] Extend the minimal prompt regression gate with memory/no-memory comparisons and enforce it before memory-aware prompt promotion.
- [ ] Add memory isolation, embedding-version, retrieval authorization, prompt rollback, and unauthorized-promotion tests.

Exit: retrieval improves context experimentally without label/fact leakage; every model call is reproducible to a registered prompt version.

## Phase 8 — Remediation, policy, approval, and safe execution

- [ ] Define Remediation Agent structured proposal, prerequisites, verification conditions, safe failure routing, explicit compensation eligibility, and risk assumptions; prohibit compensation for `rollback_service`.
- [ ] Prevent remediation until an immutable passing EvidenceGateDecision is present.
- [ ] Define risk levels and versioned deterministic Policy Engine inputs/outputs/reasons.
- [ ] Implement policy rules for environment, role, action/target, evidence gate, blast radius, maintenance constraints, and separation of duties.
- [ ] Implement approval request/approve/reject lifecycle, expiry, proposal-hash binding, and audit.
- [ ] Invalidate approval after any material proposal change and rerun schema/policy checks.
- [ ] Implement LangGraph Interrupt and durable resume for approval-required actions.
- [ ] Define versioned typed `rollback_service` tool requiring Incident ID, Approval ID, and Idempotency Key.
- [ ] Implement service/version resolution from server-owned allowlists; reject free-form commands/targets.
- [ ] Implement Action Executor with execution locks, database uniqueness, idempotent result replay, before/after snapshots, timeout, and audit.
- [ ] Recheck RBAC, policy, state, approval hash/expiry, and idempotency immediately before mutation.
- [ ] Keep the real mutation route disabled behind a server-side capability flag until the Phase 9 verifier/failure-routing exit gate passes.
- [ ] Add concurrent approval, rejection/expiry routing, mutation, replay, duplicate delivery, timeout, unauthorized role, and bypass tests.

Exit: exactly one allowlisted mutation occurs for concurrent/retried identical requests, and no invalid or stale approval can execute.

## Phase 9 — Deterministic verification, failure routing, and postmortem

- [ ] Define versioned scenario-aware Health Verification criteria and observation-window contract.
- [ ] Verify error rate and P95 latency from real metric evidence.
- [ ] Verify health endpoint, active service version, new alerts, and stable observation window.
- [ ] Persist verification observations/evidence and deterministic decision reasons.
- [ ] Enable the real mutation route only after verifier integration, non-compensable failure routing, and full rollback-service E2E tests pass.
- [ ] Route verification success to resolved/closed workflow states.
- [ ] Route failed `rollback_service` verification to bounded re-diagnosis or `NEEDS_HUMAN`; never restore the known faulty version.
- [ ] Keep generic compensation unreachable in the MVP unless a future write tool provides typed safe-inverse metadata plus independent policy/approval.
- [ ] Add verification timeout, flapping/stability-window, non-compensable failure, cancellation-safe-boundary, and re-diagnosis budget tests.
- [ ] Implement constrained postmortem draft from confirmed facts and resolvable references only.
- [ ] Support versioned human postmortem revisions with authorship/audit.
- [ ] Add false-fact/reference and unauthorized-edit tests.

Exit: the system never self-declares recovery; observed success closes the incident, while failed verification safely re-diagnoses or transfers to a human without reverting to a known faulty version.

## Phase 10 — Administration console

- [ ] Scaffold the simple Next.js/React console with locked dependencies and lint/type/unit/browser-test commands after `/api/v1` contracts stabilize.
- [ ] Implement authenticated shell, RBAC-aware navigation, and accessible error/loading states.
- [ ] Implement incident list with filters, severity/state/service, and pagination.
- [ ] Implement incident detail and state/workflow timeline.
- [ ] Show investigation plan, tool progress, budgets, and bounded-replan history.
- [ ] Implement Evidence/Artifact view with provenance, query/time/hash/version/quality/expiry/trust.
- [ ] Show ranked root causes, supporting evidence, counter-evidence, missing evidence, and gate result.
- [ ] Implement approval center with immutable proposal diff, risk/policy reasons, expiry, separation-of-duties feedback, approve/reject.
- [ ] Show execution before/after metrics, service versions, trace links, verification window, failure route, and any separately authorized compensation.
- [ ] Show agent-platform traces, tokens/cost, checkpoints, and audit completeness.
- [ ] Add component, API contract, authorization, accessibility, and critical-flow browser tests.

Exit: an operator can understand and safely control a full incident without the UI bypassing backend authority.

## Phase 11 — Dual-layer observability and audit hardening

- [ ] Standardize trace/correlation/causation IDs across alert, incident, graph, tool, model, approval, execution, and verification.
- [ ] Instrument diagnosed-system service metrics/logs/traces and deployment markers.
- [ ] Instrument graph nodes/routes, model latency/errors/tokens/cost, tool calls/retries, evidence gate, checkpoints, jobs/leases, approvals, recovery executions, verification, failure routes, and compensation.
- [ ] Create dashboards and actionable alerts for both observability layers.
- [ ] Add structured logging schema, redaction, payload limits, and no-secret telemetry tests.
- [ ] Enforce append-only audit permissions and integrity/sequence checks; document retention/export.
- [ ] Add audit completeness assertions for every workflow path.

Exit: one correlation ID reconstructs the incident and agent-control flow without exposing secrets, and required audit events are complete and immutable to application roles.

## Phase 12 — Test matrix, evaluation, load, and resilience

- [ ] Complete unit tests for domain, gate, policy, schemas, redaction, idempotency, and state transitions.
- [ ] Complete Agent output/schema/property tests including malformed and adversarial outputs.
- [ ] Complete LangGraph all-path tests including replans, refusal, human handoff, approval rejection/expiry, success, re-diagnosis, safe-boundary cancellation, and future compensation guards.
- [ ] Complete Testcontainers external integration tests for PostgreSQL/pgvector and applicable observability/tool adapters.
- [ ] Complete six fault-scenario E2E suites from alert through postmortem, asserting the recovery-eligibility matrix and correct handoffs.
- [ ] Test worker crashes at checkpoint/action/verification boundaries and stale-lease recovery.
- [ ] Test duplicate execution/delivery and concurrent approval races.
- [ ] Test model/tool timeouts, retry exhaustion, malformed payloads, and dependency outages.
- [ ] Test prompt injection, secret redaction, evidence forgery, replay, SSRF/target injection, approval and RBAC bypass.
- [ ] Build versioned evaluation datasets, rules, harness, raw result schema, and reproducible report generator.
- [ ] Enforce baseline fairness in the harness: shared splits/observations/tool schemas/safety chain; equal model and aggregate budgets where applicable; one declared independent variable per comparison.
- [ ] Implement separate diagnosis and recovery-safety tracks so diagnosis errors do not confound Executor/Verifier safety results.
- [ ] Score correct refusal/handoff as a safe outcome and restrict automated-recovery denominators to Ground Truth cases marked automation-eligible.
- [ ] Run rules-only baseline.
- [ ] Run single-Agent baseline.
- [ ] Run controlled LangGraph baseline.
- [ ] Run controlled LangGraph plus incident-memory baseline.
- [ ] Report Top-1/Top-3 root cause, unsupported conclusions, fabricated references, correct refusal/handoff, diagnosis time, tool calls, tokens/cost, proposal correctness, dangerous-action blocks, unapproved/duplicate executions, eligible recovery, safe outcomes, future compensation, and worker recovery with explicit denominators.
- [ ] Add configured evaluation regression gates for prompt/model/policy promotion based on measured baselines.
- [ ] Add bounded concurrency/load tests for API, job leasing, evidence queries, and workers; report observed limits without production-scale claims.

Exit: versioned raw results reproduce every published claim and all required safety/resilience suites pass.

## Phase 13 — Developer experience, security, and demo release

- [ ] Provide cross-platform task-runner Compose startup/shutdown with readiness and troubleshooting.
- [ ] Provide task-runner fault injection/cleanup and evaluation commands shared by Windows and CI.
- [ ] Provide deterministic mock-model mode requiring no external model credential.
- [ ] Add dependency/image locking, update policy, vulnerability/secret scans, SBOM/provenance plan, and minimal container users/permissions.
- [ ] Validate least-privilege DB roles, network paths, filesystem mounts, and service credentials.
- [ ] Complete README quickstart, configuration reference, architecture/workflow diagrams, data model, threat model, ADRs, API docs, runbooks, and contribution guide.
- [ ] Publish evaluation report containing methods, environment, raw-result links, limitations, and reproducible commands.
- [ ] Create demo script showing six faults, eligibility-aware handoff or approved recovery, verification/failure routing, audit, crash resume, and mock mode.
- [ ] Run clean-machine rehearsal and record exact versions/timings/issues.
- [ ] Derive portfolio/resume statements only from committed reproducible measurements.

Exit: a reviewer can clone, run mock mode, reproduce representative scenarios/evaluation, inspect safety controls, and verify every quantitative statement.

## Core requirement coverage index

This index is an omission check, not a second task list. The referenced phases contain the authoritative checkboxes.

| Planned capability | Primary phase(s) |
| --- | --- |
| Repository governance, atomic Git workflow, Python 3.12, CI guidance, user approval gate | 0 |
| Cross-platform task runner, Compose, Gateway/Order/Inventory/Payment, PostgreSQL/Redis simulator | 1 |
| Prometheus, Loki, Tempo, OpenTelemetry Collector, deployment events, six reproducible faults, isolated Ground Truth | 1, 11, 12 |
| Incident lifecycle, cancellation, Alert deduplication/merge/Triage, API/worker separation, PostgreSQL job leases | 2 |
| SQLAlchemy, Alembic, PostgreSQL/pgvector, append-only audit, outbox, RBAC Viewer/Operator/Approver/Admin | 2 |
| Artifact/Evidence schemas, provenance/hash/version/quality/expiry, deterministic collectors | 3 |
| Context Builder: log clustering, metric trends, trace critical path, deployments, budgets, citations, redaction, injection quarantine | 3 |
| Tool Gateway schemas, read/write/risk/RBAC/timeout/retry/idempotency/audit and six read-tool contracts | 4, 7, 8 |
| Deterministic Evidence Gate: existence, ownership, freshness, independence, counter-evidence, confidence non-authority | 5 |
| Prompt Registry, Diagnosis schemas, bounded/parallel investigation, finite replans, mock model | 6 |
| LangGraph typed state/routes/checkpoints/interrupt foundations, pause/resume/cancel, crash continuation | 6, 8, 9 |
| Working memory, historical incident memory, pgvector retrieval, reference-only similar incidents | 6, 7 |
| Remediation schema, risk, Policy Engine, proposal-bound expiring approval, separation of duties | 8 |
| Strict `rollback_service`, Action Executor locks/idempotency/before-after/timeout/audit | 8, 9 |
| Health Verifier, stable observation window, safe failure routing, compensation guard, human handoff | 9 |
| Evidence-linked Postmortem with human revision | 9 |
| Incident/admin UI: list/detail/timeline/plan/evidence/root cause/counter-evidence/approval/metrics/traces/cost/audit | 10 |
| Dual-layer observability, correlations, dashboards, redaction, audit completeness/integrity | 1, 6, 8, 9, 11 |
| Unit/schema/workflow/integration/Testcontainers/six-scenario E2E/crash/replay/concurrency/timeout/security tests | 2–12 |
| Four fair baselines, versioned datasets, all diagnostic/safety/recovery/cost metrics and regression gates | 12 |
| Concurrency/load measurement without unsupported production-scale claims | 12 |
| One-command startup/fault/cleanup/evaluation, mock mode, supply-chain/least-privilege hardening | 1, 13 |
| README, diagrams, data model, threat model, ADRs, API/runbooks, evaluation report, demo, clean-machine rehearsal | 0, 13 |
| Optional read-only MCP, future write tools/compensation, broker/A2A only after evidence and new ADRs | Enhancements only |
| Explicit exclusions: arbitrary shell, production Kubernetes control, general harness/Q&A, collector agents, multi-agent writing, multi-framework core | Guardrails |

## Enhancements after core acceptance

- [ ] Add optional read-only MCP adapters behind the existing Tool Gateway contracts.
- [ ] Add another tightly scoped write tool only with a new ADR, threat review, policy, verification, failure/compensation semantics, and adversarial suite.
- [ ] Implement a generic Compensation Controller only after a future write tool defines a safe typed inverse, independent policy/approval, idempotency, and compensation verification.
- [ ] Evaluate stronger audit integrity (hash chaining/external anchoring) based on threat/deployment needs.
- [ ] Add alternative artifact stores and enterprise identity providers behind ports.
- [ ] Add chaos/network-fault variants and larger scenario parameterization.
- [ ] Evaluate horizontal worker scaling and a message broker only after PostgreSQL queue measurements demonstrate need.
- [ ] Consider A2A only if independently deployed, separately owned agent services create a real protocol boundary.

## Explicit non-goal guardrails for the core version

These are scope constraints, not open checklist work:

- Do not implement A2A without a real independent-agent service boundary.
- Do not build a general Agent Harness framework.
- Do not create a multi-agent postmortem/writing team.
- Do not represent Metrics, Logs, Traces, Deployment, Evidence, Policy, Executor, Verifier, or Compensation as agents.
- Do not permit arbitrary shell execution or a shell-capable agent.
- Do not control real production Kubernetes.
- Do not add Kafka/NATS before evidence-based need.
- Do not mix competing agent frameworks.
- Do not build general-purpose document Q&A.
- Do not convert the core control path comprehensively to MCP.
