"""Transaction-owning ports for workflows that span multiple repository operations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application.prompt_registry import PromptLifecycleChange
from agentops_incident_commander.domain import (
    Artifact,
    AuditEvent,
    Evidence,
    EvidenceId,
    IncidentId,
    ModelCallId,
    ModelCallTrace,
    PromptDefinition,
    PromptId,
    SemanticVersion,
    TenantId,
)

from .repositories import EvidenceRepository, ModelCallTraceRepository, PromptLifecycleRepository


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

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def start(self, trace: ModelCallTrace, audit_event: AuditEvent) -> None:
        async with self._sessions.begin() as session:
            await ModelCallTraceRepository(session).start(trace, audit_event)

    async def finish(
        self, expected: ModelCallTrace, completed: ModelCallTrace, audit_event: AuditEvent
    ) -> None:
        async with self._sessions.begin() as session:
            await ModelCallTraceRepository(session).finish(expected, completed, audit_event)

    async def get(self, tenant_id: TenantId, call_id: ModelCallId) -> ModelCallTrace | None:
        async with self._sessions() as session:
            return await ModelCallTraceRepository(session).get(tenant_id, call_id)
