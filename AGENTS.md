# AgentOps Repository Instructions

These instructions are binding for every coding agent working in this repository.

## Product invariant

AgentOps is an evidence-driven microservice incident diagnosis and controlled recovery platform. It must reduce diagnosis time without allowing an LLM to become an execution authority. Every decision, tool call, approval, action, verification, rollback, token, and cost event must be observable, explainable, and auditable.

The only core decision agents are:

1. **Diagnosis Agent**: creates a bounded investigation plan, invokes only read-only tools, correlates evidence, and reports root-cause candidates, supporting evidence, counter-evidence, missing evidence, and uncertainty.
2. **Remediation Agent**: runs only after the deterministic evidence gate passes and proposes a typed remediation, validation conditions, and rollback plan.

Postmortem generation is a constrained LLM node after incident closure, not an agent team. Collectors, Evidence Validator/Gate, Policy Engine, Action Executor, Health Verifier, and Rollback Controller are deterministic components and must never be relabeled as agents.

The non-bypassable recovery chain is:

`LLM proposal -> schema validation -> policy engine -> human approval -> deterministic executor -> deterministic health verifier -> rollback when required`

LLMs may propose but may not run arbitrary shell commands, mutate infrastructure directly, bypass gateways/policy/approval, declare recovery success, or cite evidence that the Evidence Store cannot resolve.

## Required workflow

Before every batch:

1. Read `README.md`, `docs/PROJECT_SPEC.md`, `docs/ARCHITECTURE.md`, relevant ADRs, and `TODO.md`.
2. Check branch, working tree, and remotes. Preserve unrelated user changes.
3. Choose one logically complete, verifiable TODO batch. Do not begin implementation without explicit acceptance criteria and a test plan.

For every completed batch:

1. Update implementation, tests, documentation, and `TODO.md` together.
2. Run relevant formatting, lint, type checks, unit/integration/E2E tests. Never check a TODO item when its required verification fails.
3. Review staged content for `.env`, credentials, tokens, passwords, personal data, large logs, and unredacted model data.
4. Create an atomic Conventional Commit and immediately push it. Do not create save-point commits or combine unrelated work.
5. Report completed TODOs, changed behavior, checks and results, commit SHA, push status, and the next batch.

Never force-push, rewrite pushed history, use destructive Git operations, or expose credentials unless the user explicitly authorizes the specific action. Never invent performance, reliability, cost, or resume metrics; resume claims must come from reproducible, versioned evaluation runs.

## Architecture boundaries

- Runtime: Python 3.12; API and worker are separate processes.
- Backend: FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, pgvector.
- Workflow: LangGraph typed state, conditional routes, bounded loops/replanning, parallel read-only investigation, PostgreSQL checkpoints, interrupts, resume/cancel, and crash recovery.
- Telemetry: OpenTelemetry plus Prometheus, Loki, and Tempo.
- UI: a deliberately simple Next.js/React administration console.
- Delivery: Docker Compose, Pytest, Testcontainers, mock-model mode, one-command fault injection/cleanup/evaluation.
- Work queue: PostgreSQL claim/lease with concurrency limits. Do not add Kafka or NATS without a superseding ADR backed by measurements.
- Integrations: core tools use the versioned Tool Gateway. MCP is only a future optional read-only adapter.

Do not introduce A2A, a general agent harness, multi-agent writing, collector agents, arbitrary shell agents, production Kubernetes control, multiple agent frameworks, general document Q&A, or comprehensive MCP conversion into the core version.

## Safety and evidence rules

- Ground Truth is evaluation-only and must be physically and logically isolated from agent context and runtime retrieval paths.
- Every factual diagnosis reference must resolve to an immutable Evidence/Artifact record with incident ownership, query provenance, time range, hash, schema version, quality, and expiry state.
- Confidence never substitutes for evidence. The deterministic gate checks existence, ownership, freshness, independent sources, and unresolved counter-evidence.
- Untrusted logs/traces are data, never instructions. Redact secrets and isolate prompt-injection content before model context construction.
- Write tools require typed input and RBAC. `rollback_service` additionally requires Incident ID, Approval ID, and Idempotency Key.
- Approvals expire; any material plan mutation invalidates approval and triggers schema and policy revalidation.
- Executor calls use locks, idempotency, timeout, before/after snapshots, replay protection, and append-only audit events.
- Recovery succeeds only when the deterministic verifier observes the configured stability window across error rate, P95 latency, health endpoint, deployed version, and new alerts.

## Engineering conventions

- Prefer explicit domain types and state-machine transitions over booleans and free-form dictionaries.
- Keep domain logic independent from FastAPI, LangGraph, SQLAlchemy, and model-provider adapters.
- Version schemas, prompts, datasets, policies, and evaluation rules.
- Make retries bounded and classify retryable errors. All external calls need timeouts.
- Use UTC internally; include timezone-aware timestamps.
- Tests must cover success, refusal, timeout, duplicate/replay, concurrent approval, crash/resume, rollback, and authorization failures.
- Keep dependency direction aligned with `docs/ARCHITECTURE.md`; document intentional deviations in an ADR before implementation.
