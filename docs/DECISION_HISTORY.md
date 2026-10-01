# Decision History

This document preserves the reasoning behind the current AgentOps specification. It is a decision map, not a transcript. Normative behavior remains in the project specification, architecture, ADRs, and repository instructions; when those documents change, this history should be updated with the decision and rationale rather than silently rewritten.

## Product and portfolio intent

The project is designed for AI-agent and AI-oriented Python backend roles. Agent capabilities must arise from the incident-response problem rather than from a checklist of fashionable techniques. AgentOps therefore focuses on evidence-driven microservice diagnosis and controlled recovery: operational signals are fragmented, investigation is iterative, recovery can have external side effects, and a long-running workflow may wait for approval or survive worker failure.

This choice deliberately complements the existing Programming Tutor project. Programming Tutor demonstrates neuro-symbolic code analysis, educational memory, knowledge augmentation, and personalized feedback. AgentOps must instead demonstrate durable execution, dynamic investigation, least privilege, approval, idempotency, health verification, and rollback. Shared engineering foundations are acceptable; repeating the same chat/RAG/multi-agent product under another domain name is not.

## Final decisions and why they were made

| Decision | Final position | Formation reason |
| --- | --- | --- |
| Product scope | Diagnose microservice incidents from metrics, logs, traces, topology, deployments, and incident history; coordinate controlled recovery. | SRE incidents provide a natural need for evidence correlation, long-running state, human approval, and side-effect safety. |
| Agent boundary | Exactly two core decision agents: Diagnosis and Remediation. Postmortem is a constrained node; collectors and safety controls are deterministic components. | Separating investigation from recovery prevents the hypothesis author from proving and executing its own conclusion, reduces privileges, and keeps authority testable. |
| Orchestration | LangGraph owns typed workflow state, explicit routes, parallel read-only work, bounded loops, checkpoints, interrupts, recovery, and compensation paths. | An incident can run for hours, pause for approval, resume after worker failure, and branch on observed verification; a request/response chain or black-box ReAct loop is insufficient. |
| LangChain relationship | `langchain-core`-level model, message, tool-schema, or retriever components may be used where useful; LangGraph is the workflow authority and domain code owns evidence, policy, execution, and verification. | This is not a forced framework choice. It separates reusable model plumbing from durable orchestration and business authority. |
| Runtime durability | FastAPI API and workers are separate; PostgreSQL stores domain state, LangGraph checkpoints, and a claim/lease job queue. | This is the simplest reliable MVP design with transactional coordination and crash recovery. Scale claims must come from load data. |
| Control-plane messaging | No Kafka, NATS, or control-plane Redis in the MVP. The simulator's Redis is part of the diagnosed system only. | There is no measured need for another broker/cache. Add one only for a demonstrated caching, broadcast, distributed-rate-limit, or throughput requirement. |
| Evidence model | Raw observations live as immutable Artifacts; normalized Evidence records carry ownership, provenance, time range, hash, schema/version, quality, trust, and expiry. | Model claims need resolvable facts and large telemetry must stay outside prompts and graph state. |
| Evidence Gate | A deterministic gate checks existence, incident ownership, freshness, independent sources, and unresolved counter-evidence; confidence is non-authoritative. | Confidence does not prove a claim. Deterministic reference validation makes unsupported and fabricated conclusions measurable and rejectable. |
| Context strategy | Use incident working memory, an Evidence Workspace, and historical incident memory. Context Builder clusters logs, summarizes trends/critical paths/deployments, budgets tokens, labels sources, redacts secrets, and quarantines untrusted content. | Operational telemetry is too large and too hostile to send directly to a model. Diagnosis, remediation, and postmortem require different minimum contexts. |
| Historical retrieval | pgvector retrieves similar closed incidents with service/fault/time filters. Historical records are reference-only and cannot establish current facts. Runbook RAG is deferred. | This gains useful experience without rebuilding general document Q&A or contaminating current evidence. |
| Core tool integration | Prometheus, Loki, Tempo, deployments, topology, and `rollback_service` use direct versioned typed adapters behind the Tool Gateway. | Core paths need predictable latency, schemas, timeout, RBAC, idempotency, and audit behavior. |
| Mutation scope | The first and only core write tool is allowlisted `rollback_service`, requiring Incident ID, Approval ID, and Idempotency Key. No arbitrary shell or raw target. | A narrow action makes the entire approval/execution/verification/rollback chain deeply testable before expanding authority. |
| Safety chain | Proposal -> schema validation -> Policy Engine -> human approval for medium/high risk -> deterministic idempotent Executor -> deterministic Health Verifier -> rollback or human handoff. | LLMs can propose but cannot authorize, execute, or declare success. Every authority transition is explicit and auditable. |
| Evaluation | Compare rules, a single agent, controlled LangGraph, and controlled LangGraph plus incident memory on versioned scenarios. | The portfolio must demonstrate measured contribution and tradeoffs rather than attribute gains to architecture by assertion. |
| Claims | Do not claim hallucination elimination, production scale, or high concurrency. Use “production-oriented” only when controls exist; publish quantitative claims only from reproducible evaluations. | Safety controls reduce and expose failure modes but do not eliminate them; scale and quality require evidence. |

## Why the two agents remain separate

### Diagnosis Agent

- Has read-only authority and a server-supplied tool catalog.
- Produces a finite investigation plan subject to step, parallelism, time, token, and cost budgets.
- Returns ranked root-cause candidates, supporting evidence, counter-evidence, missing evidence, uncertainty, and suggested checks.
- May replan only within a deterministic limit; insufficient evidence results in a correct refusal or human handoff.
- Cannot request arbitrary writes or execute recovery.

### Remediation Agent

- Receives only a root cause that passed the deterministic Evidence Gate plus the minimum supporting context.
- Selects from an allowed action catalog and returns a typed proposal, prerequisites, risk assumptions, validation criteria, and rollback conditions.
- Cannot call the write adapter, approve itself, or declare recovery.

This separation provides context isolation and least privilege, and prevents a single agent from controlling hypothesis, justification, mutation, and success judgment. Postmortem generation occurs only after closure from confirmed facts and resolvable references; Writer/Critic/Reviewer agents add no necessary authority or reliability.

## Final workflow shape

```text
alert or manual incident
  -> deterministic deduplication, merge, and triage
  -> topology and bounded baseline context
  -> Diagnosis Agent bounded plan
  -> parallel read-only tools
  -> evidence normalization, versioning, redaction, and persistence
  -> root-cause candidates with support, counter-evidence, and gaps
  -> deterministic Evidence Gate
  -> bounded replan or human handoff when insufficient
  -> Remediation Agent typed proposal
  -> deterministic Policy Engine
  -> LangGraph Interrupt for required approval
  -> deterministic idempotent Action Executor
  -> deterministic observation-window Health Verifier
  -> close, bounded re-diagnosis, or idempotent rollback
  -> human handoff when rollback fails
  -> evidence-linked postmortem from confirmed facts
```

The graph is explicit rather than a general ReAct agent because the safety path, refusal path, pause/resume semantics, and compensation behavior must remain inspectable and testable.

## Memory and knowledge boundaries

The project uses three distinct information layers:

1. **Working memory:** versioned LangGraph state plus PostgreSQL checkpoints for one incident. It holds identifiers and bounded summaries, not raw telemetry.
2. **Evidence Workspace:** immutable raw metric/log/trace/deployment Artifacts and normalized Evidence. Model outputs cite these records.
3. **Incident memory:** confirmed closed-incident symptoms, causes, decisive evidence, attempted actions, and outcomes, indexed for pgvector similarity search.

Old incidents and future runbooks are advisory. Approval rules, permissions, thresholds, forbidden actions, and state transitions are procedural rules implemented in code/Policy Engine, never merely embedded in a vector database. Diagnosis, remediation, and postmortem receive separately constructed minimum contexts.

## Security and uncertainty posture

The system constrains model failure rather than claiming to remove hallucinations:

- factual conclusions require resolvable Evidence IDs;
- deterministic tools produce measurements and deployment times;
- untrusted logs/traces remain data and prompt-like content is quarantined;
- secrets and sensitive values are redacted before model access;
- tool schemas, allowlists, RBAC, risk, budgets, timeouts, and bounded retries limit capability;
- medium/high-risk actions require proposal-bound, expiring human approval;
- locks and idempotency keys prevent replay and duplicate mutation;
- the executor runs a typed allowlisted action in an isolated execution boundary, not arbitrary shell;
- real health observations determine success; failures trigger bounded re-diagnosis, rollback, or human handoff;
- append-only audit events cover decisions, calls, checkpoints, approval, execution, verification, and rollback.

## Evaluation and honest scale language

Required comparison groups are a rules baseline, single agent, controlled LangGraph agent, and controlled LangGraph plus historical memory. Required outcomes include root-cause Top-1/Top-3, unsupported-conclusion rate, fabricated-reference rate, correct-refusal rate, diagnosis time, calls, tokens/cost, plan correctness, dangerous-action blocking, unapproved and duplicate executions, verification pass rate, rollback success, and worker recovery.

Until fault, recovery, security, and load suites produce reproducible data, documentation must not say “production-grade,” “high concurrency,” “solves hallucinations,” or equivalent. “Production-oriented design” is acceptable only when paired with the implemented controls and explicit limitations.

## Rejected or deferred approaches

| Approach | Status | Reason / reconsideration trigger |
| --- | --- | --- |
| General ReAct agent controlling the workflow | Rejected | Hides state and safety routing; cannot replace explicit checkpoints, gates, approvals, verification, and compensation. |
| Agents for metrics/logs/traces/deployments, evidence, policy, execution, verification, or rollback | Rejected | These are deterministic capabilities and authorities, not open-ended decisions. |
| Postmortem multi-agent writing team | Rejected | Adds coordination and cost without improving the core incident-control boundary. |
| General Agent Harness or Deep Agents | Rejected for core | Build only domain runtime capabilities. Reconsider reusable extraction after multiple real consumers exist. |
| MCP on core control/write paths | Rejected | Direct typed adapters give tighter authority and reliability. Optional read-only MCP adapters may later cover runbooks, history, Git, or service catalogs. |
| A2A between the two core agents | Rejected for core | They share one codebase, state, and authority domain. Reconsider only for independently deployed, separately owned remote agents that cannot share internal state. |
| General document/runbook RAG | Deferred | Similar-incident memory is the MVP need. Add runbooks only with source governance and current-fact separation. |
| Kafka/NATS or control-plane Redis | Deferred | PostgreSQL queue/leases are sufficient until measurement or a concrete broadcast/cache/rate-limit requirement proves otherwise. |
| Production Kubernetes control | Rejected for core | The simulator and typed rollback demonstrate safety without claiming production infrastructure authority. |
| Additional write tools | Deferred | Each needs its own ADR, threat review, policy, verifier, rollback, and adversarial tests. |

## MVP commitment

The diagnosed system contains Gateway, Order, Inventory, Payment, PostgreSQL, and Redis, observed through Prometheus, Loki, Tempo, and OpenTelemetry Collector. The six reproducible faults are release-induced HTTP 500, connection-pool exhaustion, Redis timeout, downstream latency, memory leak, and bad configuration. Read tools are `query_metrics`, `query_logs`, `query_traces`, `query_deployments`, `get_service_topology`, and `search_similar_incidents`; the sole write tool is `rollback_service`.

The console remains an operational review surface: incident list/detail and timeline, investigation plan, evidence, root causes/counter-evidence, approval, before/after signals, traces, cost, and audit status. Both the diagnosed services and the agent workflow are observable.

## Coverage deliberately left to other projects or future work

Finishing AgentOps and Programming Tutor does not imply mastery of every agent technique. Real-time voice, multimodal interaction, autonomous browsing/Computer Use, model fine-tuning or reinforcement learning, large-scale GPU inference, and cross-organization agent marketplaces remain outside this project's focus. Their absence is a scope decision, not an MVP defect.
