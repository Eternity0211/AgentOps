"""Defensive-path tests for the PostgreSQL correlation repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.domain import (
    MAX_CORRELATION_LINKS,
    AuthorizationError,
    CausationId,
    CorrelationComponent,
    CorrelationEventId,
    CorrelationId,
    CorrelationLink,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    TenantId,
    TraceId,
    correlation_link_fingerprint,
)
from agentops_incident_commander.infrastructure.persistence import (
    CorrelationLinkRepository,
    CorrelationLinkRow,
    CorrelationStreamRow,
    PostgresCorrelationLinkStore,
    correlation_link_from_row,
)

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)


def link(index: int = 1, *, cause: int | None = None) -> CorrelationLink:
    return CorrelationLink(
        event_id=CorrelationEventId(f"event-{index}"),
        tenant_id=TenantId("tenant-1"),
        incident_id=IncidentId("incident-1"),
        component=(CorrelationComponent.ALERT if index == 1 else CorrelationComponent.INCIDENT),
        resource_id=OpaqueIdentifier(f"resource-{index}"),
        trace_id=TraceId(f"{index:032x}"),
        correlation_id=CorrelationId("correlation-1"),
        causation_id=None if cause is None else CausationId(f"event-{cause}"),
        occurred_at=NOW + timedelta(seconds=index),
    )


def row(item: CorrelationLink) -> CorrelationLinkRow:
    return CorrelationLinkRow(
        event_id=item.event_id.value,
        tenant_id=item.tenant_id.value,
        incident_id=item.incident_id.value,
        component=item.component.value,
        resource_id=item.resource_id.value,
        trace_id=item.trace_id.value,
        correlation_id=item.correlation_id.value,
        causation_id=None if item.causation_id is None else item.causation_id.value,
        occurred_at=item.occurred_at,
        schema_version=item.schema_version,
        fingerprint=correlation_link_fingerprint(item).value,
    )


def stream(*, incident_id: str = "incident-1") -> CorrelationStreamRow:
    return CorrelationStreamRow(
        tenant_id="tenant-1",
        correlation_id="correlation-1",
        incident_id=incident_id,
        schema_version="1.0.0",
        created_at=NOW,
    )


def session_with(
    *, scalar_values: list[object], scalar_lists: list[list[object]] | None = None
) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = scalar_values
    lists = scalar_lists or []
    session.scalars.side_effect = [
        SimpleNamespace(all=lambda values=values: values) for values in lists
    ]
    session.add = Mock()
    return session


class SessionContext:
    def __init__(self, session: AsyncMock) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


class SessionFactory:
    def __init__(self, *sessions: AsyncMock) -> None:
        self.sessions = iter(sessions)

    def begin(self) -> SessionContext:
        return SessionContext(next(self.sessions))


def test_row_hydration_handles_parent_and_detects_tamper() -> None:
    root = link()
    child = link(2, cause=1)

    assert correlation_link_from_row(row(root)) == root
    assert correlation_link_from_row(row(child)) == child
    corrupt = row(root)
    corrupt.fingerprint = "a" * 64
    with pytest.raises(InvalidDomainValueError, match="fingerprint mismatch"):
        correlation_link_from_row(corrupt)


@pytest.mark.anyio
async def test_append_rejects_missing_incident_stream_and_scope() -> None:
    with pytest.raises(AuthorizationError, match="requested tenant"):
        await CorrelationLinkRepository(
            cast(AsyncSession, session_with(scalar_values=[None]))
        ).append(link())

    with pytest.raises(InvalidDomainValueError, match="claim was not persisted"):
        await CorrelationLinkRepository(
            cast(AsyncSession, session_with(scalar_values=["incident-1", None]))
        ).append(link())

    with pytest.raises(InvalidDomainValueError, match="different Incident"):
        await CorrelationLinkRepository(
            cast(
                AsyncSession,
                session_with(scalar_values=["incident-1", stream(incident_id="incident-2")]),
            )
        ).append(link())


@pytest.mark.anyio
async def test_append_replays_exact_event_and_rejects_changed_content() -> None:
    item = link()
    stored_row = row(item)
    exact_session = session_with(scalar_values=["incident-1", stream(), stored_row])

    assert await CorrelationLinkRepository(cast(AsyncSession, exact_session)).append(item) == item

    changed = replace(item, trace_id=TraceId("f" * 32))
    changed_session = session_with(scalar_values=["incident-1", stream(), stored_row])
    with pytest.raises(InvalidDomainValueError, match="different immutable content"):
        await CorrelationLinkRepository(cast(AsyncSession, changed_session)).append(changed)


@pytest.mark.anyio
async def test_append_new_link_and_enforce_bounded_stream() -> None:
    root = link()
    root_session = session_with(scalar_values=["incident-1", stream(), None], scalar_lists=[[]])
    repository = CorrelationLinkRepository(cast(AsyncSession, root_session))

    assert await repository.append(root) == root
    root_session.add.assert_called_once()
    root_session.flush.assert_awaited_once()

    full_session = session_with(
        scalar_values=["incident-1", stream(), None],
        scalar_lists=[[object()] * MAX_CORRELATION_LINKS],
    )
    with pytest.raises(InvalidDomainValueError, match="bounded link limit"):
        await CorrelationLinkRepository(cast(AsyncSession, full_session)).append(root)


@pytest.mark.anyio
async def test_scoped_read_rejects_missing_or_empty_stream_and_returns_timeline() -> None:
    item = link()
    with pytest.raises(AuthorizationError, match="requested scope"):
        await CorrelationLinkRepository(
            cast(AsyncSession, session_with(scalar_values=[None]))
        ).by_correlation(item.tenant_id, item.incident_id, item.correlation_id)

    with pytest.raises(InvalidDomainValueError, match="no immutable links"):
        await CorrelationLinkRepository(
            cast(
                AsyncSession,
                session_with(scalar_values=[stream()], scalar_lists=[[]]),
            )
        ).by_correlation(item.tenant_id, item.incident_id, item.correlation_id)

    loaded = await CorrelationLinkRepository(
        cast(
            AsyncSession,
            session_with(scalar_values=[stream()], scalar_lists=[[row(item)]]),
        )
    ).by_correlation(item.tenant_id, item.incident_id, item.correlation_id)
    assert loaded.links == (item,)


@pytest.mark.anyio
async def test_count_normalizes_database_scalar() -> None:
    repository = CorrelationLinkRepository(
        cast(AsyncSession, session_with(scalar_values=[3, None]))
    )

    assert await repository.count(TenantId("tenant-1"), CorrelationId("correlation-1")) == 3
    assert await repository.count(TenantId("tenant-1"), CorrelationId("correlation-1")) == 0


@pytest.mark.anyio
async def test_transaction_owning_store_appends_and_reads_across_sessions() -> None:
    item = link()
    append_session = session_with(scalar_values=["incident-1", stream(), None], scalar_lists=[[]])
    read_session = session_with(scalar_values=[stream()], scalar_lists=[[row(item)]])
    store = PostgresCorrelationLinkStore(cast(Any, SessionFactory(append_session, read_session)))

    assert await store.append(item) == item
    assert (
        await store.by_correlation(item.tenant_id, item.incident_id, item.correlation_id)
    ).links == (item,)
