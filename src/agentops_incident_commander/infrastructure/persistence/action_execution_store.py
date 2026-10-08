"""Transaction-owning durable ActionExecution application-store adapter."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    EventMetadata,
    EventReason,
    Incident,
    IncidentState,
    InvalidDomainValueError,
    Sha256Digest,
)

from .models import AuditEventRow, IncidentRow
from .repositories import ActionExecutionRepository, AuditRepository, IncidentRepository

ACTION_EXECUTION_INCIDENT_AUDIT_SCHEMA_VERSION = "action_execution_incident/v1"


class PostgresActionExecutionStore:
    """Commit each claim, replay observation, and completion as its own durable boundary."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim(
        self,
        execution: ActionExecution,
        audit_event: AuditEvent,
        replay_audit_factory: Callable[[ActionExecution], AuditEvent],
    ) -> tuple[ActionExecution, bool]:
        async with self._sessions.begin() as session:
            repository = ActionExecutionRepository(session)
            stored, replayed = await repository.claim(execution, audit_event)
            if replayed:
                await repository.record_replay(
                    execution,
                    stored,
                    replay_audit_factory(stored),
                )
            return stored, replayed

    async def finish(
        self,
        expected: ActionExecution,
        completed: ActionExecution,
        audit_event: AuditEvent,
    ) -> ActionExecution:
        async with self._sessions.begin() as session:
            return await ActionExecutionRepository(session).finish(
                expected,
                completed,
                audit_event,
            )


class PostgresLifecycleActionExecutionStore(PostgresActionExecutionStore):
    """Atomically bind ActionExecution persistence to the Incident execution states."""

    async def claim(
        self,
        execution: ActionExecution,
        audit_event: AuditEvent,
        replay_audit_factory: Callable[[ActionExecution], AuditEvent],
    ) -> tuple[ActionExecution, bool]:
        async with self._sessions.begin() as session:
            repository = ActionExecutionRepository(session)
            stored, replayed = await repository.claim(execution, audit_event)
            if replayed:
                await repository.record_replay(
                    execution,
                    stored,
                    replay_audit_factory(stored),
                )
            else:
                await self._transition_once(
                    session,
                    stored,
                    expected_state=IncidentState.READY_TO_EXECUTE,
                    target_state=IncidentState.EXECUTING,
                    event_type="action.execution_incident_started",
                    request_hash=stored.request_fingerprint,
                    result_hash=stored.fingerprint,
                    occurred_at=stored.started_at,
                    correlation_audit=audit_event,
                )
            return stored, replayed

    async def finish(
        self,
        expected: ActionExecution,
        completed: ActionExecution,
        audit_event: AuditEvent,
    ) -> ActionExecution:
        async with self._sessions.begin() as session:
            stored = await ActionExecutionRepository(session).finish(
                expected,
                completed,
                audit_event,
            )
            if stored.status is ActionExecutionStatus.SUCCEEDED:
                target_state = IncidentState.VERIFYING
            elif stored.status is ActionExecutionStatus.FAILED:
                target_state = IncidentState.INVESTIGATING
            elif stored.status in {
                ActionExecutionStatus.TIMED_OUT,
                ActionExecutionStatus.UNCERTAIN,
            }:
                target_state = IncidentState.NEEDS_HUMAN
            else:  # pragma: no cover - ActionExecutionRepository contract defense
                raise InvalidDomainValueError("terminal action execution status is invalid")
            completed_at = stored.completed_at
            if completed_at is None:  # pragma: no cover - ActionExecution contract defense
                raise InvalidDomainValueError("terminal action execution time is missing")
            await self._transition_once(
                session,
                stored,
                expected_state=IncidentState.EXECUTING,
                target_state=target_state,
                event_type="action.execution_incident_routed",
                request_hash=expected.fingerprint,
                result_hash=stored.fingerprint,
                occurred_at=completed_at,
                correlation_audit=audit_event,
            )
            return stored

    @staticmethod
    async def _transition_once(
        session: AsyncSession,
        execution: ActionExecution,
        *,
        expected_state: IncidentState,
        target_state: IncidentState,
        event_type: str,
        request_hash: Sha256Digest,
        result_hash: Sha256Digest,
        occurred_at: datetime,
        correlation_audit: AuditEvent,
    ) -> Incident:
        identity = (
            f"{event_type}:{execution.tenant_id.value}:{execution.incident_id.value}:"
            f"{execution.id.value}:{execution.fingerprint.value}"
        )
        audit_id = AuditEventId(
            f"audit-action-incident-{hashlib.sha256(identity.encode()).hexdigest()}"
        )
        existing_audit = await session.scalar(
            select(AuditEventRow.id).where(AuditEventRow.id == audit_id.value)
        )
        await session.scalar(
            select(IncidentRow.id)
            .where(
                IncidentRow.id == execution.incident_id.value,
                IncidentRow.tenant_id == execution.tenant_id.value,
            )
            .with_for_update()
        )
        incidents = IncidentRepository(session)
        incident = await incidents.get_for_tenant(execution.incident_id, execution.tenant_id)
        if incident is None:  # pragma: no cover - ActionExecution foreign-key defense
            raise InvalidDomainValueError("action execution Incident was not found")
        if existing_audit is not None:
            return incident
        if incident.state is not expected_state:
            raise InvalidDomainValueError("action execution Incident state is invalid")
        metadata = EventMetadata(
            execution.actor_id,
            EventReason(
                f"ActionExecution {execution.id.value} routed "
                f"{expected_state.value} to {target_state.value}."
            ),
            correlation_audit.correlation_id,
            CausationId(execution.id.value),
            occurred_at,
        )
        change = incident.transition(
            target_state,
            expected_version=incident.version,
            metadata=metadata,
        )
        await incidents.apply(change)
        await AuditRepository(session).append(
            AuditEvent(
                audit_id,
                execution.tenant_id,
                event_type,
                1,
                ACTION_EXECUTION_INCIDENT_AUDIT_SCHEMA_VERSION,
                execution.actor_id,
                correlation_audit.correlation_id,
                metadata.causation_id,
                AuditTarget("incident.lifecycle", execution.incident_id),
                occurred_at,
                request_hash,
                result_hash,
            )
        )
        return change.incident
