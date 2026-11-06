"""Run a registered SQL-backed lab investigation and stop before human approval."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.application import (
    ModelCallTraceManager,
    PolicyRules,
    evidence_gate_decision_fingerprint,
)
from agentops_incident_commander.domain import (
    ActorId,
    CausationId,
    CorrelationId,
    EventMetadata,
    EventReason,
    Incident,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    Job,
    JobFailureRoute,
    JobId,
    JobLease,
    MaintenanceWindowStatus,
    OpaqueIdentifier,
    PolicyAction,
    PolicyBlastRadius,
    PolicyEnvironment,
    PolicyEvaluationInput,
    Principal,
    PromptVersionReference,
    Role,
    SemanticVersion,
    TenantId,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage
from agentops_incident_commander.infrastructure.persistence.diagnosis_progress import (
    PostgresDiagnosisProgressRecorder,
)
from agentops_incident_commander.infrastructure.persistence.repositories import (
    IncidentRepository,
    JobRepository,
)
from agentops_incident_commander.infrastructure.persistence.runtime_ports import (
    PostgresWorkflowDiagnosisReportStore,
    PostgresWorkflowEvidenceStore,
    PostgresWorkflowModelTraceStore,
    PostgresWorkflowPromptStore,
)
from evaluation.durable_effects import SqlInvestigationEffects
from evaluation.investigation_job import InvestigationJobInput, RegisteredInvestigationJobHandler
from evaluation.leased_worker import LeasedEvaluationWorker
from evaluation.registered_gate import persist_registered_report_gates
from evaluation.registered_model import RegisteredModelInvoker
from evaluation.registered_review import propose_and_request_sql_review
from evaluation.structured_model import ModelPurpose, StructuredEvaluationModel


async def run_registered_case(
    sessions: async_sessionmaker[AsyncSession],
    saver: BaseCheckpointSaver[Any],
    model: StructuredEvaluationModel,
    references: dict[ModelPurpose, PromptVersionReference],
    payload: InvestigationJobInput,
    journal: Callable[[dict[str, Any]], None],
    *,
    adapters: dict[Any, Any] | None = None,
    consume: Callable[[Job, Callable[[JobLease], Awaitable[None]]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Inputs contain observations only; evaluator fault labels are not accepted."""
    principal = Principal(
        ActorId("registered-lab-operator"), TenantId(payload.tenant_id), frozenset({Role.OPERATOR})
    )
    incident_id = IncidentId(payload.incident_id)
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        await IncidentRepository(session).add(
            Incident.open(
                incident_id, principal.tenant_id, IncidentSeverity.SEV2, "gateway", opened_at=now
            )
        )

    async def transition(target: IncidentState) -> None:
        async with sessions.begin() as session:
            repository = IncidentRepository(session)
            current = await repository.get_for_tenant(incident_id, principal.tenant_id)
            if current is None:
                raise ValueError("lab Incident disappeared")
            await repository.apply(
                current.transition(
                    target,
                    expected_version=current.version,
                    metadata=EventMetadata(
                        principal.actor_id,
                        EventReason("Registered lab workflow"),
                        CorrelationId(payload.correlation_id),
                        CausationId(payload.causation_id),
                        datetime.now(UTC),
                    ),
                )
            )

    await transition(IncidentState.TRIAGED)
    await transition(IncidentState.INVESTIGATING)
    reports = PostgresWorkflowDiagnosisReportStore(sessions)
    evidence = PostgresWorkflowEvidenceStore(sessions)
    invoker = RegisteredModelInvoker(
        model,
        PostgresWorkflowPromptStore(sessions),
        ModelCallTraceManager(
            PostgresWorkflowModelTraceStore(sessions, max_calls_per_workflow=5),
            clock=lambda: datetime.now(UTC),
            id_factory=lambda: f"lab-call-{uuid4().hex}",
        ),
        references,
        principal,
        incident_id,
        WorkflowRunId(payload.workflow_run_id),
        CorrelationId(payload.correlation_id),
        CausationId(payload.causation_id),
        journal,
        report_writer=reports,
        report_reader=reports,
    )
    queued = Job(
        id=JobId(f"lab-job-{uuid4().hex}"),
        tenant_id=principal.tenant_id,
        incident_id=incident_id,
        workflow_run_id=invoker.workflow,
        type="workflow.investigate",
        schema_version="workflow/v1",
        payload_ref=OpaqueIdentifier(payload.payload_ref),
        correlation_id=invoker.correlation,
        causation_id=invoker.causation,
        priority=50,
        created_at=now,
        available_at=now,
        max_attempts=1,
        failure_route=JobFailureRoute.NEEDS_HUMAN,
    )
    async with sessions.begin() as session:
        await JobRepository(session).enqueue(queued)

    async def factory() -> RegisteredModelInvoker:
        return invoker

    handler = RegisteredInvestigationJobHandler(
        payload,
        factory,
        saver,
        evidence,
        PostgresDiagnosisProgressRecorder(sessions, max_tool_retries=2),
        journal,
        effects=SqlInvestigationEffects(
            sessions, principal, payload.correlation_id, payload.causation_id
        ),
        adapters=adapters,
    )
    queue_measurements: dict[str, int] = {}

    async def measured_handler(lease: JobLease) -> None:
        queue_measurements.update(
            queue_creation_to_claim_ms=int(
                (lease.leased_at - lease.job.created_at).total_seconds() * 1000
            ),
            queue_ready_to_claim_ms=int(
                (lease.leased_at - lease.job.available_at).total_seconds() * 1000
            ),
        )
        journal(
            {"event": "evaluation.job_claimed", "job_id": lease.job.id.value, **queue_measurements}
        )
        await handler(lease)

    worker = LeasedEvaluationWorker(
        sessions, OpaqueIdentifier(f"lab-worker-{uuid4().hex}"), measured_handler
    )
    result: dict[str, Any] = {
        "incident_id": payload.incident_id,
        "approval_decided": False,
        "recovery_executed": False,
        "actual_bill": None,
    }
    stage = IncidentState.INVESTIGATING
    try:
        if consume is None:
            await worker.run_once()
            result["second_claim_count"] = await worker.run_once()
        else:
            await consume(queued, measured_handler)
            result["execution_mode"] = "SHARED_BATCH_QUEUE"

        await transition(IncidentState.EVIDENCE_REVIEW)
        stage = IncidentState.EVIDENCE_REVIEW
        gates = await persist_registered_report_gates(
            sessions, invoker, LocalArtifactStorage(payload.artifact_root)
        )
        result["gates"] = [
            {
                "candidate_id": g.candidate_id,
                "outcome": g.outcome.value,
                "reasons": [r.code.value for r in g.reasons],
            }
            for g in gates
        ]
        passing = next((g for g in gates if g.outcome.value == "PASS"), None)
        if passing is None:
            await transition(IncidentState.NEEDS_HUMAN)
            result["status"] = "HUMAN_HANDOFF"
            result.update(queue_measurements)
            return result
        record = await reports.latest(tenant_id=principal.tenant_id, incident_id=incident_id)
        assert record is not None
        observations = []
        for identifier in passing.evaluated_evidence_ids:
            item = await evidence.get(
                identifier, tenant_id=principal.tenant_id, incident_id=incident_id
            )
            if item is None:
                raise ValueError("Gate Evidence disappeared")
            artifact = LocalArtifactStorage(payload.artifact_root).retrieve(
                item.artifact_id, incident_id=incident_id, principal=principal, at=datetime.now(UTC)
            )
            observations.append(
                {
                    "id": identifier.value,
                    "source": item.source_type.value,
                    "content": artifact.content.decode("utf-8"),
                }
            )
        await transition(IncidentState.PLANNING_REMEDIATION)
        stage = IncidentState.PLANNING_REMEDIATION

        # Policy is server-owned, independent of model risk assertions.
        def policy_input(admitted: Any) -> PolicyEvaluationInput:
            proposal = admitted.proposal
            return PolicyEvaluationInput(
                principal.tenant_id,
                incident_id,
                OpaqueIdentifier(proposal.proposal_id),
                proposal.proposal_version,
                proposal.fingerprint,
                evidence_gate_decision_fingerprint(passing),
                principal.actor_id,
                principal.roles,
                PolicyEnvironment.STAGING,
                PolicyAction.ROLLBACK_SERVICE,
                proposal.parameters.service,
                PolicyBlastRadius.SINGLE_SERVICE,
                MaintenanceWindowStatus.NOT_REQUIRED,
                True,
                datetime.now(UTC),
            )

        async def before_policy() -> None:
            nonlocal stage
            await transition(IncidentState.POLICY_REVIEW)
            stage = IncidentState.POLICY_REVIEW

        admitted, policy, approval = await propose_and_request_sql_review(
            sessions,
            invoker,
            passing,
            {
                "incident_id": payload.incident_id,
                "observations": observations,
                "evidence_ids": [e.value for e in passing.evaluated_evidence_ids],
                "stability_window_seconds": 300,
            },
            policy_input,
            PolicyRules(
                SemanticVersion("1.0.0"),
                frozenset({PolicyEnvironment.STAGING}),
                frozenset({Role.OPERATOR}),
                frozenset({PolicyAction.ROLLBACK_SERVICE}),
                frozenset({"gateway", "order", "inventory", "payment"}),
                frozenset({PolicyBlastRadius.SINGLE_SERVICE}),
                False,
                True,
                timedelta(minutes=30),
            ),
            before_policy=before_policy,
        )
        await transition(IncidentState.AWAITING_APPROVAL if approval else IncidentState.NEEDS_HUMAN)
        result.update(
            status="PENDING_APPROVAL" if approval else "POLICY_REFUSED",
            proposal=admitted.proposal.model_dump(mode="json"),
            policy_outcome=policy.outcome.value,
            approval_id=approval.id.value if approval else None,
        )
    except Exception as error:
        result.update(status="FAILED", error_type=type(error).__name__)
        if stage is IncidentState.INVESTIGATING:
            await transition(IncidentState.EVIDENCE_REVIEW)
        await transition(IncidentState.NEEDS_HUMAN)
    result.update(queue_measurements)
    return result
