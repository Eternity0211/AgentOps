"""PostgreSQL integration tests for migrations and operational repositories."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from itertools import count, pairwise

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from agentops_incident_commander.apps.api import create_app
from agentops_incident_commander.apps.config import ApiSettings
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Alert,
    AlertDimension,
    AlertGroupId,
    AlertId,
    AlertTriageAction,
    AuditEvent,
    AuditEventId,
    AuditTarget,
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
    Job,
    JobFailureRoute,
    JobId,
    JobLeaseError,
    JobStatus,
    OpaqueIdentifier,
    OptimisticVersionError,
    OutboxEvent,
    OutboxEventId,
    OutboxLeaseError,
    OutboxPayload,
    Principal,
    Role,
    Sha256Digest,
    TenantId,
)
from agentops_incident_commander.infrastructure.persistence import (
    AlertGroupRow,
    AlertRepository,
    AlertRow,
    AuditEventRow,
    AuditRepository,
    IdempotencyRecordRow,
    IncidentCancellationRequestRow,
    IncidentMemoryEmbeddingRow,
    IncidentRepository,
    IncidentTransitionRow,
    JobRepository,
    JobRow,
    OutboxEventRow,
    OutboxRepository,
)

NOW = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    """Run the same major PostgreSQL image as the local control plane."""
    with PostgresContainer("pgvector/pgvector:0.8.6-pg18", driver="asyncpg") as postgres:
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
                "incident_transitions, idempotency_records, outbox_events, jobs, "
                "incidents RESTART IDENTITY CASCADE"
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


def audit_event(event_id: str, correlation_id: str = "audit-correlation") -> AuditEvent:
    return AuditEvent(
        id=AuditEventId(event_id),
        tenant_id=TenantId("tenant-1"),
        type="incident.transitioned",
        event_version=1,
        payload_schema_version="incident/v1",
        actor_id=ActorId("operator-1"),
        correlation_id=CorrelationId(correlation_id),
        causation_id=CausationId(f"command-{event_id}"),
        target=AuditTarget("incident.record", IncidentId("incident-1")),
        occurred_at=NOW,
        request_hash=Sha256Digest("a" * 64),
        result_hash=Sha256Digest("b" * 64),
    )


def outbox_event(
    event_id: str,
    *,
    aggregate_id: str | None = None,
    aggregate_version: int = 1,
    max_attempts: int = 3,
) -> OutboxEvent:
    return OutboxEvent(
        id=OutboxEventId(event_id),
        topic="incident.transitioned",
        schema_version="incident/v1",
        aggregate_type="incident.record",
        aggregate_id=IncidentId(aggregate_id or f"incident-{event_id}"),
        aggregate_version=aggregate_version,
        correlation_id=CorrelationId(f"correlation-{event_id}"),
        causation_id=CausationId(f"command-{event_id}"),
        payload=OutboxPayload.from_mapping({"event_id": event_id}),
        occurred_at=NOW,
        available_at=NOW,
        max_attempts=max_attempts,
    )


def job(
    job_id: str,
    *,
    priority: int = 50,
    max_attempts: int = 3,
    failure_route: JobFailureRoute = JobFailureRoute.DEAD_LETTER,
) -> Job:
    return Job(
        id=JobId(job_id),
        type="workflow.investigate",
        schema_version="workflow/v1",
        payload_ref=OpaqueIdentifier(f"payload-{job_id}"),
        correlation_id=CorrelationId(f"correlation-{job_id}"),
        causation_id=CausationId(f"command-{job_id}"),
        priority=priority,
        created_at=NOW,
        available_at=NOW,
        max_attempts=max_attempts,
        failure_route=failure_route,
    )


def api_app(
    engine: AsyncEngine,
    principal: Principal | None,
    *,
    now: datetime = NOW + timedelta(hours=1),
    audit_id: str = "api-audit-1",
) -> FastAPI:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    audit_ids = count(1)

    async def resolve(_: Request) -> Principal | None:
        return principal

    return create_app(
        ApiSettings("postgresql+asyncpg://unused:unused@localhost/unused", "127.0.0.1", 8000),
        session_factory=sessions,
        principal_resolver=resolve,
        clock=lambda: now,
        id_factory=lambda: f"{audit_id}-{next(audit_ids)}",
    )


def principal(
    *,
    tenant: str = "tenant-api",
    actor: str = "operator-api",
    roles: frozenset[Role] = frozenset({Role.OPERATOR}),
) -> Principal:
    return Principal(ActorId(actor), TenantId(tenant), roles)


async def add_incident(
    engine: AsyncEngine,
    incident_id: str,
    *,
    tenant: str = "tenant-api",
    state: IncidentState = IncidentState.TRIAGED,
    opened_at: datetime = NOW,
) -> Incident:
    item = Incident(
        id=IncidentId(incident_id),
        tenant_id=TenantId(tenant),
        severity=IncidentSeverity.SEV2,
        opened_at=opened_at,
        updated_at=opened_at,
        state=state,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        await IncidentRepository(session).add(item)
    return item


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
        "audit_events",
        "incidents",
        "incident_transitions",
        "incident_cancellation_requests",
        "incident_memory_embeddings",
        "idempotency_records",
        "jobs",
        "outbox_events",
    } <= names
    async with engine.connect() as connection:
        assert await connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        )


@pytest.mark.anyio
async def test_api_fails_closed_without_identity_and_denies_viewer_control(
    engine: AsyncEngine,
) -> None:
    item = await add_incident(engine, "incident-auth")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    unauthenticated = create_app(
        ApiSettings("postgresql+asyncpg://unused:unused@localhost/unused", "127.0.0.1", 8000),
        session_factory=sessions,
    )
    async with AsyncClient(
        transport=ASGITransport(app=unauthenticated), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/incidents")
    assert response.status_code == 401

    viewer_app = api_app(engine, principal(roles=frozenset({Role.VIEWER})))
    async with AsyncClient(
        transport=ASGITransport(app=viewer_app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/incidents/{item.id.value}/controls/start-investigation",
            headers={"Idempotency-Key": "viewer-denied"},
            json={
                "expected_version": 1,
                "reason": "not permitted",
                "correlation_id": "correlation-viewer",
                "causation_id": "command-viewer",
            },
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "principal lacks permission investigation:start"}


@pytest.mark.anyio
async def test_incident_read_endpoints_are_tenant_scoped_and_cursor_paginated(
    engine: AsyncEngine,
) -> None:
    first = await add_incident(engine, "incident-page-a", opened_at=NOW + timedelta(minutes=2))
    second = await add_incident(engine, "incident-page-b", opened_at=NOW + timedelta(minutes=1))
    await add_incident(engine, "incident-foreign", tenant="tenant-foreign")
    app = api_app(engine, principal(roles=frozenset({Role.VIEWER})))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page_one = await client.get("/api/v1/incidents", params={"limit": 1})
        cursor = page_one.json()["next_cursor"]
        page_two = await client.get("/api/v1/incidents", params={"limit": 1, "cursor": cursor})
        own = await client.get(f"/api/v1/incidents/{second.id.value}")
        foreign = await client.get("/api/v1/incidents/incident-foreign")
        malformed = await client.get("/api/v1/incidents", params={"cursor": "%%%"})
        wrong_shape = await client.get("/api/v1/incidents", params={"cursor": "WzFd"})
        wrong_types = await client.get("/api/v1/incidents", params={"cursor": "WzEsMl0"})
        bad_time = await client.get(
            "/api/v1/incidents", params={"cursor": "WyJub3QtYS10aW1lIiwiaWQiXQ"}
        )

    assert page_one.status_code == page_two.status_code == 200
    assert page_one.json()["items"][0]["id"] == first.id.value
    assert page_two.json()["items"][0]["id"] == second.id.value
    assert page_two.json()["next_cursor"] is None
    assert own.status_code == 200
    assert foreign.status_code == 404
    assert {
        malformed.status_code,
        wrong_shape.status_code,
        wrong_types.status_code,
        bad_time.status_code,
    } == {400}


@pytest.mark.anyio
async def test_timeline_paginates_transition_and_cancellation_records_without_skips(
    engine: AsyncEngine,
) -> None:
    opened = await add_incident(engine, "incident-timeline", state=IncidentState.DETECTED)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        repository = IncidentRepository(session)
        triaged = opened.transition(
            IncidentState.TRIAGED,
            expected_version=AggregateVersion(1),
            metadata=metadata(),
        )
        await repository.apply(triaged)
        cancelled = triaged.incident.request_cancellation(
            expected_version=AggregateVersion(2), metadata=metadata(2)
        )
        await repository.apply(cancelled)

    app = api_app(engine, principal(roles=frozenset({Role.VIEWER})))
    kinds: list[str] = []
    cursor: str | None = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        while True:
            params: dict[str, str | int] = {"limit": 1}
            if cursor is not None:
                params["cursor"] = cursor
            response = await client.get(
                "/api/v1/incidents/incident-timeline/timeline", params=params
            )
            assert response.status_code == 200
            kinds.append(response.json()["items"][0]["kind"])
            cursor = response.json()["next_cursor"]
            if cursor is None:
                break
        missing = await client.get("/api/v1/incidents/missing/timeline")
        bad_cursor = await client.get(
            "/api/v1/incidents/incident-timeline/timeline", params={"cursor": "WzEsMl0"}
        )

    assert kinds == ["transition", "cancellation_request", "transition"]
    assert missing.status_code == 404
    assert bad_cursor.status_code == 400


@pytest.mark.anyio
async def test_control_commands_are_atomic_audited_and_idempotent(engine: AsyncEngine) -> None:
    await add_incident(engine, "incident-control")
    operator = principal()
    app = api_app(engine, operator)
    command_body = {
        "expected_version": 1,
        "reason": "begin bounded diagnosis",
        "correlation_id": "correlation-control",
        "causation_id": "command-control",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/v1/incidents/incident-control/controls/start-investigation",
            headers={"Idempotency-Key": "control-key"},
            json=command_body,
        )
        replay = await client.post(
            "/api/v1/incidents/incident-control/controls/start-investigation",
            headers={"Idempotency-Key": "control-key"},
            json=command_body,
        )
        conflict = await client.post(
            "/api/v1/incidents/incident-control/controls/start-investigation",
            headers={"Idempotency-Key": "control-key"},
            json={**command_body, "reason": "different command"},
        )

    assert first.status_code == replay.status_code == 200
    assert first.headers["Idempotency-Replayed"] == "false"
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert first.json() == replay.json()
    assert first.json()["incident"]["state"] == IncidentState.INVESTIGATING.value
    assert conflict.status_code == 409

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(IdempotencyRecordRow)) == 1
        assert await session.scalar(select(func.count()).select_from(IncidentTransitionRow)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEventRow)
                .where(AuditEventRow.tenant_id == operator.tenant_id.value)
            )
            == 1
        )


@pytest.mark.anyio
async def test_cancel_control_and_audit_pages_are_tenant_scoped(engine: AsyncEngine) -> None:
    await add_incident(
        engine,
        "incident-cancel",
        tenant="tenant-cancel-owner",
        state=IncidentState.DETECTED,
    )
    await add_incident(
        engine,
        "incident-cancel-two",
        tenant="tenant-cancel-owner",
        state=IncidentState.DETECTED,
    )
    operator = principal(tenant="tenant-cancel", actor="operator-cancel")
    # The incident belongs to another tenant, proving a cross-tenant 404 first.
    foreign_app = api_app(engine, operator, audit_id="api-audit-foreign")
    body = {
        "expected_version": 1,
        "reason": "stop investigation",
        "correlation_id": "correlation-cancel",
        "causation_id": "command-cancel",
    }
    async with AsyncClient(
        transport=ASGITransport(app=foreign_app), base_url="http://test"
    ) as client:
        hidden = await client.post(
            "/api/v1/incidents/incident-cancel/controls/cancel",
            headers={"Idempotency-Key": "cancel-hidden"},
            json=body,
        )
    assert hidden.status_code == 404

    owner = principal(tenant="tenant-cancel-owner")
    app = api_app(engine, owner, audit_id="api-audit-cancel")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cancelled = await client.post(
            "/api/v1/incidents/incident-cancel/controls/cancel",
            headers={"Idempotency-Key": "cancel-owner"},
            json=body,
        )
        cancelled_two = await client.post(
            "/api/v1/incidents/incident-cancel-two/controls/cancel",
            headers={"Idempotency-Key": "cancel-owner-two"},
            json={
                **body,
                "correlation_id": "correlation-cancel-two",
                "causation_id": "command-cancel-two",
            },
        )
        audit_first = await client.get("/api/v1/audit", params={"limit": 1})
        audit_second = await client.get(
            "/api/v1/audit",
            params={"limit": 100, "after_sequence": audit_first.json()["next_after_sequence"]},
        )

    assert cancelled.status_code == 200
    assert cancelled_two.status_code == 200
    assert cancelled.json()["cancellation_disposition"] == "CANCELLED"
    assert cancelled.json()["incident"]["state"] == IncidentState.CANCELLED.value
    assert audit_first.status_code == audit_second.status_code == 200
    assert {item["target_id"] for item in audit_second.json()["items"]} == {"incident-cancel-two"}


@pytest.mark.anyio
async def test_control_conflicts_invalid_values_and_incomplete_replay_fail_closed(
    engine: AsyncEngine,
) -> None:
    await add_incident(engine, "incident-detected", state=IncidentState.DETECTED)
    await add_incident(engine, "incident-stale")
    app = api_app(engine, principal(), audit_id="api-audit-errors")
    base = {
        "expected_version": 1,
        "reason": "controlled action",
        "correlation_id": "correlation-errors",
        "causation_id": "command-errors",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        illegal = await client.post(
            "/api/v1/incidents/incident-detected/controls/start-investigation",
            headers={"Idempotency-Key": "illegal-state"},
            json=base,
        )
        stale = await client.post(
            "/api/v1/incidents/incident-stale/controls/start-investigation",
            headers={"Idempotency-Key": "stale-version"},
            json={**base, "expected_version": 2},
        )
        invalid_id = await client.post(
            "/api/v1/incidents/bad%20id/controls/cancel",
            headers={"Idempotency-Key": "invalid-id"},
            json=base,
        )
        invalid_header = await client.post(
            "/api/v1/incidents/incident-stale/controls/cancel",
            headers={"Idempotency-Key": "bad key"},
            json=base,
        )

    assert illegal.status_code == stale.status_code == 409
    assert invalid_id.status_code == 422
    assert invalid_header.status_code == 422

    request_hash = hashlib.sha256(
        json.dumps(
            {
                "operation": "cancel",
                "incident_id": "incident-stale",
                "command": base,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(
            IdempotencyRecordRow(
                tenant_id="tenant-api",
                actor_id="operator-api",
                operation="incident:cancel:incident-stale",
                idempotency_key="incomplete",
                request_hash=request_hash,
                created_at=NOW,
            )
        )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="has no response"):
            await client.post(
                "/api/v1/incidents/incident-stale/controls/cancel",
                headers={"Idempotency-Key": "incomplete"},
                json=base,
            )


@pytest.mark.anyio
async def test_audit_repository_appends_and_reads_correlation_timeline(
    engine: AsyncEngine,
) -> None:
    """The repository exposes only append and sequence-ordered correlation reads."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        repository = AuditRepository(session)
        first = await repository.append(audit_event("audit-read-1"))
        second = await repository.append(audit_event("audit-read-2"))
        await repository.append(audit_event("audit-other", "other-correlation"))

    assert first.sequence < second.sequence
    async with sessions() as session:
        timeline = await AuditRepository(session).by_correlation(CorrelationId("audit-correlation"))

    assert [stored.event.id for stored in timeline] == [
        AuditEventId("audit-read-1"),
        AuditEventId("audit-read-2"),
    ]
    assert timeline[0].event.request_hash == Sha256Digest("a" * 64)
    assert timeline[0].event.result_hash == Sha256Digest("b" * 64)


@pytest.mark.anyio
async def test_audit_sequence_is_unique_under_concurrent_appends(engine: AsyncEngine) -> None:
    """Independent writers receive one globally unique monotonically ordered sequence."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def append(index: int) -> int:
        async with sessions.begin() as session:
            stored = await AuditRepository(session).append(
                audit_event(f"audit-concurrent-{index}", "concurrent-correlation")
            )
            return stored.sequence

    sequences = await asyncio.gather(*(append(index) for index in range(16)))
    ordered = sorted(sequences)
    assert len(set(ordered)) == 16
    assert all(later > earlier for earlier, later in pairwise(ordered))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET actor_id = 'attacker' WHERE id = 'audit-protected'",
        "DELETE FROM audit_events WHERE id = 'audit-protected'",
        "TRUNCATE audit_events",
    ],
)
async def test_audit_ledger_rejects_all_mutation_paths(engine: AsyncEngine, statement: str) -> None:
    """Database triggers protect history even from the table-owning connection."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        existing = await session.scalar(
            select(AuditEventRow).where(AuditEventRow.id == "audit-protected")
        )
        if existing is None:
            await AuditRepository(session).append(audit_event("audit-protected"))

    async with sessions.begin() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text(statement))


@pytest.mark.anyio
async def test_audit_database_constraints_reject_invalid_raw_hash(engine: AsyncEngine) -> None:
    """Direct inserts cannot bypass the canonical digest rule."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(
            AuditEventRow(
                id="audit-invalid-hash",
                tenant_id="tenant-1",
                event_type="incident.transitioned",
                event_version=1,
                payload_schema_version="incident/v1",
                actor_id="operator-1",
                correlation_id="audit-invalid-correlation",
                causation_id="command-invalid",
                target_type="incident.record",
                target_id="incident-1",
                request_hash="A" * 64,
                result_hash=None,
                occurred_at=NOW,
            )
        )
        with pytest.raises(IntegrityError, match="ck_audit_request_hash"):
            await session.flush()


@pytest.mark.anyio
async def test_outbox_and_aggregate_commit_or_rollback_together(engine: AsyncEngine) -> None:
    """Aggregate state never commits without its required cross-process event intent."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    incident = Incident.open(
        IncidentId("incident-atomic"),
        TenantId("tenant-1"),
        IncidentSeverity.SEV2,
        opened_at=NOW,
    )

    with pytest.raises(RuntimeError, match="abort transaction"):
        async with sessions.begin() as session:
            await IncidentRepository(session).add(incident)
            await OutboxRepository(session).enqueue(
                outbox_event("outbox-rollback", aggregate_id=incident.id.value)
            )
            raise RuntimeError("abort transaction")

    async with sessions() as session:
        assert await IncidentRepository(session).get(incident.id) is None
        assert await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 0

    async with sessions.begin() as session:
        await IncidentRepository(session).add(incident)
        sequence = await OutboxRepository(session).enqueue(
            outbox_event("outbox-commit", aggregate_id=incident.id.value)
        )
    assert sequence > 0


@pytest.mark.anyio
async def test_outbox_rejects_duplicate_aggregate_intent(engine: AsyncEngine) -> None:
    """A retry with a new message ID cannot duplicate the same aggregate event intent."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        await OutboxRepository(session).enqueue(
            outbox_event("outbox-original", aggregate_id="incident-dedupe", aggregate_version=7)
        )

    with pytest.raises(IntegrityError, match="uq_outbox_aggregate_intent"):
        async with sessions.begin() as session:
            await OutboxRepository(session).enqueue(
                outbox_event("outbox-retry", aggregate_id="incident-dedupe", aggregate_version=7)
            )


@pytest.mark.anyio
async def test_outbox_concurrent_claims_are_disjoint(engine: AsyncEngine) -> None:
    """SKIP LOCKED assigns each available event to at most one concurrent dispatcher."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        repository = OutboxRepository(session)
        for index in range(16):
            await repository.enqueue(outbox_event(f"outbox-concurrent-{index}"))

    async def claim(worker: str) -> tuple[OutboxEventId, ...]:
        async with sessions.begin() as session:
            claimed = await OutboxRepository(session).claim(
                OpaqueIdentifier(worker), now=NOW, lease_duration=timedelta(minutes=1), limit=10
            )
            return tuple(item.event.id for item in claimed)

    first, second = await asyncio.gather(claim("worker-1"), claim("worker-2"))
    assert len(first) + len(second) == 16
    assert set(first).isdisjoint(second)


@pytest.mark.anyio
async def test_outbox_reclaims_stale_lease_and_publishes_once(engine: AsyncEngine) -> None:
    """A crashed worker's expired lease is reclaimed and only its successor can acknowledge."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    event = outbox_event("outbox-stale")
    async with sessions.begin() as session:
        await OutboxRepository(session).enqueue(event)
        first = await OutboxRepository(session).claim(
            OpaqueIdentifier("worker-old"),
            now=NOW,
            lease_duration=timedelta(minutes=1),
            limit=1,
        )
    assert first[0].attempt == 1

    takeover_time = NOW + timedelta(minutes=2)
    async with sessions.begin() as session:
        second = await OutboxRepository(session).claim(
            OpaqueIdentifier("worker-new"),
            now=takeover_time,
            lease_duration=timedelta(minutes=1),
            limit=1,
        )
    assert second[0].attempt == 2

    async with sessions.begin() as session:
        with pytest.raises(OutboxLeaseError, match="no active lease"):
            await OutboxRepository(session).mark_published(
                event.id, OpaqueIdentifier("worker-old"), published_at=takeover_time
            )
        await OutboxRepository(session).mark_published(
            event.id,
            OpaqueIdentifier("worker-new"),
            published_at=takeover_time + timedelta(seconds=1),
        )

    async with sessions.begin() as session:
        assert not await OutboxRepository(session).claim(
            OpaqueIdentifier("worker-third"),
            now=takeover_time + timedelta(minutes=2),
            lease_duration=timedelta(minutes=1),
            limit=1,
        )


@pytest.mark.anyio
async def test_outbox_failure_retries_then_dead_letters(engine: AsyncEngine) -> None:
    """Failures are delayed and bounded; exhaustion stops automatic publication attempts."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    event = outbox_event("outbox-failure", max_attempts=2)
    worker = OpaqueIdentifier("worker-failure")
    async with sessions.begin() as session:
        repository = OutboxRepository(session)
        await repository.enqueue(event)
        await repository.claim(worker, now=NOW, lease_duration=timedelta(minutes=1), limit=1)
        await repository.mark_failed(
            event.id,
            worker,
            failed_at=NOW + timedelta(seconds=1),
            retry_at=NOW + timedelta(minutes=2),
            error=" broker unavailable ",
        )

    async with sessions.begin() as session:
        repository = OutboxRepository(session)
        assert not await repository.claim(
            worker,
            now=NOW + timedelta(minutes=1),
            lease_duration=timedelta(minutes=1),
            limit=1,
        )
        retry = await repository.claim(
            worker,
            now=NOW + timedelta(minutes=2),
            lease_duration=timedelta(minutes=1),
            limit=1,
        )
        assert retry[0].attempt == 2
        await repository.mark_failed(
            event.id,
            worker,
            failed_at=NOW + timedelta(minutes=2, seconds=1),
            retry_at=NOW + timedelta(minutes=4),
            error="still unavailable",
        )

    async with sessions() as session:
        row = await session.scalar(
            select(OutboxEventRow).where(OutboxEventRow.id == event.id.value)
        )
        assert row is not None
        assert row.dead_lettered_at == NOW + timedelta(minutes=2, seconds=1)
        assert row.last_error == "still unavailable"


@pytest.mark.anyio
async def test_job_claims_are_priority_ordered_and_concurrently_disjoint(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        repository = JobRepository(session)
        for index in range(16):
            await repository.enqueue(job(f"job-concurrent-{index}", priority=index))

    async def claim(worker_id: str) -> tuple[JobId, ...]:
        async with sessions.begin() as session:
            leases = await JobRepository(session).claim(
                OpaqueIdentifier(worker_id),
                now=NOW,
                lease_duration=timedelta(minutes=1),
                limit=10,
            )
            return tuple(lease.job.id for lease in leases)

    first, second = await asyncio.gather(claim("worker-a"), claim("worker-b"))
    assert len(first) + len(second) == 16
    assert set(first).isdisjoint(second)


@pytest.mark.anyio
async def test_job_heartbeat_completion_and_foreign_worker_refusal(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    item = job("job-complete")
    owner = OpaqueIdentifier("worker-owner")
    async with sessions.begin() as session:
        repository = JobRepository(session)
        await repository.enqueue(item)
        lease = (
            await repository.claim(owner, now=NOW, lease_duration=timedelta(minutes=1), limit=1)
        )[0]
        assert lease.attempt == 1
        renewed = await repository.heartbeat(
            item.id,
            owner,
            now=NOW + timedelta(seconds=30),
            lease_duration=timedelta(minutes=1),
        )
        assert renewed.expires_at == NOW + timedelta(minutes=1, seconds=30)
        with pytest.raises(JobLeaseError, match="no active lease"):
            await repository.complete(
                item.id,
                OpaqueIdentifier("worker-foreign"),
                completed_at=NOW + timedelta(seconds=31),
            )
        await repository.complete(item.id, owner, completed_at=NOW + timedelta(seconds=31))

    async with sessions() as session:
        row = await session.scalar(select(JobRow).where(JobRow.id == item.id.value))
        assert row is not None
        assert row.status == JobStatus.COMPLETED.value


@pytest.mark.anyio
async def test_job_duplicate_id_is_rejected_and_stale_lease_is_reclaimed(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    item = job("job-reclaim", max_attempts=2)
    async with sessions.begin() as session:
        repository = JobRepository(session)
        await repository.enqueue(item)
        await repository.claim(
            OpaqueIdentifier("worker-crashed"),
            now=NOW,
            lease_duration=timedelta(minutes=1),
            limit=1,
        )

    with pytest.raises(IntegrityError, match="jobs_id_key"):
        async with sessions.begin() as session:
            await JobRepository(session).enqueue(item)

    async with sessions.begin() as session:
        reclaimed = await JobRepository(session).claim(
            OpaqueIdentifier("worker-recovery"),
            now=NOW + timedelta(minutes=2),
            lease_duration=timedelta(minutes=1),
            limit=1,
        )
        assert reclaimed[0].attempt == 2
        assert reclaimed[0].worker_id == OpaqueIdentifier("worker-recovery")


@pytest.mark.anyio
async def test_job_failure_retries_then_routes_to_human(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    item = job("job-human", max_attempts=2, failure_route=JobFailureRoute.NEEDS_HUMAN)
    owner = OpaqueIdentifier("worker-human")
    async with sessions.begin() as session:
        repository = JobRepository(session)
        await repository.enqueue(item)
        await repository.claim(owner, now=NOW, lease_duration=timedelta(minutes=1), limit=1)
        assert (
            await repository.fail(
                item.id,
                owner,
                failed_at=NOW + timedelta(seconds=1),
                retry_at=NOW + timedelta(minutes=2),
                error="transient",
            )
            is JobStatus.PENDING
        )

    async with sessions.begin() as session:
        repository = JobRepository(session)
        assert not await repository.claim(
            owner,
            now=NOW + timedelta(minutes=1),
            lease_duration=timedelta(minutes=1),
            limit=1,
        )
        await repository.claim(
            owner,
            now=NOW + timedelta(minutes=2),
            lease_duration=timedelta(minutes=1),
            limit=1,
        )
        assert (
            await repository.fail(
                item.id,
                owner,
                failed_at=NOW + timedelta(minutes=2, seconds=1),
                retry_at=NOW + timedelta(minutes=3),
                error="exhausted",
            )
            is JobStatus.NEEDS_HUMAN
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("route", "expected"),
    [
        (JobFailureRoute.DEAD_LETTER, JobStatus.DEAD_LETTER),
        (JobFailureRoute.NEEDS_HUMAN, JobStatus.NEEDS_HUMAN),
    ],
)
async def test_job_expired_final_lease_routes_terminally(
    engine: AsyncEngine, route: JobFailureRoute, expected: JobStatus
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    item = job(f"job-stale-{route.value.lower()}", max_attempts=1, failure_route=route)
    async with sessions.begin() as session:
        repository = JobRepository(session)
        await repository.enqueue(item)
        await repository.claim(
            OpaqueIdentifier("worker-crashed"),
            now=NOW,
            lease_duration=timedelta(minutes=1),
            limit=1,
        )

    async with sessions.begin() as session:
        assert not await JobRepository(session).claim(
            OpaqueIdentifier("worker-recovery"),
            now=NOW + timedelta(minutes=2),
            lease_duration=timedelta(minutes=1),
            limit=1,
        )
    async with sessions() as session:
        row = await session.scalar(select(JobRow).where(JobRow.id == item.id.value))
        assert row is not None
        assert row.status == expected.value
        assert row.last_error == "lease expired after final attempt"


@pytest.mark.anyio
async def test_incident_repository_persists_transitions_cancellation_and_conflicts(
    engine: AsyncEngine,
) -> None:
    """Aggregate changes and records commit together while stale writers fail."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    opened = Incident.open(
        IncidentId("incident-1"), TenantId("tenant-1"), IncidentSeverity.SEV2, opened_at=NOW
    )
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
    incident = Incident.open(
        IncidentId("incident-empty"),
        TenantId("tenant-1"),
        IncidentSeverity.SEV4,
        opened_at=NOW,
    )
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
        tenant_id=TenantId("tenant-1"),
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


@pytest.mark.anyio
async def test_embedding_metadata_retains_versions_and_enforces_vector_dimensions(
    engine: AsyncEngine,
) -> None:
    """Embedding rows remain reproducible to source/model/schema and reject shape drift."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    incident = Incident.open(
        IncidentId("incident-memory"),
        TenantId("tenant-1"),
        IncidentSeverity.SEV3,
        opened_at=NOW,
    )
    async with sessions.begin() as session:
        await IncidentRepository(session).add(incident)
        session.add(
            IncidentMemoryEmbeddingRow(
                id="embedding-1",
                incident_id=incident.id.value,
                source_content_hash="a" * 64,
                provider="mock",
                model="deterministic-embedding",
                model_version="1.0.0",
                dimensions=3,
                content_schema_version="incident-memory/v1",
                normalization_version="l2/v1",
                embedding=[0.1, 0.2, 0.3],
                reindex_required=False,
                created_at=NOW,
            )
        )

    async with sessions() as session:
        row = await session.get(IncidentMemoryEmbeddingRow, "embedding-1")
        assert row is not None
        assert row.embedding == pytest.approx([0.1, 0.2, 0.3])
        assert row.model_version == "1.0.0"
        assert row.content_schema_version == "incident-memory/v1"

    async with sessions.begin() as session:
        session.add(
            IncidentMemoryEmbeddingRow(
                id="embedding-invalid",
                incident_id=incident.id.value,
                source_content_hash="b" * 64,
                provider="mock",
                model="deterministic-embedding",
                model_version="2.0.0",
                dimensions=3,
                content_schema_version="incident-memory/v1",
                normalization_version="l2/v1",
                embedding=[0.1, 0.2],
                reindex_required=True,
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError, match="ck_embeddings_vector_dimensions"):
            await session.flush()
