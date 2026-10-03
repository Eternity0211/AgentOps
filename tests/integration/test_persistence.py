"""PostgreSQL integration tests for migrations and operational repositories."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Alert,
    AlertDimension,
    AlertGroupId,
    AlertId,
    AlertTriageAction,
    CausationId,
    CorrelationId,
    EventMetadata,
    EventReason,
    Incident,
    IncidentChange,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    OptimisticVersionError,
    TenantId,
)
from agentops_incident_commander.infrastructure.persistence import (
    AlertGroupRow,
    AlertRepository,
    AlertRow,
    IncidentCancellationRequestRow,
    IncidentRepository,
    IncidentTransitionRow,
)

NOW = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    """Run the same major PostgreSQL image as the local control plane."""
    with PostgresContainer("postgres:18.6-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


def alembic_config(postgres_url: str) -> Config:
    """Build an explicit, credential-scoped migration configuration."""
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_url.replace("%", "%%"))
    return config


@pytest.fixture(scope="module")
def migrated_url(postgres_url: str) -> Iterator[str]:
    """Prove upgrade, full downgrade, and a clean second upgrade."""
    config = alembic_config(postgres_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield postgres_url
    command.downgrade(config, "base")


@pytest.fixture
async def engine(migrated_url: str) -> AsyncIterator[AsyncEngine]:
    """Provide a clean transactional engine and truncate between tests."""
    value = create_async_engine(migrated_url)
    yield value
    async with value.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE alerts, alert_groups, incident_cancellation_requests, "
                "incident_transitions, incidents RESTART IDENTITY CASCADE"
            )
        )
    await value.dispose()


def metadata(minute: int = 1) -> EventMetadata:
    return EventMetadata(
        actor_id=ActorId("operator-1"),
        reason=EventReason("integration transition"),
        correlation_id=CorrelationId("correlation-1"),
        causation_id=CausationId(f"command-{minute}"),
        occurred_at=NOW + timedelta(minutes=minute),
    )


def alert(alert_id: str, *, severity: IncidentSeverity = IncidentSeverity.SEV3) -> Alert:
    return Alert(
        id=AlertId(alert_id),
        tenant_id=TenantId("tenant-1"),
        environment="production",
        service="order-service",
        rule="http-errors",
        severity=severity,
        observed_at=NOW,
        received_at=NOW,
        dimensions=(AlertDimension("region", "cn-east-1"),),
    )


def group_ids() -> Callable[[], AlertGroupId]:
    sequence = count(1)
    return lambda: AlertGroupId(f"group-{next(sequence)}")


@pytest.mark.anyio
async def test_migration_created_expected_tables_and_constraints(engine: AsyncEngine) -> None:
    """The upgraded schema contains all initial operational tables."""
    async with engine.connect() as connection:
        names = set(
            (
                await connection.scalars(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' ORDER BY tablename"
                    )
                )
            ).all()
        )
    assert {
        "alembic_version",
        "alerts",
        "alert_groups",
        "incidents",
        "incident_transitions",
        "incident_cancellation_requests",
    } <= names


@pytest.mark.anyio
async def test_incident_repository_persists_transitions_cancellation_and_conflicts(
    engine: AsyncEngine,
) -> None:
    """Aggregate changes and records commit together while stale writers fail."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    opened = Incident.open(IncidentId("incident-1"), IncidentSeverity.SEV2, opened_at=NOW)
    async with sessions.begin() as session:
        await IncidentRepository(session).add(opened)

    async with sessions() as first_session, sessions() as stale_session:
        first = await IncidentRepository(first_session).get(opened.id)
        stale = await IncidentRepository(stale_session).get(opened.id)
        assert first == stale == opened
        assert await IncidentRepository(first_session).get(IncidentId("missing")) is None
        assert first is not None and stale is not None
        first_change = first.transition(
            IncidentState.TRIAGED,
            expected_version=AggregateVersion(1),
            metadata=metadata(),
        )
        await IncidentRepository(first_session).apply(first_change)
        await first_session.commit()

        stale_change = stale.transition(
            IncidentState.TRIAGED,
            expected_version=AggregateVersion(1),
            metadata=metadata(),
        )
        with pytest.raises(OptimisticVersionError, match="no longer has version"):
            await IncidentRepository(stale_session).apply(stale_change)
        await stale_session.rollback()

    async with sessions.begin() as session:
        repository = IncidentRepository(session)
        current = await repository.get(opened.id)
        assert current is not None
        cancelled = current.request_cancellation(
            expected_version=current.version, metadata=metadata(2)
        )
        await repository.apply(cancelled)

    async with sessions() as session:
        persisted = await IncidentRepository(session).get(opened.id)
        assert persisted is not None
        assert persisted.state is IncidentState.CANCELLED
        assert await session.scalar(select(func.count()).select_from(IncidentTransitionRow)) == 2
        assert (
            await session.scalar(select(func.count()).select_from(IncidentCancellationRequestRow))
            == 1
        )


@pytest.mark.anyio
async def test_incident_repository_rejects_change_without_record(engine: AsyncEngine) -> None:
    """Persistence cannot mutate an aggregate without an auditable domain record."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    incident = Incident.open(IncidentId("incident-empty"), IncidentSeverity.SEV4, opened_at=NOW)
    async with sessions.begin() as session:
        await IncidentRepository(session).add(incident)
    async with sessions() as session:
        with pytest.raises(InvalidDomainValueError, match="no auditable record"):
            await IncidentRepository(session).apply(IncidentChange(incident))


@pytest.mark.anyio
async def test_incident_repository_persists_deferred_cancellation(engine: AsyncEngine) -> None:
    """A mid-operation cancellation request persists without inventing a transition."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    executing = Incident(
        id=IncidentId("incident-executing"),
        severity=IncidentSeverity.SEV1,
        opened_at=NOW,
        updated_at=NOW,
        state=IncidentState.EXECUTING,
    )
    async with sessions.begin() as session:
        repository = IncidentRepository(session)
        await repository.add(executing)
        change = executing.request_cancellation(
            expected_version=AggregateVersion(1), metadata=metadata()
        )
        await repository.apply(change)

    async with sessions() as session:
        persisted = await IncidentRepository(session).get(executing.id)
        assert persisted is not None
        assert persisted.state is IncidentState.EXECUTING
        assert persisted.cancellation_requested_at == NOW + timedelta(minutes=1)
        assert await session.scalar(select(func.count()).select_from(IncidentTransitionRow)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(IncidentCancellationRequestRow))
            == 1
        )


@pytest.mark.anyio
async def test_alert_repository_serializes_concurrent_ingestion(engine: AsyncEngine) -> None:
    """Independent transactions produce one group with no lost Alert deliveries."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    factory = group_ids()

    async def ingest(item: Alert) -> AlertTriageAction:
        async with sessions.begin() as session:
            decision = await AlertRepository(
                session, window=timedelta(minutes=5), group_id_factory=factory
            ).ingest(item)
            return decision.action

    actions = await asyncio.gather(*(ingest(alert(f"alert-{index}")) for index in range(1, 17)))
    assert actions.count(AlertTriageAction.OPEN_GROUP) == 1
    assert actions.count(AlertTriageAction.MERGE_GROUP) == 15

    replay_actions = await asyncio.gather(*(ingest(alert("alert-1")) for _ in range(8)))
    assert replay_actions == [AlertTriageAction.DUPLICATE] * 8

    async with sessions() as session:
        group = await session.scalar(select(AlertGroupRow))
        assert group is not None
        assert group.occurrence_count == 16
        assert group.version == 16
        assert await session.scalar(select(func.count()).select_from(AlertRow)) == 16


@pytest.mark.anyio
async def test_alert_repository_opens_new_group_outside_window_and_escalates(
    engine: AsyncEngine,
) -> None:
    """Database-backed triage retains the pure-domain window and severity rules."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    factory = group_ids()
    async with sessions.begin() as session:
        repository = AlertRepository(session, window=timedelta(minutes=5), group_id_factory=factory)
        await repository.ingest(alert("alert-1"))
        critical = alert("alert-2", severity=IncidentSeverity.SEV1)
        await repository.ingest(critical)
        later = Alert(
            id=AlertId("alert-3"),
            tenant_id=critical.tenant_id,
            environment=critical.environment,
            service=critical.service,
            rule=critical.rule,
            severity=IncidentSeverity.SEV4,
            observed_at=NOW + timedelta(minutes=6),
            received_at=NOW + timedelta(minutes=6),
            dimensions=critical.dimensions,
        )
        decision = await repository.ingest(later)
        assert decision.action is AlertTriageAction.OPEN_GROUP

    async with sessions() as session:
        groups = (await session.scalars(select(AlertGroupRow).order_by(AlertGroupRow.id))).all()
        assert [group.severity for group in groups] == ["SEV1", "SEV4"]


@pytest.mark.anyio
async def test_alert_repository_rejects_invalid_window(engine: AsyncEngine) -> None:
    """Persistence uses the same positive-window invariant as the domain coordinator."""
    async with AsyncSession(engine) as session:
        with pytest.raises(InvalidDomainValueError, match="must be positive"):
            AlertRepository(session, window=timedelta(0), group_id_factory=group_ids())
