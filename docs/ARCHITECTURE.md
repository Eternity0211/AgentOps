# AgentOps Incident Commander Architecture

## System context

```mermaid
flowchart LR
    O[Operator / Approver] --> UI[Next.js Admin Console]
    UI --> API[FastAPI Control Plane]
    AS[Alert Source] --> API
    API --> DB[(PostgreSQL + pgvector)]
    API --> Q[PostgreSQL Job/Lease Queue]
    W[Workflow Worker] --> Q
    W <--> DB
    W --> TG[Tool Gateway]
    TG --> OBS[Prometheus / Loki / Tempo]
    TG --> DEP[Deployment Records]
    TG --> SIM[Microservice Simulator]
    SIM --> OTEL[OpenTelemetry Collector]
    OTEL --> OBS
    W --> LLM[Model Provider or Mock Model]
    EV[Evaluation Harness] --> API
    EV --> GT[(Evaluation-only Ground Truth)]
    API -. no access .-> GT
    W -. no access .-> GT
```

## Container/module boundaries

| Boundary | Responsibility | Must not do |
| --- | --- | --- |
| API | authentication, RBAC, incident/approval/query APIs, request validation, job creation | execute recovery inline or own workflow loops |
| Worker | claim leased work, run LangGraph workflows, persist checkpoints | bypass gateway/policy/approval |
| Domain | incident states, evidence/policy/action contracts and invariants | depend on FastAPI, ORM, or model SDKs |
| Evidence | normalize, redact, hash, persist, expire, resolve artifacts | infer root cause |
| Tool Gateway | validate versioned calls, enforce permission/risk/timeout/retry/idempotency, audit | expose arbitrary shell/network capabilities |
| Policy/Approval | deterministic risk decisions and proposal-bound approvals | trust client-side checks |
| Executor | allowlisted idempotent mutation with locks and snapshots | accept free-form commands |
| Verifier/Compensation | determine observed recovery and, only for future explicitly reversible actions, verify authorized compensation | accept LLM success claims or infer that every action has a safe inverse |
| Evaluation | datasets, Ground Truth, baselines, scoring, reports | leak labels to runtime/model context |
| Console | explain state/evidence and collect authorized intent | become system of record |

## Workflow graph

```mermaid
flowchart TD
    A[Alert ingest] --> D[Deduplicate / merge / triage]
    D --> C[Load topology and bounded context]
    C --> DA[Diagnosis Agent: bounded plan]
    DA --> P{Parallel read-only tools}
    P --> E[Normalize + redact + persist evidence]
    E --> H[Root-cause hypotheses with references]
    H --> G{Deterministic Evidence Gate}
    G -->|insufficient and budget remains| DA
    G -->|insufficient or budget exhausted| X[Human handoff]
    G -->|pass| RA[Remediation Agent: typed proposal]
    RA --> S[Schema validation]
    S --> PE{Policy Engine}
    PE -->|deny, replannable| RA
    PE -->|deny, no safe plan| X
    PE -->|approval required| I[LangGraph interrupt]
    I --> AP{Human approval valid?}
    AP -->|rejected / expired, replannable| RA
    AP -->|rejected / expired, no safe plan| X
    AP -->|yes| EX[Deterministic idempotent executor]
    PE -->|allowed| EX
    EX --> V{Deterministic health verification}
    V -->|stable| CL[Resolve and close]
    V -->|rollback_service failed, budget remains| DA
    V -->|rollback_service failed / no budget| X
    V -->|future action: separately authorized compensation| CP[Deterministic compensation]
    CP --> CV{Verify compensation}
    CV -->|safe baseline restored, budget remains| DA
    CV -->|failed / no budget| X
    CL --> PM[Evidence-linked postmortem node]
```

## Incident state topology

Approval `REJECTED` and `EXPIRED` are Approval-record statuses and therefore do not appear as Incident states. The graph uses the same state names as the domain model and project specification.

```mermaid
stateDiagram-v2
    [*] --> DETECTED
    DETECTED --> TRIAGED
    TRIAGED --> INVESTIGATING
    INVESTIGATING --> EVIDENCE_REVIEW
    EVIDENCE_REVIEW --> INVESTIGATING: bounded replan
    EVIDENCE_REVIEW --> NEEDS_HUMAN: insufficient evidence or budget
    EVIDENCE_REVIEW --> PLANNING_REMEDIATION: evidence gate passed
    PLANNING_REMEDIATION --> POLICY_REVIEW: valid proposal
    PLANNING_REMEDIATION --> INVESTIGATING: diagnosis must be revised
    PLANNING_REMEDIATION --> NEEDS_HUMAN: no safe proposal
    POLICY_REVIEW --> PLANNING_REMEDIATION: denied but replannable
    POLICY_REVIEW --> NEEDS_HUMAN: denied with no safe plan
    POLICY_REVIEW --> AWAITING_APPROVAL: approval required
    POLICY_REVIEW --> READY_TO_EXECUTE: policy permits
    AWAITING_APPROVAL --> READY_TO_EXECUTE: approved
    AWAITING_APPROVAL --> PLANNING_REMEDIATION: rejected or expired, retry allowed
    AWAITING_APPROVAL --> NEEDS_HUMAN: rejected or expired, no safe retry
    READY_TO_EXECUTE --> EXECUTING
    EXECUTING --> VERIFYING: action result is observable
    EXECUTING --> INVESTIGATING: failed safely before side effect
    EXECUTING --> NEEDS_HUMAN: uncertain or unsafe execution result
    VERIFYING --> RESOLVED: stable health window passed
    VERIFYING --> INVESTIGATING: budgeted re-diagnosis
    VERIFYING --> NEEDS_HUMAN: no safe automated route
    VERIFYING --> COMPENSATING: future reversible action separately authorized
    COMPENSATING --> VERIFYING_COMPENSATION
    COMPENSATING --> NEEDS_HUMAN: compensation failed or uncertain
    VERIFYING_COMPENSATION --> INVESTIGATING: safe baseline restored and budget remains
    VERIFYING_COMPENSATION --> NEEDS_HUMAN: failed or no budget
    NEEDS_HUMAN --> INVESTIGATING: human resumes diagnosis
    NEEDS_HUMAN --> PLANNING_REMEDIATION: human supplies safe planning input
    NEEDS_HUMAN --> VERIFYING: recorded external action
    RESOLVED --> CLOSED
    CLOSED --> [*]
    CANCELLED --> [*]

    DETECTED --> CANCELLED
    TRIAGED --> CANCELLED
    INVESTIGATING --> CANCELLED
    EVIDENCE_REVIEW --> CANCELLED
    NEEDS_HUMAN --> CANCELLED
    PLANNING_REMEDIATION --> CANCELLED
    POLICY_REVIEW --> CANCELLED
    AWAITING_APPROVAL --> CANCELLED
    READY_TO_EXECUTE --> CANCELLED
```

`CLOSED` and `CANCELLED` are terminal. `AWAITING_APPROVAL` and `NEEDS_HUMAN` are durable waits. All other non-terminal states are checkpoint-recoverable active states, with `RESOLVED` awaiting closure. Cancellation during execution, verification, or compensation is recorded but deferred until deterministic processing reaches a permitted safe state.

## LangGraph state and durability

The graph state is a versioned Pydantic model holding identifiers and bounded summaries, not large raw telemetry. Raw results live behind Artifact references. Key fields include workflow/incident IDs, state schema version, plan and attempt budgets, selected tool calls, evidence IDs, hypotheses, gate decision, remediation proposal fingerprint, policy decision, approval reference, recovery-action reference, verification observations, optional compensation authorization/reference, and error classification.

Each externally visible transition writes domain state, outbox/audit event, and next job intent transactionally where possible. PostgreSQL checkpointing supports pauses, interrupts, safe-boundary cancellation, and worker recovery. Jobs use `SELECT ... FOR UPDATE SKIP LOCKED` (or an equivalently documented strategy), owner/lease timestamps, heartbeat, attempts, and stale-lease reclamation. Execution idempotency is independent of workflow retry semantics.

LangGraph, rather than a black-box general ReAct agent, is the workflow authority because the graph must expose safety routing, durable pauses, resumption, and compensation. `langchain-core` model/message/tool-schema or retriever components may be used underneath nodes where helpful, but Evidence, Policy, RBAC, Executor, and Verifier remain application/domain responsibilities.

## Investigation parallelism and bounded loops

The Diagnosis Agent may propose only tools from the supplied catalog and within maximum step, parallelism, wall-clock, and token budgets. Tool arguments pass schemas before dispatch. Independent read-only calls can fan out; results join at evidence normalization. A deterministic router decides whether missing evidence justifies replanning. Replanning has a hard attempt limit and repeated-equivalent-query detection.

## Data and trust flow

```text
telemetry/deployments (untrusted)
  -> tool adapter -> raw Artifact (immutable/hash)
  -> parser/redactor/injection classifier
  -> normalized Evidence (provenance + quality)
  -> budgeted Context Builder output
  -> agent hypothesis (references only)
  -> Evidence Gate resolves references against store
```

Historical incidents use a separate trust label. Similarity search results include source incident, age, outcome status, and Artifact links; they can suggest a query but cannot satisfy evidence requirements for the current incident.

## Control plane safety sequence

Approval binds `(incident_id, proposal_hash, policy_decision_id, actor, expiry)`. Immediately before execution, the server re-loads all records, verifies RBAC, state, hashes, expiry, policy version, and idempotency key, then acquires a target/action lock. Any material proposal edit creates a new version and invalidates the old approval. Append-only events capture request and result hashes plus before/after state.

`rollback_service` is a forward recovery action to a known stable version. Its pre-action faulty version is not a safe compensation target. Failed verification therefore routes to bounded re-diagnosis or human handoff. A future action can enter `COMPENSATING` only when the tool declares a typed safe inverse and a separate policy decision/approval authorizes it; compensation success restores a safe baseline but still returns to investigation or human handling rather than resolving the incident.

## API outline

The initial API surface will be versioned under `/api/v1` and cover authentication principal resolution, incidents, timelines, investigation control, evidence/artifacts, hypotheses, approvals, actions, verification, audit, prompts, tools, and evaluations. Commands use idempotency keys and optimistic concurrency/version fields. Read APIs paginate and enforce incident-level authorization.

## Deployment topology

The reference Compose topology separates `api`, `worker`, `console`, control-plane `postgres`, observability backends, OTel Collector, and simulator services. The simulator includes its own PostgreSQL and Redis as diagnosed dependencies. Redis is not a control-plane queue or cache in the MVP. The runtime and Ground Truth evaluator use different Compose profiles/networks/credentials so runtime containers cannot read evaluation labels.

## Dependency direction

```text
adapters (FastAPI, SQLAlchemy, LangGraph, providers, telemetry)
    -> application use cases
        -> domain contracts and invariants
```

Infrastructure implements domain ports. Domain code does not import web, ORM, graph, or vendor SDKs. This keeps policy, evidence gates, state transitions, and idempotency directly unit-testable.

## Planned package shape

```text
src/agentops_incident_commander/apps/            FastAPI and worker composition
src/agentops_incident_commander/domain/          pure domain models and invariants
src/agentops_incident_commander/application/     use cases and ports
src/agentops_incident_commander/workflows/       LangGraph state/nodes/routes
src/agentops_incident_commander/infrastructure/  SQLAlchemy, tools, model and telemetry adapters
console/                  Next.js UI
simulator/                services, scenarios and fault controls
evaluation/               datasets, isolated Ground Truth and scoring
tests/                    unit, contract, integration, workflow and E2E
```

This source layout is now enforced incrementally by `python scripts/dev.py architecture`. The domain package cannot import the API/application/workflow/infrastructure layers or the web, ORM, graph, and model-provider SDKs owned by those layers. Additional cross-layer rules are added alongside the corresponding packages rather than claiming checks for code that does not yet exist.
