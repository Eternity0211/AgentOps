"""Concurrency-safe persistence for the content-free correlation ledger."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.domain import (
    CORRELATION_LINK_SCHEMA_VERSION,
    MAX_CORRELATION_LINKS,
    AuthorizationError,
    CausationId,
    CorrelationComponent,
    CorrelationEventId,
    CorrelationId,
    CorrelationLink,
    CorrelationTimeline,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    TraceId,
    correlation_link_fingerprint,
)

from .models import CorrelationLinkRow, CorrelationStreamRow, IncidentRow


def correlation_link_from_row(row: CorrelationLinkRow) -> CorrelationLink:
    """Hydrate and verify one immutable stored link."""
    link = CorrelationLink(
        event_id=CorrelationEventId(row.event_id),
        tenant_id=TenantId(row.tenant_id),
        incident_id=IncidentId(row.incident_id),
        component=CorrelationComponent(row.component),
        resource_id=OpaqueIdentifier(row.resource_id),
        trace_id=TraceId(row.trace_id),
        correlation_id=CorrelationId(row.correlation_id),
        causation_id=None if row.causation_id is None else CausationId(row.causation_id),
        occurred_at=row.occurred_at,
        schema_version=row.schema_version,
    )
    expected = correlation_link_fingerprint(link)
    if expected != Sha256Digest(row.fingerprint):
        raise InvalidDomainValueError("stored correlation link fingerprint mismatch")
    return link


class CorrelationLinkRepository:
    """Append and reconstruct one serialized tenant-scoped correlation stream."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, link: CorrelationLink) -> CorrelationLink:
        """Append exactly once, rejecting cross-Incident scope and broken causation."""
        incident_exists = await self._session.scalar(
            select(IncidentRow.id).where(
                IncidentRow.id == link.incident_id.value,
                IncidentRow.tenant_id == link.tenant_id.value,
            )
        )
        if incident_exists is None:
            raise AuthorizationError("Incident is not available in the requested tenant")

        await self._session.execute(
            pg_insert(CorrelationStreamRow)
            .values(
                tenant_id=link.tenant_id.value,
                correlation_id=link.correlation_id.value,
                incident_id=link.incident_id.value,
                schema_version=CORRELATION_LINK_SCHEMA_VERSION,
                created_at=link.occurred_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    CorrelationStreamRow.tenant_id,
                    CorrelationStreamRow.correlation_id,
                ]
            )
        )
        stream = await self._session.scalar(
            select(CorrelationStreamRow)
            .where(
                CorrelationStreamRow.tenant_id == link.tenant_id.value,
                CorrelationStreamRow.correlation_id == link.correlation_id.value,
            )
            .with_for_update()
        )
        if stream is None:
            raise InvalidDomainValueError("correlation stream claim was not persisted")
        if stream.incident_id != link.incident_id.value:
            raise InvalidDomainValueError("correlation ID is already bound to a different Incident")

        existing_event = await self._session.scalar(
            select(CorrelationLinkRow).where(CorrelationLinkRow.event_id == link.event_id.value)
        )
        if existing_event is not None:
            stored = correlation_link_from_row(existing_event)
            if correlation_link_fingerprint(stored) != correlation_link_fingerprint(link):
                raise InvalidDomainValueError(
                    "correlation event ID replayed with different immutable content"
                )
            return stored

        rows = (
            await self._session.scalars(
                select(CorrelationLinkRow)
                .where(
                    CorrelationLinkRow.tenant_id == link.tenant_id.value,
                    CorrelationLinkRow.correlation_id == link.correlation_id.value,
                )
                .order_by(CorrelationLinkRow.sequence)
            )
        ).all()
        if len(rows) >= MAX_CORRELATION_LINKS:
            raise InvalidDomainValueError("correlation stream reached its bounded link limit")
        prior = tuple(correlation_link_from_row(row) for row in rows)
        CorrelationTimeline((*prior, link))

        row = CorrelationLinkRow(
            event_id=link.event_id.value,
            tenant_id=link.tenant_id.value,
            incident_id=link.incident_id.value,
            component=link.component.value,
            resource_id=link.resource_id.value,
            trace_id=link.trace_id.value,
            correlation_id=link.correlation_id.value,
            causation_id=None if link.causation_id is None else link.causation_id.value,
            occurred_at=link.occurred_at,
            schema_version=link.schema_version,
            fingerprint=correlation_link_fingerprint(link).value,
        )
        self._session.add(row)
        await self._session.flush()
        return correlation_link_from_row(row)

    async def by_correlation(
        self,
        tenant_id: TenantId,
        incident_id: IncidentId,
        correlation_id: CorrelationId,
    ) -> CorrelationTimeline:
        """Reconstruct a fingerprint-verified stream without leaking another scope."""
        stream = await self._session.scalar(
            select(CorrelationStreamRow).where(
                CorrelationStreamRow.tenant_id == tenant_id.value,
                CorrelationStreamRow.correlation_id == correlation_id.value,
                CorrelationStreamRow.incident_id == incident_id.value,
            )
        )
        if stream is None:
            raise AuthorizationError("correlation stream is not available in the requested scope")
        rows = (
            await self._session.scalars(
                select(CorrelationLinkRow)
                .where(
                    CorrelationLinkRow.tenant_id == tenant_id.value,
                    CorrelationLinkRow.correlation_id == correlation_id.value,
                    CorrelationLinkRow.incident_id == incident_id.value,
                )
                .order_by(CorrelationLinkRow.sequence)
            )
        ).all()
        if not rows:
            raise InvalidDomainValueError("correlation stream has no immutable links")
        return CorrelationTimeline(tuple(correlation_link_from_row(row) for row in rows))

    async def count(self, tenant_id: TenantId, correlation_id: CorrelationId) -> int:
        """Return a bounded stream count for health and completeness checks."""
        value = await self._session.scalar(
            select(func.count())
            .select_from(CorrelationLinkRow)
            .where(
                CorrelationLinkRow.tenant_id == tenant_id.value,
                CorrelationLinkRow.correlation_id == correlation_id.value,
            )
        )
        return int(value or 0)


class PostgresCorrelationLinkStore:
    """Transaction-owning workflow adapter safe across long-lived Incident processing."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append(self, link: CorrelationLink) -> CorrelationLink:
        async with self._sessions.begin() as session:
            return await CorrelationLinkRepository(session).append(link)

    async def by_correlation(
        self,
        tenant_id: TenantId,
        incident_id: IncidentId,
        correlation_id: CorrelationId,
    ) -> CorrelationTimeline:
        async with self._sessions.begin() as session:
            return await CorrelationLinkRepository(session).by_correlation(
                tenant_id, incident_id, correlation_id
            )
