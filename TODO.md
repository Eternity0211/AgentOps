# AgentOps Delivery Plan

Checkboxes are completion claims. Check an item only when its acceptance criteria and listed verification pass. Record measured results in committed reports; do not invent numbers.

> Implementation status: **core complete**. Phase 0 through Phase 13 exit checks pass; optional post-core enhancements remain open below.

## 当前主任务总览（2026-11-05 更新）

目标：补齐真实模型驱动的调查、证据门禁、修复建议、策略与审批等待链路，
再运行预先定义、可复现的完整测评。报告必须保留失败、缺失指标和实验限制。

### 已完成并提交

- [x] DeepSeek 真实调用、严格结构校验、调用用量与耗时记录。
- [x] 初轮固定摘要对比、实际 Compose 故障实验、对抗实验及原始报告（v1/v2）。
- [x] 本地不可变 Evidence/Artifact、引用解析及确定性证据门禁的实验验证。
- [x] C1：真实模型调查计划、诊断与门禁绑定修复提案的类型化调用接口。

### 当前正在做：C2 自主只读调查

- [x] 完成并提交中断前的只读工具 v2 契约、适配器、LangGraph 调查服务和测试。
- [x] 定位真实 PLAN 的额外 steps_note 字段错误；补充明确示例并保留严格校验。
- [ ] 跑通“真实计划 → 现有编译器 → Tool Gateway → 实际遥测 → 不可变证据 → 诊断 → 门禁”。
- [ ] 证明非法计划不调用工具；正常与故障场景均保留完整调用和查询来源。

当前事实：C2 已完成正常基线真实冒烟：5 次 Gateway 查询、2 次模型调用、5 条证据。
这仅证明链路跑通；固定提交版本的故障测评和 C3 持久化仍需完成。

### 后续按顺序执行

- [ ] C3：接入真实 Prompt Registry、PostgreSQL 证据/调用审计、检查点及任务租约。
- [ ] C3 验收：工作进程重启可续跑，重复投递不重复产生效果，取消与失败路由正确。
- [ ] C4：只对门禁 PASS 的候选生成真实修复提案，经策略生成持久化审批请求。
- [ ] C4 验收：提案变更使旧审批失效；拒绝、过期、越权和重复请求均按既有规则处理。
- [ ] C5：冻结独立测试集和评分规则，覆盖六类故障变体、正常、证据不足、反证及注入。
- [ ] C5 验收：标签与 Ground Truth 隔离，评分规则不根据测试答案事后修改。
- [ ] C6：运行规则/单次模型/受控图/图加记忆对比，记录诊断正确率、移交、证据及失败原因。
- [ ] C6：测量工具/模型调用、token、费用口径、排队/调查/续跑耗时、并发和资源分布。
- [ ] C6：运行安全、韧性、重放、超时与恢复验证测试，输出逐项覆盖矩阵和原始数据。
- [ ] C7：自行执行模拟操作员流程与确定性测试审批，报告为模拟数据，不冒充真实审批或真人收益。
- [ ] 发布统一报告：目标、方法、实测结果、局限、未达标项、复现方法及证据链接。

### 不可混淆的边界

- 测试代码覆盖率不等于测评指标覆盖率，也不等于模型能力达标。
- 固定摘要、真实故障采集、自主工具调查、真实审批恢复分别标注，不能互相替代。
- 模拟操作员不代表真人工时、使用体验或 MTTR 收益；真实写操作仍需独立人工审批。
- 不降低证据门禁，不让 LLM 执行命令或宣告恢复成功，不将实验清理计为产品恢复。
- 每批更新实现、测试、文档及本 TODO；检查通过后原子提交并立即推送。

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
- [x] Implement versioned `/api/v1` incident, timeline, control, and audit endpoints with pagination, idempotency, and authorization.
- [x] Add OpenAPI contract snapshots and API error/idempotency conventions.

Exit: migrations apply/rollback in test, API and workers run separately, state/RBAC/job invariants pass unit and Testcontainers integration tests.

## Phase 3 — Evidence Store, artifacts, collectors, and Context Builder

- [x] Implement immutable Artifact storage interface, local development backend, hashes, size/type/version, retention metadata, and safe retrieval authorization.
- [x] Implement Evidence schema with ID, incident ownership, source, normalized query, time range, content hash, Artifact, lineage, version, quality, trust, and expiry.
- [x] Implement evidence normalization, provenance, content verification, quality reasons, and expiration evaluation.
- [x] Implement deterministic collectors/adapters for metrics, logs, traces, deployments, and topology; keep them non-agent components.
- [x] Implement log error-pattern clustering/deduplication with raw Artifact links.
- [x] Implement metric trend summaries with interval/baseline/source metadata.
- [x] Implement trace critical-path/error summaries with trace/span references.
- [x] Implement deployment change summaries correlated to incident windows.
- [x] Implement sensitive-data redaction with transformation lineage and seeded-secret tests.
- [x] Implement untrusted telemetry/prompt-injection detection, delimiting, and quarantine.
- [x] Implement token-budgeted Context Builder with provenance labels, deterministic truncation, and recorded omissions.
- [x] Ensure raw telemetry is not embedded unbounded in LangGraph state or model prompts.
- [x] Add Evidence/Artifact API and authorization tests.

Exit: known telemetry fixtures produce stable normalized evidence and safe budgeted contexts with resolvable source artifacts.

## Phase 4 — Versioned Tool Gateway and read-only investigation

- [x] Define ToolDefinition registry: semantic/schema version, input/output schemas, read/write class, risk, RBAC, timeout, bounded retry, idempotency, audit.
- [x] Implement Tool Gateway validation, authorization, dispatch, timeout, retry classification, result limits, and audit events.
- [x] Implement `query_metrics` adapter and contracts.
- [x] Implement `query_logs` adapter and contracts.
- [x] Implement `query_traces` adapter and contracts.
- [x] Implement `query_deployments` adapter and contracts.
- [x] Implement `get_service_topology` adapter and contracts.
- [x] Register the versioned `search_similar_incidents` contract with historical-reference labeling and a typed disabled/empty result until Phase 7 enables the memory backend.
- [x] Prevent raw URLs, arbitrary paths/commands, unknown tool versions, and write calls from diagnosis.
- [x] Add schema compatibility, timeout, bounded retry, permission, payload-limit, injection, and audit tests.

Exit: five live observability/topology/deployment tools and the disabled-memory `search_similar_incidents` contract return versioned, incident-scoped results through the gateway, including negative/security paths.

## Phase 5 — Deterministic Evidence Gate

- [x] Define versioned gate rules and typed decision/reason schema.
- [x] Validate every cited Evidence ID exists and content hash resolves.
- [x] Validate incident ownership and prevent cross-incident evidence substitution.
- [x] Validate time relevance, freshness, expiry, quality floor, and source availability.
- [x] Evaluate independent-source requirements without double-counting derived evidence.
- [x] Require explicit treatment of material counter-evidence and missing evidence.
- [x] Keep model confidence as non-authoritative metadata.
- [x] Persist gate inputs, rules version, decision, and audit trace.
- [x] Add fabricated, missing, altered, stale, low-quality, correlated-source, and unresolved-counter-evidence tests.

Exit: only candidates satisfying deterministic rules pass; false citations and confidence-only claims always fail.

## Phase 6 — Prompt Registry, Diagnosis Agent, and durable LangGraph investigation

- [x] Define Prompt Registry with Prompt ID, semantic version, immutable content fingerprint, model parameters, schema compatibility, trace links, lifecycle status, and rollback predecessor.
- [x] Implement prompt draft/evaluate/promote/rollback lifecycle with RBAC, immutable versions, audit, and a minimal regression-fixture gate.
  - [x] Implement framework-independent RBAC lifecycle orchestration, regression gating, immutable copy-based rollback, and hash-bound audit contracts.
  - [x] Add the PostgreSQL lifecycle store so Prompt versions, status transitions, regression results, and audit commit atomically.
- [x] Trace the exact prompt/model/settings/token/cost metadata for every model call without leaking sensitive content.
- [x] Define versioned Pydantic graph state and migration/compatibility strategy.
- [x] Implement Diagnosis Agent structured schemas for bounded plan, candidates, support, counter-evidence, missing evidence, and uncertainty.
- [x] Implement tool-catalog constrained planning with maximum steps, parallelism, time, tokens, and cost.
- [x] Implement LangGraph nodes/routes for context load, plan, parallel read-only tools, evidence persistence, hypothesis, gate, replan/handoff.
- [x] Detect repeated/equivalent queries and enforce finite replan/attempt budgets.
- [x] Integrate PostgreSQL LangGraph checkpoints with thread/run correlation.
- [x] Implement pause, resume, cancel, and idempotent node replay semantics.
- [x] Implement worker-crash continuation and checkpoint observability.
- [x] Add deterministic mock-model mode covering valid, malformed, timeout, refusal, fabricated-reference, and injection-resistant outputs.
- [x] Require every Diagnosis node invocation to load an approved Prompt Registry version; prohibit unregistered inline production prompts.
- [x] Add Agent schema tests and all Diagnosis graph path tests.
- [x] Add parallel investigation and model/tool timeout/failure tests.

Exit: a worker can crash at each durable boundary and resume without evidence loss, illegal writes, unbounded loops, or duplicate effects.

## Phase 7 — Incident memory and similar-incident retrieval

- [x] Define confirmed closed-incident memory projection with source/outcome/trust metadata.
- [x] Generate and store pgvector embeddings with embedding model/version and reindex support.
- [x] Implement scoped similar-incident retrieval with authorization, freshness, and leakage controls.
- [x] Implement and enable the `search_similar_incidents` Tool Gateway adapter against the confirmed-memory projection.
- [x] Ensure historical incidents are labeled reference-only and cannot satisfy current Evidence Gate facts.
- [x] Extend the minimal prompt regression gate with memory/no-memory comparisons and enforce it before memory-aware prompt promotion.
- [x] Add memory isolation, embedding-version, retrieval authorization, prompt rollback, and unauthorized-promotion tests.

Exit: retrieval improves context experimentally without label/fact leakage; every model call is reproducible to a registered prompt version.

## Phase 8 — Remediation, policy, approval, and safe execution

- [x] Define Remediation Agent structured proposal, prerequisites, verification conditions, safe failure routing, explicit compensation eligibility, and risk assumptions; prohibit compensation for `rollback_service`.
- [x] Prevent remediation until an immutable passing EvidenceGateDecision is present.
- [x] Define risk levels and versioned deterministic Policy Engine inputs/outputs/reasons.
- [x] Implement policy rules for environment, role, action/target, evidence gate, blast radius, maintenance constraints, and separation of duties.
- [x] Implement approval request/approve/reject lifecycle, expiry, proposal-hash binding, and audit.
- [x] Invalidate approval after any material proposal change and rerun schema/policy checks.
- [x] Implement LangGraph Interrupt and durable resume for approval-required actions.
- [x] Define versioned typed `rollback_service` tool requiring Incident ID, Approval ID, and Idempotency Key.
- [x] Implement service/version resolution from server-owned allowlists; reject free-form commands/targets.
- [x] Implement Action Executor with execution locks, database uniqueness, idempotent result replay, before/after snapshots, timeout, and audit.
  - [x] Define immutable ActionExecution lifecycle, terminal outcomes, snapshot bindings, and canonical fingerprint.
  - [x] Persist ActionExecution records and lifecycle events; enforce target locks, database idempotency uniqueness, concurrent claim serialization, terminal result replay, and atomic lock release.
  - [x] Persist each explicitly observed in-progress, completion, or terminal-result replay as a distinct hash-bound lifecycle and append-only audit event.
  - [x] Implement the disabled-by-default, single-attempt typed write dispatcher with bounded timeout and safe confirmed/timeout/uncertain classifications.
  - [x] Compose preflight, claim, replay audit, dispatch, after snapshot, and terminal persistence into the crash-safe Executor application path.
- [x] Recheck RBAC, policy, state, approval hash/expiry, and idempotency immediately before mutation.
  - [x] Define the deterministic preflight that reloads tenant Incident/Approval/invalidation state, replays Evidence Gate and Policy, checks expiry/hash/RBAC, and resolves the target from server-owned current-version/configuration ports.
  - [x] Compose preflight and the durable idempotency claim in the same Executor path immediately before bounded adapter dispatch.
- [x] Keep the real mutation route disabled behind a server-side capability flag until the Phase 9 verifier/failure-routing exit gate passes.
- [x] Add concurrent approval, rejection/expiry routing, mutation, replay, duplicate delivery, timeout, unauthorized role, and bypass tests.

Exit: exactly one allowlisted mutation occurs for concurrent/retried identical requests, and no invalid or stale approval can execute.

## Phase 9 — Deterministic verification, failure routing, and postmortem

- [x] Define versioned scenario-aware Health Verification criteria and observation-window contract.
- [x] Bind every verification sample to owned, fresh, direct, hash-verified Evidence/Artifact
  content and fail closed before evaluation on any scope, source, query, or value mismatch.
- [x] Verify error rate and P95 latency from real metric evidence.
- [x] Verify health endpoint, active service version, new alerts, and stable observation window.
- [x] Persist verification observations/evidence and deterministic decision reasons.
- [x] Enable the real mutation route only after verifier integration, non-compensable failure routing, and full rollback-service E2E tests pass.
  - [x] Compose execution, persisted verification, and exclusive PASS/FAIL routing behind the disabled mutation capability.
  - [x] Prove PostgreSQL-backed PASS/FAIL orchestration and exact replay without duplicate route audit.
  - [x] Compose live five-signal collection, immutable Artifact/Evidence persistence, re-resolution, deterministic evaluation, decision audit, and exact replay.
  - [x] Add a narrow server-bound deployment adapter that accepts only the preflight-resolved target and idempotency key, with no command/URL/manifest surface.
  - [x] Persist deterministic-identity before/after deployment snapshots as immutable, hash-bound Artifacts and reuse them safely on exact replay.
  - [x] Add a deterministic local-simulator deployment backend with exact-target validation, concurrent idempotency, and live version observation for recovery E2E.
  - [x] Atomically bind durable execution claim/completion to Incident `EXECUTING`, `VERIFYING`, safe re-diagnosis, or human-handoff states with replay-safe audit.
  - [x] Prove the authorized local rollback full chain from durable execution through live persisted verification and closure, including exact replay without a second mutation.
- [x] Route verification success to resolved/closed workflow states.
- [x] Route failed `rollback_service` verification to bounded re-diagnosis or `NEEDS_HUMAN`; never restore the known faulty version.
- [x] Keep generic compensation unreachable in the MVP unless a future write tool provides typed safe-inverse metadata plus independent policy/approval.
- [x] Add verification timeout, flapping/stability-window, non-compensable failure, cancellation-safe-boundary, and re-diagnosis budget tests.
- [x] Implement constrained postmortem draft from confirmed facts and resolvable references only.
- [x] Support versioned human postmortem revisions with authorship/audit.
- [x] Add false-fact/reference and unauthorized-edit tests.

Exit: the system never self-declares recovery; observed success closes the incident, while failed verification safely re-diagnoses or transfers to a human without reverting to a known faulty version.

## Phase 10 — Administration console

- [x] Scaffold the simple Next.js/React console with locked dependencies and lint/type/unit/browser-test commands after `/api/v1` contracts stabilize.
- [x] Implement authenticated shell, RBAC-aware navigation, and accessible error/loading states.
- [x] Implement incident list with filters, severity/state/service, and pagination.
- [x] Implement incident detail and state/workflow timeline.
- [x] Show investigation plan, tool progress, budgets, and bounded-replan history.
- [x] Implement Evidence/Artifact view with provenance, query/time/hash/version/quality/expiry/trust.
- [x] Show ranked root causes, supporting evidence, counter-evidence, missing evidence, and gate result.
- [x] Implement approval center with immutable proposal diff, risk/policy reasons, expiry, separation-of-duties feedback, approve/reject.
- [x] Show execution before/after metrics, service versions, trace links, verification window, failure route, and any separately authorized compensation.
- [x] Show agent-platform traces, tokens/cost, checkpoints, and audit completeness.
- [x] Add component, API contract, authorization, accessibility, and critical-flow browser tests.

Exit: an operator can understand and safely control a full incident without the UI bypassing backend authority.

## Phase 11 — Dual-layer observability and audit hardening

- [x] Standardize trace/correlation/causation IDs across alert, incident, graph, tool, model, approval, execution, and verification.
  - [x] Define the versioned typed identity/link/timeline contract and concurrency-safe, tenant/Incident-scoped immutable PostgreSQL correlation ledger.
  - [x] Wire all eight authoritative runtime boundaries and prove complete reconstruction, propagation, replay, and refusal paths.
- [x] Instrument diagnosed-system service metrics/logs/traces and deployment markers.
- [x] Instrument graph nodes/routes, model latency/errors/tokens/cost, tool calls/retries, evidence gate, checkpoints, jobs/leases, approvals, recovery executions, verification, failure routes, and compensation.
  - [x] Define the versioned content-free control-plane observation contract and bounded OpenTelemetry traces, metrics, logs, model-usage, and tool-retry adapter.
  - [x] Add fail-open observation hooks for every Diagnosis graph node/route, model-call lifecycle, Tool Gateway attempt/retry/refusal/timeout, and deterministic Evidence Gate route.
  - [x] Instrument PostgreSQL checkpoints, jobs/leases, and approval lifecycle/resume boundaries.
  - [x] Instrument recovery executions, deterministic verification, failure routes, and explicit compensation-guard outcomes.
  - [x] Wire one process-owned observer through API/worker compositions and prove correlated end-to-end success, refusal, retry, pause/resume, and failure signals.
- [x] Create dashboards and actionable alerts for both observability layers.
- [x] Add structured logging schema, redaction, payload limits, and no-secret telemetry tests.
- [x] Enforce append-only audit permissions and integrity/sequence checks; document retention/export.
- [x] Add audit completeness assertions for every workflow path.

Exit: one correlation ID reconstructs the incident and agent-control flow without exposing secrets, and required audit events are complete and immutable to application roles.

## Phase 12 — Test matrix, evaluation, load, and resilience

- [x] Complete unit tests for domain, gate, policy, schemas, redaction, idempotency, and state transitions.
- [x] Complete Agent output/schema/property tests including malformed and adversarial outputs.
- [x] Complete LangGraph all-path tests including replans, refusal, human handoff, approval rejection/expiry, success, re-diagnosis, safe-boundary cancellation, and future compensation guards.
- [x] Complete Testcontainers external integration tests for PostgreSQL/pgvector and applicable observability/tool adapters.
- [x] Complete six fault-scenario E2E suites from alert through postmortem, asserting the recovery-eligibility matrix and correct handoffs.
- [x] Test worker crashes at checkpoint/action/verification boundaries and stale-lease recovery.
- [x] Test duplicate execution/delivery and concurrent approval races.
- [x] Test model/tool timeouts, retry exhaustion, malformed payloads, and dependency outages.
- [x] Test prompt injection, secret redaction, evidence forgery, replay, SSRF/target injection, approval and RBAC bypass.
- [x] Build versioned evaluation datasets, rules, harness, raw result schema, and reproducible report generator.
- [x] Enforce baseline fairness in the harness: shared splits/observations/tool schemas/safety chain; equal model and aggregate budgets where applicable; one declared independent variable per comparison.
- [x] Implement separate diagnosis and recovery-safety tracks so diagnosis errors do not confound Executor/Verifier safety results.
- [x] Score correct refusal/handoff as a safe outcome and restrict automated-recovery denominators to Ground Truth cases marked automation-eligible.
- [x] Run rules-only baseline.
  - [x] Predeclare the four-way comparison plan and implement the isolated, create-only rules runner.
- [x] Run single-Agent baseline.
  - [x] Bind the versioned prompt/model settings and implement the isolated single-pass runner.
- [x] Run controlled LangGraph baseline.
  - [x] Bind the graph prompt and implement the real bounded-graph evaluation adapter and runner.
- [x] Run controlled LangGraph plus incident-memory baseline.
  - [x] Bind historical-only memory and implement the otherwise-identical graph runner.
- [x] Report Top-1/Top-3 root cause, unsupported conclusions, fabricated references, correct refusal/handoff, diagnosis time, tool calls, tokens/cost, proposal correctness, dangerous-action blocks, unapproved/duplicate executions, eligible recovery, safe outcomes, future compensation, and worker recovery with explicit denominators.
  - [x] Define the versioned four-baseline metrics policy, create-only report generator, and measured worker-resilience runner.
- [x] Add configured evaluation regression gates for prompt/model/policy promotion based on measured baselines.
- [x] Add bounded concurrency/load tests for API, job leasing, evidence queries, and workers; report observed limits without production-scale claims.
  - [x] Define the fixed four-surface load plan, real PostgreSQL probes, in-process API/worker probes, and create-only result runner with backend-qualified JUnit parsing.

Exit: versioned raw results reproduce every published claim and all required safety/resilience suites pass.

## Phase 13 — Developer experience, security, and demo release

- [x] Provide cross-platform task-runner Compose startup/shutdown with readiness and troubleshooting.
- [x] Provide task-runner fault injection/cleanup and evaluation commands shared by Windows and CI.
- [x] Provide deterministic mock-model mode requiring no external model credential.
- [x] Add dependency/image locking, update policy, vulnerability/secret scans, SBOM/provenance plan, and minimal container users/permissions.
- [x] Validate least-privilege DB roles, network paths, filesystem mounts, and service credentials.
- [x] Complete README quickstart, configuration reference, architecture/workflow diagrams, data model, threat model, ADRs, API docs, runbooks, and contribution guide.
- [x] Publish evaluation report containing methods, environment, raw-result links, limitations, and reproducible commands.
- [x] Create demo script showing six faults, eligibility-aware handoff or approved recovery, verification/failure routing, audit, crash resume, and mock mode.
- [x] Run clean-machine rehearsal and record exact versions/timings/issues.
- [x] Derive portfolio/resume statements only from committed reproducible measurements.

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

## Real-provider evaluation follow-up

- [x] Batch R1: opt-in DeepSeek evaluation adapter and six-case smoke run.
  Acceptance: official endpoint only, environment-only credential, bounded requests, strict existing
  DiagnosisReport validation, opaque case IDs, pre-dispatch hash-only journal, usage and failures
  retained, no runtime/write enablement or Ground Truth in requests.
  Test plan: transport/auth/timeout/truncation/malformed/schema/reference negative tests; Ruff,
  mypy, unit tests; real six-case read-only run with immutable results and explicit limitations.
- [x] R2a: implement bounded real-provider paired replay runner; 22 relevant tests, Ruff and mypy pass.
- [x] R2b: publish 54 real-provider paired replay calls; retain known-case/held-out distinction.
- [ ] R2: real-provider fair single/graph/memory comparisons with repeated held-out scenarios.
  Acceptance: predeclared equal model/budgets and cause taxonomy; opaque IDs; repeated paired
  inputs; same scoring across modes; real graph topology and advisory-only memory; per-call
  token/latency/failure records. No comparison to mock latency or post-hoc semantic relabeling.
  Tests: strict schema, unknown IDs, memory citation refusal, graph routes, budget limits,
  equal-context pair hashes, isolated scoring and report arithmetic; Ruff/mypy/pytest.
- [x] R3a-runner: bounded live Compose collection runner with cleanup-on-failure tests.
- [x] R3b: execute two six-fault Compose diagnosis runs; publish 24 immutable Artifacts and Gate results.
  Outcomes are measurements, not capability acceptance: verified run 4/6 valid reports, 2/6
  exact Top-1, 0/5 candidate Gate passes; all six evaluator cleanups succeed.
- [ ] R3a: collect real local simulator fault observations and evaluate diagnosis up to human wait.
  Acceptance: actual HTTP observations, provenance/hash/time, baseline/fault/cleanup separation,
  real provider calls, no automatic approval or recovery credit; distinguish in-process and Compose.
  Tests: collection failure, cleanup in finally, evidence reference resolution and no label leakage.
- [ ] R3: live fault-injection diagnostics and approved recovery measurements.
- [x] R4a: publish six-case provider, worker-resilience, bounded-load and full Python regression artifacts.
  Result: 2,810 Python tests pass with 100% statement/branch source coverage; 20 new adapter/runner
  tests independently pass with 100% coverage. See evaluation/results/deepseek/v1/README.md.
- [x] R4b: publish real adversarial probes, price bounds, resource snapshots and 2,820-test regression.
  Full requested coverage matrix distinguishes measured results, human tasks and remaining
  nonhuman engineering gaps. See evaluation/results/deepseek/v2/README.md.
- [ ] R4: consolidated safety/evidence/resilience/load measurements and metric coverage matrix.
  Measurement batch acceptance: publish clean-revision six-case provider results, fixed worker
  resilience and bounded-load raw artifacts; distinguish test counts from outcome rates and
  mark every unsupported human/production metric unmeasured. Verification: full Python tests
  with the existing 100% source coverage gate, report arithmetic and revision/hash checks,
  credential/content review, Ruff/mypy/architecture. No fair-comparison or live-recovery credit.
- [ ] R5: human paired trial, active labor, MTTR, recurrence and actual cost measurements.

## Complete real-model evaluation follow-up

- [x] C1: typed real-model planning/report/remediation transport and safe plan compilation.
  Acceptance: fixed provider endpoint; bounded context/calls/tokens/timeouts; strict schemas;
  content-free pre/post call records; invalid plans dispatch nothing; actual compiler checks
  registered read tools, arguments, deduplication and aggregate budgets.
  Tests: success, malformed/refusal/truncation/auth/timeout/unknown references, plan budget,
  write-tool/URL refusal and audit failure; Ruff/mypy and relevant Pytest gates.
  Verification: 63 relevant transport/compiler/regression tests pass; Ruff and strict mypy pass.
- [x] C2a: local read catalog, real model-selected Gateway investigation and exact provenance;
  25 relevant tests, Ruff/mypy and normal-baseline real smoke pass.
- [x] C2b: bounded evidence-driven replan with immutable incremental Evidence.
  Acceptance: at most one replan, 12 aggregate reads and four model calls; missing-evidence
  feedback reaches planner, equivalent queries refuse before dispatch, old Evidence remains
  immutable, terminal checkpoint replay adds no calls. Verification: 23 relevant tests pass,
  including real PostgreSQL terminal replay, two-round Gate success and query reconstruction.
- [ ] C2: autonomous read investigation through the gateway, discriminating telemetry and exact provenance.
- [x] C3a: inject the official PostgreSQL checkpointer and use the existing resume-aware runner.
  Verification: replacement PostgreSQL saver restores a completed autonomous investigation;
  exactly two model calls and one tool call remain unchanged after replay. This does not yet
  establish mid-investigation effect reconstruction, Prompt Registry or JobLease composition.
- [x] C3b: transaction-owning PostgreSQL ports for Evidence, Prompt Registry and model traces.
  Acceptance: cross-session committed reads, tenant isolation, atomic lifecycle/audit and
  duplicate-write/finish rollback without corruption. Test plan: three actual PostgreSQL
  integration cases, full Python regression/100% source coverage, Ruff/mypy/architecture.
  Verification: three real PostgreSQL port tests pass; full regression 2,844 passed,
  100% source statement/branch coverage; Ruff/mypy/architecture pass.
- [x] C3c: autonomous Evidence commits before report generation and Gate resolves SQL records.
  Tests: actual PostgreSQL success and foreign-key refusal; failed writes prevent DIAGNOSE.
  Incident-scoped identifiers and exact Gateway call lineage prevent cross-incident aliasing.
- [ ] C3: registered prompts, PostgreSQL evidence/checkpoint/job/call integration and crash/resume measurements.
- [x] C3d: registered evaluation invoker, durable concurrent call budget and report persistence.
  Acceptance: exact ACTIVE Prompt/content/settings and RBAC before provider;
  durable call start before dispatch; canonical report/trace binding; tenant/workflow budget
  serialized across concurrent and replacement callers. Test plan: transport negative cases,
  PostgreSQL report/trace and concurrent-budget integration, full Python coverage, Ruff/mypy,
  architecture and planning checks. Verification: four focused PostgreSQL cases pass; full
  regression 2,859 passed with 100% source statement/branch coverage; final nine invoker
  tests also pass, including report-write failure. Ruff/mypy/architecture/Compose/supply-chain
  and planning checks pass. C3 remains open for job composition and mid-run reconstruction.
- [ ] C4: gate-bound real remediation, deterministic policy and actual pending approval records.
- [x] C3e: inject PostgreSQL progress recorder into autonomous evaluation.
  Acceptance/tests: existing graph boundaries call the supplied recorder; actual PostgreSQL
  integration reads terminal phase, sequence, budgets and successful tool states from a fresh
  session; Evidence write refusal remains fail-closed. Both integration cases pass; no claim
  of mid-run effect reconstruction or complete worker composition.
- [ ] C5: frozen holdout/counter-evidence/normal/insufficient-evidence datasets and predeclared scoring.
- [ ] C6: complete automatic regression, load/resilience/failure distributions and consolidated results.
- [ ] C7: simulated-operator protocol and evaluation, explicitly separate from real human labor/approval.

- [x] C3f: leased evaluation consumer with injectable workflow handler.
  Committed claim, periodic heartbeat, success/failure completion, fixed failure code and
  cancellation/stale takeover: three PostgreSQL tests pass; Ruff/mypy/architecture pass.
  Real-model handler wiring and effect reconstruction remain open. Commit f530c7b.

- [x] C3g: registered investigation job handler identity binding.
  Acceptance: exact job schema/payload/tenant/incident/workflow/correlation/causation before
  provider construction; registered invoker must match all identities; forward durable ports
  to investigation. Ten positive/tamper tests, Ruff/mypy/architecture pass. Combined real
  PostgreSQL/provider composition and mid-run restoration remain open.

- [x] C3h: bind autonomous Evidence lineage to the actual registered workflow.
  Tenant-scoped Artifact identities avoid cross-tenant aliasing; incremental Evidence rejects
  tenant/workflow changes. Nine Evidence/autonomous tests plus Ruff/mypy/architecture pass.
  Mid-investigation restoration is still open.

- [x] C3i: restore committed Evidence before hypothesis after worker replacement.
  Loader implemented: checkpoint IDs resolve through scoped SQL port, Artifact integrity,
  expiry and workflow bindings checked, context reconstructed without writing manifests.
  Ten relevant unit tests pass; two real PostgreSQL checkpoint tests pass including injected
  pre-hypothesis failure and saver/service replacement: exactly two model and one tool calls.
  Evidence port in this checkpoint test is in-memory; SQL Evidence is tested separately.
  Fully combined registered-prompt/SQL/queue composition remains open.

- [x] C3j: combined registered investigation with SQL Evidence, traces, reports and progress.
  Three PostgreSQL cases pass including active PLAN/DIAGNOSE registrations, exact custom
  workflow lineage, Gate PASS, cross-session report equality and Evidence-write refusal.
  Provider uses MockTransport and Prompt promotion uses test fixtures: integration evidence
  only, not real-model quality or production Prompt promotion. Queue/checkpoint combination
  and remaining crash boundaries are still open. Ruff/mypy pass.

- [x] C3k: SQL queue consumes a registered investigation through the real handler.
  Combined test enqueues/claims a Job, runs the handler with controlled read adapters and
  provider transport, persists report/progress and verifies COMPLETED plus zero second claim.
  Three PostgreSQL cases pass; Ruff/mypy pass. Checkpoint is in-memory in this combined
  case; official PostgreSQL checkpoint replacement remains independently tested.

- [x] C3l: official PostgreSQL checkpoint in the combined SQL leased investigation.
  Combined registered case now uses the official saver against the same PostgreSQL database
  as queue, prompts, traces, Evidence, reports and progress. Three integration cases pass.
  Selector event-loop configuration makes psycopg behavior explicit on Windows. This proves
  successful composition, not every crash boundary; full regression currently running.

- [x] C3m: combined SQL leased investigation recovers before hypothesis.
  Inject failure after Evidence persistence, re-claim with a replacement worker and open a new
  official PostgreSQL saver; reuse SQL Evidence and registered prompts. Four integration cases
  pass; exactly PLAN+DIAGNOSE and two reads, no duplicate collection. Full regression before
  this final extra case: 2,878 passed, 100% source statement/branch coverage. Ruff/mypy pass.

- [x] C3n: restore persisted report before Gate after replacement.
  Implemented scoped report read port, checkpoint call/workflow/tenant/incident checks and
  shared Evidence restoration. Five combined PostgreSQL cases pass including pre-hypothesis
  and pre-Gate failure/reclaim; final 11 autonomous tests pass including negative bindings.
  Full regression: 2,880 passed, 100% source statement/branch coverage. Ruff/mypy and
  architecture pass.

- [x] C4a: registered remediation proposal with stored Gate pre/post admission and Policy review.
  Missing/failed/changed Gate refuses; server-owned Policy inputs and requester binding are
  checked; denied Policy produces no Approval, accepted review stops at PENDING through
  existing lifecycle manager. Twenty-seven related unit tests plus Ruff/mypy pass.
  SQL pending-approval/provider composition and live measurements remain open under C4.

- [x] C4b: deterministic evaluation Policy creates a persisted PENDING approval and review.
  Actual PostgreSQL integration commits through ApprovalLifecycleManager and verifies exact
  proposal/Policy snapshot and PENDING state from a new session. One integration case passes;
  no human decision or execution is dispatched. Gate/proposal inputs are controlled fixtures;
  registered-provider-to-stored-Gate-to-approval composition remains open.

- [x] C4c: registered remediation, stored SQL Gate and pending SQL approval combined.
  Integration runs an ACTIVE remediation prompt with bounded MockTransport provider output,
  durable call trace, exact SQL Gate pre/post admission, deterministic Policy and committed
  PENDING Approval/review snapshot. Fresh-session snapshot equality passes; Ruff/mypy pass.
  This is controlled integration evidence; live-provider diagnosis/remediation runs remain open.

- [x] C5a: predeclare real-provider comparison protocol before new capture.
  Frozen v1 plan: 27 instances/mode, three model modes, 81 provider instances, explicit
  taxonomy, known-family limitation, paired inputs/budgets, memory isolation, failure-inclusive
  denominators and separate recovery/operator tracks. JSON and sample arithmetic verified.
  Dataset capture, protocol validator, scoring and provider runs remain open under C5/C6.

- [x] C5b: strict evaluator-only paired-result and exact-count scorer.
  Requires 27 unique labels across frozen strata and all 81 mode outcomes; rejects missing,
  duplicate, unknown, protocol-hash or paired-input mismatches. Failures score zero without
  changing denominators. Six scoring/negative tests and Ruff/mypy pass. Artifact ingestion,
  confidence intervals, resource distributions and captures remain open.

- [x] C5c: hashed artifact ingestion, nominal Wilson intervals and resource distributions.
  Bounded reads verify original label/output bytes; outputs validate before labels load.
  Reports separate success/failure latency, raw distributions, nearest-rank P95 and unknown
  token/cost values. Eight scorer tests pass; local repeated samples imply no production claim.
  Dataset capture, durable result writer and real provider runs remain open.

- [x] C5d: bounded known-family observation capture and immutable read replay.
  Capture entry schedules 18 fault and three normal instances, snapshots all local read
  sources, redacts output/quarantines injection, records opaque IDs and evaluator-only labels,
  and always cleans injected faults with baseline verification. Three tests cover immutable
  replay, sanitation/quarantine and cleanup on failure; Ruff/mypy pass. Live smoke/capture and
  six explicitly derived control instances remain open; no 27-instance dataset claim yet.

- [x] C5e-smoke: execute real fixed-window capture smoke and retain failures.
  First run fails baseline and remains recorded; second captures 20 tool/service combinations,
  19 successful and one trace-source failure, then checkout 200. This is capture validation,
  not diagnosis quality. Added baseline/protocol-hash manifest bindings; three tests/mypy pass.
  Full 21-instance capture and derived controls remain open.

- [x] C5f: create-only outcome ledger and verified snapshot loader.
  Each outcome commits/fsyncs independently under a hashed instance/mode identity; duplicate
  writes refuse, collection checks protocol and file identity. Snapshot loads verify bounded
  bytes/hash, closed fields, opaque ID, aware window and full read catalog; extra label fields
  refuse. Five related tests plus Ruff/mypy pass. Full capture is running independently.

- [x] C5g: freeze and implement explicit derived control transforms.
  Three normal parents will each yield withheld-source and unsupported-operator-hypothesis
  controls. Counter control preserves telemetry; insufficient control exposes unavailable
  sources. Parent/transform hashes and derived origin stay evaluator-only. Two tests verify
  immutable parents, unchanged counter observations and no label fields in model snapshots.
  Controls still need generation from completed real normal captures.

- [x] C6a: independent single-pass orchestration over shared compiler/Gateway/Evidence/Gate.
  Single-pass uses one PLAN, bounded read batches and one DIAGNOSE without LangGraph/replan;
  both modes share deterministic safety components. Twelve autonomous tests pass plus
  Ruff/mypy. Also bind Gateway workflow/correlation/causation to actual graph identities.
  Full snapshot-mode runner and provider comparison remain open.

- [x] C6b: run a verified snapshot through real-provider transport and durable outcome ledger.
  Shared public taxonomy, independent single-pass/graph paths, bounded calls, fsynced hash-only
  journal and failure-preserving resource aggregation; two transport success/failure tests
  and Ruff/mypy pass. Memory mode metadata explicitly says NO_HISTORY_SUPPLIED and is
  ineligible for quality comparison; confirmed-memory composition and full runs remain open.

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

