# Data Model Baseline

This is the conceptual model. SQLAlchemy/Alembic implementation must preserve these invariants and document deviations.

## Operational aggregates

| Aggregate/entity | Important fields and invariants |
| --- | --- |
| Incident | ID, dedupe key, severity, service scope, state, version, opened/closed timestamps; transitions only through state machine. |
| Alert | source ID, fingerprint, observed window, payload Artifact, incident link; deterministic dedupe/merge decision. |
| WorkflowRun | graph/schema version, incident, status, budgets, checkpoint thread ID, attempt/cancel metadata. |
| InvestigationPlan | immutable version, ordered/dependency-aware bounded steps, tool/schema versions, rationale, budget. |
| ToolCall | tool/version, normalized args hash, actor/workflow, permission/risk, timeout/retry, status, result Artifact, audit links. |
| Artifact | immutable locator, media/schema type, content hash, size, retention class, encryption/redaction metadata. |
| Evidence | incident, source, query/time range, Artifact, hash, lineage, quality, parser version, trust and expiry. |
| RootCauseCandidate | rank, structured claim, uncertainty, supporting/contradicting/missing Evidence IDs, version. |
| EvidenceGateDecision | ruleset version, candidate, pass/fail, resolved references, independence/freshness findings, reasons. |
| RemediationProposal | immutable version/hash, gate decision, allowlisted action, typed parameters, validation and rollback specs, risk assumptions. |
| PolicyDecision | policy version, proposal hash, actor/context, risk, allow/deny/approval-required, reasons, expiry constraints. |
| Approval | proposal/policy hashes, approver, decision, reason, timestamps/expiry; cannot be reused after mutation. |
| ActionExecution | action, incident, approval, idempotency key, lock owner, before/after Artifacts, status, timeout/error. |
| VerificationRun | action, criteria version, observation window, metric/health/version/alert Evidence, deterministic result. |
| RollbackExecution | failed action/verification, idempotency key, approval/policy basis, before/after state, result. |
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
| OutboxEvent | transactional event intent and publication status for reliable asynchronous processing. |

## Storage rules

- Use UUID/ULID-style opaque identifiers and timezone-aware UTC timestamps.
- Store large/raw telemetry as Artifacts; keep normalized indexes and immutable hashes in PostgreSQL.
- Use explicit optimistic versions on mutable aggregates.
- Enforce unique idempotency scope at the database level.
- Audit rows are append-only to the application role; corrections are compensating events.
- Embeddings retain source/version metadata and never erase the authoritative textual reference.
- Retention and expiry do not silently delete audit integrity metadata.
