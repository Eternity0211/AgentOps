"""Transaction-owning adapters for deterministic verification outcome routing."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application import (
    FailedHealthVerificationRouter,
    SuccessfulHealthVerificationRouter,
)
from agentops_incident_commander.domain import (
    AuditEventId,
    CorrelationId,
    Incident,
    IncidentId,
    OpaqueIdentifier,
    Principal,
)
from agentops_incident_commander.workflows import RemediationProposal

from .repositories import HealthVerificationRepository


class PostgresSuccessfulHealthVerificationRouter:
    """Own one transaction for the persisted PASS closure route."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime],
        audit_event_id_factory: Callable[[], AuditEventId],
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._audit_event_id_factory = audit_event_id_factory

    async def close(
        self,
        decision_id: OpaqueIdentifier,
        incident_id: IncidentId,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> Incident:
        async with self._sessions.begin() as session:
            return await SuccessfulHealthVerificationRouter(
                HealthVerificationRepository(session),
                clock=self._clock,
                audit_event_id_factory=self._audit_event_id_factory,
            ).close(
                decision_id,
                incident_id,
                principal=principal,
                correlation_id=correlation_id,
            )


class PostgresFailedHealthVerificationRouter:
    """Own one transaction for the persisted non-compensable FAIL route."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime],
        audit_event_id_factory: Callable[[], AuditEventId],
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._audit_event_id_factory = audit_event_id_factory

    async def route(
        self,
        decision_id: OpaqueIdentifier,
        incident_id: IncidentId,
        proposal: RemediationProposal,
        *,
        used_rediagnosis_attempts: int,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> Incident:
        async with self._sessions.begin() as session:
            return await FailedHealthVerificationRouter(
                HealthVerificationRepository(session),
                clock=self._clock,
                audit_event_id_factory=self._audit_event_id_factory,
            ).route(
                decision_id,
                incident_id,
                proposal,
                used_rediagnosis_attempts=used_rediagnosis_attempts,
                principal=principal,
                correlation_id=correlation_id,
            )
