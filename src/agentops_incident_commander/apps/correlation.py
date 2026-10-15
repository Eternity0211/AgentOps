"""Worker composition for durable Incident control-flow correlation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.infrastructure.persistence import PostgresCorrelationLinkStore
from agentops_incident_commander.workflows import IncidentCorrelationWorkflow


@dataclass(frozen=True, slots=True)
class IncidentCorrelationRuntime:
    """Durable workflow exposed to worker handlers at authoritative boundaries."""

    workflow: IncidentCorrelationWorkflow


def compose_incident_correlation_runtime(
    sessions: async_sessionmaker[AsyncSession],
) -> IncidentCorrelationRuntime:
    """Compose transaction-owning PostgreSQL correlation for long-lived Incident work."""
    return IncidentCorrelationRuntime(
        IncidentCorrelationWorkflow(PostgresCorrelationLinkStore(sessions))
    )
