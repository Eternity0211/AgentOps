# AgentOps Incident Commander Data Model Baseline

This is the conceptual model. SQLAlchemy/Alembic implementation must preserve these invariants and document deviations.

## Operational aggregates

| Aggregate/entity | Important fields and invariants |
| --- | --- |
| Incident | ID, dedupe key, severity, service scope, state, version, opened/closed/cancelled timestamps; transitions only through the complete state machine. Terminal states are `CLOSED` and `CANCELLED`; durable waits are `AWAITING_APPROVAL` and `NEEDS_HUMAN`; other non-terminals are checkpoint-recoverable active states. |
| Alert | source ID, fingerprint, observed window, payload Artifact, incident link; deterministic dedupe/merge decision. |
| WorkflowRun | graph/schema version, incident, status, budgets, checkpoint thread ID, attempt/cancel metadata. |
| InvestigationPlan | immutable version, ordered/dependency-aware bounded steps, tool/schema versions, rationale, budget. |
| ToolCall | tool/version, normalized args hash, actor/workflow, permission/risk, timeout/retry, status, result Artifact, audit links. |
| Artifact | immutable locator, media/schema type, content hash, size, retention class, encryption/redaction metadata. |
| Evidence | incident, source, query/time range, Artifact, hash, lineage, quality, parser version, trust and expiry. |
| RootCauseCandidate | rank, structured claim, uncertainty, supporting/contradicting/missing Evidence IDs, version. |
| EvidenceGateDecision | ruleset version, candidate, pass/fail, resolved references, independence/freshness findings, reasons. |
| RemediationProposal | immutable version/hash, gate decision, allowlisted recovery action, typed parameters, validation spec, failure routing, optional compensation eligibility, risk assumptions. `rollback_service` compensation eligibility is always false. |
| PolicyDecision | policy version, proposal hash, actor/context, risk, allow/deny/approval-required, reasons, expiry constraints. |
| Approval | proposal/policy hashes, approver, status (`PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`), reason, timestamps/expiry; cannot be reused after mutation. Rejection/expiry are not Incident states. |
| ActionExecution | recovery action, incident, approval, idempotency key, lock owner, before/after Artifacts, status, timeout/error. For `rollback_service`, records faulty and target stable versions and forbids the faulty version as automatic compensation target. |
| VerificationRun | action, criteria version, observation window, metric/health/version/alert Evidence, deterministic result. |
| CompensationExecution | future-only safe inverse for an explicitly reversible action; original action/verification, independent policy/approval, idempotency key, before/after state, and result. It is not created for failed `rollback_service`. |
| GroundTruthScenario | evaluator-only scenario/version, root cause, expected evidence, automation eligibility, expected safe outcome/handoff, recovery action, verification, cleanup procedure, and future-tool requirement. |
| Postmortem | version, incident, confirmed facts, Evidence references, generated draft, human revisions and authorship. |
| AuditEvent | append-only sequence, event type/version, actor, correlation/causation IDs, target, request/result hashes, timestamp. |

## Platform configuration and memory

| Entity | Purpose |
| --- | --- |
| ToolDefinition | Versioned schemas, read/write class, risk, permission, timeouts, retries, idempotency contract. |
| PromptDefinition | Prompt ID/semantic version, content fingerprint, model settings, schema compatibility, status and rollback link. |
| IncidentMemory | Closed-incident summary with source links, embedding/model version, outcome confidence; reference-only. |
| JobLease | job type/payload reference, state, priority, available time, lease owner/expiry/heartbeat, attempts. |
| WorkflowCheckpoint | LangGraph checkpoint, schema/graph versions, thread/run IDs, created time and integrity metadata. |
| OutboxEvent | Stable/global sequence, topic/schema version, aggregate identity/version, bounded canonical payload/hash, correlation/causation, availability, publication lease/attempts, retry/dead-letter status. It is committed with aggregate state and is distinct from the general JobLease queue. |

## Storage rules

- Use UUID/ULID-style opaque identifiers and timezone-aware UTC timestamps.
- Store large/raw telemetry as Artifacts; keep normalized indexes and immutable hashes in PostgreSQL.
- Use explicit optimistic versions on mutable aggregates.
- Enforce unique idempotency scope at the database level.
- Audit rows are append-only to the application role; corrections are compensating events.
- Embeddings retain source/version metadata and never erase the authoritative textual reference.
- Retention and expiry do not silently delete audit integrity metadata.

## State ownership and liveness invariants

- Incident states are `DETECTED`, `TRIAGED`, `INVESTIGATING`, `EVIDENCE_REVIEW`, `NEEDS_HUMAN`, `PLANNING_REMEDIATION`, `POLICY_REVIEW`, `AWAITING_APPROVAL`, `READY_TO_EXECUTE`, `EXECUTING`, `VERIFYING`, `COMPENSATING`, `VERIFYING_COMPENSATION`, `RESOLVED`, `CLOSED`, and `CANCELLED`.
- `REJECTED` and `EXPIRED` belong to Approval; they route the Incident to replanning or human handling.
- Cancellation is immediately legal before side-effect execution from the explicitly enumerated states in `PROJECT_SPEC.md`. Requests during execution/verification are deferred to the next safe boundary.
- No non-terminal Incident state may lack a legal outgoing transition. Exhaustive tests assert liveness and transition parity between domain code, persistence constraints, API commands, and LangGraph routes.
- `COMPENSATING` and `VERIFYING_COMPENSATION` are unreachable for the MVP `rollback_service`; future tools must opt in through versioned tool metadata, policy, and approval.
