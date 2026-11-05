"""Transaction-owning ports for workflows that span multiple repository operations."""

from __future__ import annotations

import hashlib

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application.prompt_registry import PromptLifecycleChange
from agentops_incident_commander.domain import (
    Artifact,
    AuditEvent,
    Evidence,
    EvidenceId,
    IncidentId,
    InvalidDomainValueError,
    ModelCallId,
    ModelCallTrace,
    PromptDefinition,
    PromptId,
    SemanticVersion,
    TenantId,
)
from agentops_incident_commander.workflows import DiagnosisReportRecord

from .models import ModelCallTraceRow
from .repositories import (
    DiagnosisReportRepository,
    EvidenceRepository,
    ModelCallTraceRepository,
    PromptLifecycleRepository,
)


class PostgresWorkflowEvidenceStore:
    """Commit immutable Evidence before the workflow publishes its identifiers."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, evidence: Evidence, artifact: Artifact) -> None:
        async with self._sessions.begin() as session:
            await EvidenceRepository(session).add(evidence, artifact)

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None:
        async with self._sessions() as session:
            return await EvidenceRepository(session).get(
                evidence_id, tenant_id=tenant_id, incident_id=incident_id
            )


class PostgresWorkflowPromptStore:
    """Resolve exact registrations and atomically commit lifecycle plus audit."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def resolve(
        self, tenant_id: TenantId, prompt_id: PromptId, version: SemanticVersion
    ) -> PromptDefinition | None:
        async with self._sessions() as session:
            return await PromptLifecycleRepository(session).resolve(tenant_id, prompt_id, version)

    async def active(self, tenant_id: TenantId, prompt_id: PromptId) -> PromptDefinition | None:
        async with self._sessions() as session:
            return await PromptLifecycleRepository(session).active(tenant_id, prompt_id)

    async def apply(self, change: PromptLifecycleChange, audit_event: AuditEvent) -> None:
        async with self._sessions.begin() as session:
            await PromptLifecycleRepository(session).apply(change, audit_event)


class PostgresWorkflowModelTraceStore:
    """Durably commit model-call start before dispatch, and finish plus audit afterward."""

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, max_calls_per_workflow: int = 4
    ) -> None:
        if type(max_calls_per_workflow) is not int or not 1 <= max_calls_per_workflow <= 128:
            raise InvalidDomainValueError("workflow model-call budget must be between 1 and 128")
        self._sessions = sessions
        self._max_calls = max_calls_per_workflow

    async def start(self, trace: ModelCallTrace, audit_event: AuditEvent) -> None:
        async with self._sessions.begin() as session:
            scope = f"model-budget:{trace.tenant_id.value}:{trace.workflow_run_id.value}"
            key = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], signed=True)
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
            consumed = int(
                (
                    await session.scalar(
                        select(func.count(ModelCallTraceRow.id)).where(
                            ModelCallTraceRow.tenant_id == trace.tenant_id.value,
                            ModelCallTraceRow.workflow_run_id == trace.workflow_run_id.value,
                        )
                    )
                )
                or 0
            )
            if consumed >= self._max_calls:
                raise InvalidDomainValueError("durable workflow model-call budget exhausted")
            await ModelCallTraceRepository(session).start(trace, audit_event)

    async def finish(
        self, expected: ModelCallTrace, completed: ModelCallTrace, audit_event: AuditEvent
    ) -> None:
        async with self._sessions.begin() as session:
            await ModelCallTraceRepository(session).finish(expected, completed, audit_event)

    async def get(self, tenant_id: TenantId, call_id: ModelCallId) -> ModelCallTrace | None:
        async with self._sessions() as session:
            return await ModelCallTraceRepository(session).get(tenant_id, call_id)


class PostgresWorkflowDiagnosisReportStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def latest(
        self, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> DiagnosisReportRecord | None:
        async with self._sessions() as session:
            return await DiagnosisReportRepository(session).latest(
                tenant_id=tenant_id, incident_id=incident_id
            )

    async def record(
        self, record: DiagnosisReportRecord, audit_event: AuditEvent
    ) -> DiagnosisReportRecord:
        async with self._sessions.begin() as session:
            return await DiagnosisReportRepository(session).record(record, audit_event)
