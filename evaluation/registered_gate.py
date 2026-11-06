"""Re-resolve SQL report Evidence and commit decisions before remediation admission."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application import (
    evaluate_evidence_gate,
    evidence_gate_decision_fingerprint,
    resolve_gate_evidence_references,
)
from agentops_incident_commander.domain import (
    ArtifactStorage,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    EvidenceGateDecision,
    EvidenceGateRules,
    ModelCallStatus,
    OpaqueIdentifier,
    Permission,
    require_permission,
)
from agentops_incident_commander.infrastructure.persistence.repositories import (
    EvidenceGateRepository,
)
from agentops_incident_commander.infrastructure.persistence.runtime_ports import (
    PostgresWorkflowDiagnosisReportStore,
    PostgresWorkflowEvidenceStore,
    PostgresWorkflowModelTraceStore,
)
from evaluation.registered_model import RegisteredModelInvoker


async def persist_registered_report_gates(
    sessions: async_sessionmaker[AsyncSession],
    invoker: RegisteredModelInvoker,
    artifacts: ArtifactStorage,
) -> tuple[EvidenceGateDecision, ...]:
    """No caller-supplied report/decision can substitute for the stored model result."""
    principal = invoker.principal
    require_permission(principal, Permission.REMEDIATION_REQUEST, tenant_id=principal.tenant_id)
    record = await PostgresWorkflowDiagnosisReportStore(sessions).latest(
        tenant_id=principal.tenant_id, incident_id=invoker.incident
    )
    if record is None or record.workflow_run_id != invoker.workflow:
        raise ValueError("registered Gate report binding unavailable")
    trace = await PostgresWorkflowModelTraceStore(sessions).get(
        principal.tenant_id, record.model_call_id
    )
    if (
        trace is None
        or trace.tenant_id != principal.tenant_id
        or trace.incident_id != invoker.incident
        or trace.workflow_run_id != invoker.workflow
        or trace.status is not ModelCallStatus.SUCCEEDED
        or trace.response_hash != record.report_fingerprint
    ):
        raise ValueError("registered Gate model trace binding unavailable")
    evidence = PostgresWorkflowEvidenceStore(sessions)
    rules = EvidenceGateRules()
    decisions = []
    for candidate in record.report.candidates:
        at = datetime.now(UTC)
        claim = record.report.evidence_gate_claim(candidate.candidate_id)
        resolution = await resolve_gate_evidence_references(
            claim,
            tenant_id=principal.tenant_id,
            principal=principal,
            reader=evidence,
            artifact_storage=artifacts,
            at=at,
        )
        decision = evaluate_evidence_gate(claim, resolution, rules=rules, at=at)
        async with sessions.begin() as session:
            await EvidenceGateRepository(session).record(
                tenant_id=principal.tenant_id,
                claim=claim,
                evidence=resolution.verified_evidence,
                rules=rules,
                decision=decision,
                audit_event=AuditEvent(
                    id=AuditEventId(f"registered-gate-{uuid4().hex}"),
                    tenant_id=principal.tenant_id,
                    type="evidence.gate_decided",
                    event_version=1,
                    payload_schema_version="evidence_gate/v1",
                    actor_id=principal.actor_id,
                    correlation_id=invoker.correlation,
                    causation_id=invoker.causation,
                    target=AuditTarget(
                        "evidence.gate_decision", OpaqueIdentifier(decision.input_fingerprint.value)
                    ),
                    occurred_at=at,
                    request_hash=decision.input_fingerprint,
                    result_hash=evidence_gate_decision_fingerprint(decision),
                ),
            )
        decisions.append(decision)
    return tuple(decisions)
