# Comparison with Programming Tutor

This comparison prevents portfolio and architecture drift. It records the confirmed capability boundary of the existing `D:\ProgrammingTutor_Update` project and the distinct problem AgentOps must solve. It is not a runtime dependency between repositories.

## Portfolio narratives

- **Programming Tutor:** neuro-symbolic program analysis + educational memory + knowledge augmentation + personalized feedback.
- **AgentOps:** durable execution + dynamic incident investigation + authority isolation + approval + verification + safe failure routing.

Both projects can demonstrate strong agent engineering, but they must earn that claim through different product pressures and technical constraints.

## Confirmed Programming Tutor baseline

Programming Tutor is a Next.js 15, React 19, TypeScript, Prisma/PostgreSQL application. Its established capabilities include teachers/students, classes, assignments, test cases, submissions, grading and analytics; Judge0 multi-language sandbox execution; static/dynamic symbol analysis, control-flow graphs, and rule checks; LLM code review; Code Review, Emotion, and Learning Navigation agents in a DAG; optional-agent fault isolation; evidence fingerprints/sources; dialogue state and memory, context trimming, student profiles, and semantic memory; keyword/vector/hybrid RAG with optional pgvector; Neo4j relations; an MCP-compatible JSON-RPC server; a versioned Prompt Registry; output schemas, evidence validation, quality gates, and degradation; PostgreSQL-backed evaluation jobs and workers; offline benchmarks, blind/human review, and token/cost reporting; plus OpenTelemetry, Prometheus, Tempo, and Grafana.

It also has a custom `DialogueStateGraph` with nodes, edges, state, loop protection, and step limits. It is a predefined request/response dialogue graph, not a claim of native LangGraph checkpointing, long-duration human interrupts, or crash-resumable incident execution.

## Structural differences

| Dimension | Programming Tutor | AgentOps |
| --- | --- | --- |
| Primary user/problem | Teachers and students need explainable code feedback and personalized learning guidance. | Backend/SRE operators need faster evidence correlation and safe incident recovery. |
| Main stack | TypeScript, Next.js/React, Prisma/PostgreSQL. | Python 3.12, FastAPI, Pydantic, SQLAlchemy/Alembic, PostgreSQL/pgvector, small Next.js console. |
| Trigger model | User dialogue and code submission. | Alerts and manually declared incidents. |
| Runtime shape | Primarily request/response interactions and predefined DAG execution. | Long-running event workflow that can pause for approval, resume hours later, survive worker failure, cancel, and compensate. |
| Orchestration | Custom `DialogueStateGraph`; Code Review followed by parallel optional Emotion/Navigation agents. | LangGraph typed persistent state, conditional routing, parallel read-only investigation, bounded replanning, interrupts, checkpoints, recovery, verification and safe failure routes. |
| Decision agents | Code Review, Emotion, Learning Navigation. | Only Diagnosis and Remediation. Postmortem is a constrained node; all safety/collection components are deterministic. |
| Primary evidence | Source code, tests, static/dynamic analysis, assignment/course knowledge, dialogue and learner context. | Metrics, logs, traces, topology, deployment records, alerts, and current-incident Evidence/Artifacts. |
| Memory | Dialogue/session memory, student profiles, educational semantic memory. | Incident working state/checkpoints, Evidence Workspace, and confirmed historical incident memory. No user-profile-style memory. |
| Knowledge retrieval | Course/knowledge RAG, hybrid retrieval, pgvector option, Neo4j knowledge relations. | pgvector similar-incident retrieval only in MVP; historical facts are advisory. General runbook/document RAG and Neo4j are excluded. |
| Tool authority | Mostly read/analyze and Judge0 sandboxed code execution. | Read-only operational queries plus one side-effecting allowlisted version-recovery action with policy, approval, idempotency, verification, and safe failure handoff. |
| Core safety question | Is feedback supported by code/teaching evidence and useful to the learner? | Is the root cause evidence-valid, is the action authorized, did it execute once, and did real service health recover? |
| Human involvement | Educational interaction and review. | Formal approval interrupt for medium/high risk and human handoff for insufficient evidence or failed rollback. |
| Observability | Agent/RAG/evaluation and application telemetry. | Dual-layer telemetry for both the diagnosed microservices and every workflow/model/tool/approval/checkpoint/action/verification event. |
| Evaluation emphasis | Agent/RAG answer quality, educational evidence, personalization, blind/human review, tokens/cost. | Root-cause ranking/refusal/citation integrity, safety blocking, execution uniqueness, recovery/rollback, worker resume, time/tools/tokens/cost. |
| Resume narrative | Neuro-symbolic educational agent system and personalized knowledge-enhanced feedback. | Evidence-driven durable incident agent with controlled operational side effects. |

## What may be reused

Reuse is encouraged for general engineering lessons that do not define the product's unique behavior:

- typed/structured model outputs and validation;
- Prompt Registry concepts: semantic versions, fingerprints, traceability, regression gates, rollback;
- OpenTelemetry tracing and token/cost accounting;
- versioned datasets, reproducible evaluation, blind or human review methods;
- timeout/retry/error classification patterns;
- PostgreSQL persistence, migrations, API authentication, and RBAC fundamentals;
- evidence source labeling and quality-gate discipline.

Reuse should be conceptual or extracted only when ownership and compatibility are clear. AgentOps still implements Python-native domain contracts and must not couple to the Tutor repository.

## What must not be repeated in AgentOps

- a general chat window as the main product interface;
- student/user-profile-style memory or educational dialogue state;
- a general course/document knowledge base or Neo4j graph;
- Code Review, Emotion, or Learning Navigation agents;
- another custom state-graph framework;
- Judge0 or code-submission analysis;
- an MCP server as a core selling point or control path;
- multiple agents generating parallel prose as the main architecture;
- Prometheus/Loki/Tempo query adapters disguised as agents.

AgentOps is not a renamed tutoring RAG system. If a proposed feature resembles one of these, it needs a direct incident-operations requirement and an ADR explaining why the existing deterministic or retrieval boundary is insufficient.

## Similar-looking capabilities with different responsibilities

| Shared-looking concept | Programming Tutor responsibility | AgentOps responsibility |
| --- | --- | --- |
| Evidence | Tie review/teaching feedback to code, tests, and knowledge sources. | Establish current-incident facts with immutable provenance and pass deterministic evidence rules. |
| Memory | Preserve learner/dialogue context and personalization. | Resume one durable incident and retrieve outcome-labeled historical cases without treating them as current facts. |
| Evaluation worker | Run offline agent/RAG benchmarks independently of web requests. | Run versioned incident baselines and validate crash recovery, safe handoff, eligible recovery, and worker-resume behavior. |
| Prompt versions | Reproduce and gate educational-agent behavior. | Reproduce diagnosis/remediation/postmortem nodes and prevent untested prompt promotion. |
| Observability | Understand application, agent, RAG, and evaluation behavior. | Correlate the failing system with the control workflow, authority decisions, and side effects. |
| Graph execution | Coordinate a bounded predefined educational DAG. | Persist a long-lived state machine with dynamic investigation, human interrupts, recovery, and compensation. |

## Guardrail for future design reviews

Before adding an agent, memory system, retriever, graph/database, tool protocol, or UI mode, reviewers must answer:

1. Which incident-response failure does it address?
2. Why is a deterministic component or existing Tool Gateway port insufficient?
3. Does it expand model authority or leak historical/reference data into current facts?
4. Does it duplicate a Programming Tutor capability without introducing the durable-control problem that differentiates AgentOps?
5. How will its contribution, cost, and safety impact be measured?

If these questions do not have concrete answers, the feature stays out of the core scope.
