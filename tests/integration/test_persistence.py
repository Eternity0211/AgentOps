"""PostgreSQL integration tests for migrations and operational repositories."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import count, pairwise
from pathlib import Path
from typing import Any, cast

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

from agentops_incident_commander.application import (
    EvidenceReferenceResolution,
    ModelCallTraceManager,
    PromptLifecycleChange,
    PromptLifecycleManager,
    RemediationEvidenceGate,
    SimilarIncidentRetriever,
    ToolAdapterContext,
    ToolCallRequest,
    ToolGateway,
    evaluate_evidence_gate,
    evidence_gate_decision_fingerprint,
    model_call_trace_fingerprint,
)
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
    Artifact,
    ArtifactId,
    ArtifactStorage,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    AuthorizationError,
    CausationId,
    CorrelationId,
    EventMetadata,
    EventReason,
    Evidence,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceGateReason,
    EvidenceGateReasonCode,
    EvidenceGateRules,
    EvidenceId,
    EvidenceLineage,
    EvidenceQuality,
    EvidenceSourceType,
    Incident,
    IncidentChange,
    IncidentId,
    IncidentMemoryConfirmationSource,
    IncidentMemoryEmbedding,
    IncidentMemoryId,
    IncidentMemoryOutcome,
    IncidentMemoryProjection,
    IncidentMemorySearchQuery,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    Job,
    JobFailureRoute,
    JobId,
    JobLeaseError,
    JobStatus,
    ModelCallId,
    ModelCallStatus,
    ModelCost,
    ModelCostSource,
    ModelMetering,
    ModelMeteringUnavailableReason,
    ModelTokenUsage,
    NormalizedQuery,
    OpaqueIdentifier,
    OptimisticVersionError,
    OutboxEvent,
    OutboxEventId,
    OutboxLeaseError,
    OutboxPayload,
    Permission,
    Principal,
    PromptDefinition,
    PromptId,
    PromptInjectionStatus,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptPurpose,
    PromptRegressionContext,
    PromptRegressionEvaluation,
    PromptRegressionFixtureResult,
    PromptSchemaCompatibility,
    PromptTraceLink,
    PromptVersionReference,
    QueryParameter,
    RedactionStatus,
    RedactionTransformId,
    RetentionClass,
    Role,
    RootCauseEvidenceClaim,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    ToolAccessClass,
    ToolAuditPolicy,
    ToolCallId,
    ToolDefinition,
    ToolIdempotency,
    ToolRegistry,
    ToolRetryPolicy,
    ToolRisk,
    ToolSchema,
    TrustClassification,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure import DeterministicIncidentMemoryEmbedder
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage
from agentops_incident_commander.infrastructure.persistence import (
    AlertGroupRow,
    AlertRepository,
    AlertRow,
    AuditEventRow,
    AuditRepository,
    EvidenceGateDecisionRow,
    EvidenceGateRepository,
    EvidenceRepository,
    EvidenceRow,
    IdempotencyRecordRow,
    IncidentCancellationRequestRow,
    IncidentMemoryEmbeddingRow,
    IncidentMemoryProjectionRow,
    IncidentMemoryRepository,
    IncidentRepository,
    IncidentTransitionRow,
    JobRepository,
    JobRow,
    ModelCallTraceRepository,
    ModelCallTraceRow,
    OutboxEventRow,
    OutboxRepository,
    PromptLifecycleEventRow,
    PromptLifecycleRepository,
    PromptVersionRow,
)
from agentops_incident_commander.workflows import (
    REMEDIATION_PROPOSAL_SCHEMA_VERSION,
    RecoveryAction,
    RemediationFailureHandling,
    RemediationFailureRoute,
    RemediationProposal,
    RollbackPrerequisites,
    RollbackServiceParameters,
    RollbackVerificationConditions,
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
                "incident_transitions, evidence, idempotency_records, outbox_events, jobs, "
                "evidence_gate_decisions, model_call_traces, prompt_lifecycle_events, "
                "prompt_versions, "
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
    artifact_storage: ArtifactStorage | None = None,
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
        artifact_storage=artifact_storage,
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
        "evidence",
        "evidence_gate_decisions",
        "incidents",
        "incident_transitions",
        "incident_cancellation_requests",
        "incident_memory_embeddings",
        "incident_memory_projections",
        "idempotency_records",
        "jobs",
        "model_call_traces",
        "outbox_events",
        "prompt_lifecycle_events",
        "prompt_versions",
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
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"

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
    assert response.json()["code"] == "PERMISSION_DENIED"
    assert response.json()["detail"] == "principal lacks permission investigation:start"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["x-request-id"] == response.json()["request_id"]


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
async def test_evidence_api_resolves_authorized_artifacts_without_tenant_disclosure(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    await add_incident(engine, "incident-evidence", tenant="tenant-1")
    item = evidence_record()
    metadata = evidence_artifact()
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.store(metadata, b"evidence")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        await EvidenceRepository(session).add(item, metadata)

    viewer = principal(tenant="tenant-1", roles=frozenset({Role.VIEWER}))
    app = api_app(engine, viewer, artifact_storage=storage)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/v1/incidents/incident-evidence/evidence")
        detail = await client.get("/api/v1/incidents/incident-evidence/evidence/evidence-1")
        content = await client.get(
            "/api/v1/incidents/incident-evidence/evidence/evidence-1/artifact"
        )
        wrong_incident = await client.get("/api/v1/incidents/another-incident/evidence/evidence-1")

    assert listed.status_code == detail.status_code == content.status_code == 200
    assert listed.json()["items"][0]["id"] == "evidence-1"
    assert listed.json()["items"][0]["expired"] is False
    assert detail.json()["content_hash"] == metadata.content_hash.value
    assert content.content == b"evidence"
    assert content.headers["x-content-sha256"] == metadata.content_hash.value
    assert content.headers["cache-control"] == "private, no-store"
    assert wrong_incident.status_code == 404

    foreign_app = api_app(engine, principal(tenant="tenant-foreign"), artifact_storage=storage)
    async with AsyncClient(
        transport=ASGITransport(app=foreign_app), base_url="http://test"
    ) as client:
        foreign_list = await client.get("/api/v1/incidents/incident-evidence/evidence")
        foreign_detail = await client.get("/api/v1/incidents/incident-evidence/evidence/evidence-1")
    assert foreign_list.status_code == foreign_detail.status_code == 404

    unavailable_app = api_app(engine, viewer)
    missing_app = api_app(
        engine, viewer, artifact_storage=LocalArtifactStorage(tmp_path / "empty-artifacts")
    )
    artifact_path = "/api/v1/incidents/incident-evidence/evidence/evidence-1/artifact"
    async with AsyncClient(
        transport=ASGITransport(app=unavailable_app), base_url="http://test"
    ) as client:
        unavailable = await client.get(artifact_path)
    async with AsyncClient(
        transport=ASGITransport(app=missing_app), base_url="http://test"
    ) as client:
        missing = await client.get(artifact_path)
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "ARTIFACT_STORAGE_UNAVAILABLE"
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_tool_gateway_persists_started_and_succeeded_audit_events(
    engine: AsyncEngine,
) -> None:
    version = SemanticVersion("1.0.0")
    input_schema = ToolSchema.from_mapping(
        version,
        {
            "additionalProperties": False,
            "properties": {"service": {"type": "string"}},
            "required": ["service"],
            "type": "object",
        },
    )
    output_schema = ToolSchema.from_mapping(
        version,
        {
            "additionalProperties": False,
            "properties": {"count": {"minimum": 0, "type": "integer"}},
            "required": ["count"],
            "type": "object",
        },
    )
    definition = ToolDefinition(
        name="query_logs",
        semantic_version=version,
        input_schema=input_schema,
        output_schema=output_schema,
        access_class=ToolAccessClass.READ,
        risk=ToolRisk.LOW,
        required_permission=Permission.EVIDENCE_READ,
        timeout_ms=1000,
        retry_policy=ToolRetryPolicy(1, 0, 0, frozenset()),
        idempotency=ToolIdempotency.NOT_APPLICABLE,
        audit=ToolAuditPolicy("tool.call", version),
        max_input_bytes=1024,
        max_result_bytes=1024,
    )

    class Adapter:
        async def invoke(
            self, context: ToolAdapterContext, arguments: Mapping[str, Any]
        ) -> Mapping[str, Any]:
            assert context.incident_id == IncidentId("incident-tool")
            assert arguments == {"service": "orders"}
            return {"count": 2}

    actor = principal(tenant="tenant-tool-gateway", roles=frozenset({Role.VIEWER}))
    call = ToolCallRequest.from_mapping(
        call_id=ToolCallId("tool-call-integration"),
        tool_name="query_logs",
        tool_version=version,
        incident_id=IncidentId("incident-tool"),
        workflow_run_id=WorkflowRunId("workflow-tool"),
        principal=actor,
        correlation_id=CorrelationId("correlation-tool"),
        causation_id=CausationId("cause-tool"),
        arguments={"service": "orders"},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    audit_ids = count(1)
    async with sessions.begin() as session:
        result = await ToolGateway(
            ToolRegistry((definition,)),
            {definition.identity: Adapter()},
            AuditRepository(session),
            clock=lambda: NOW,
            audit_id_factory=lambda: f"audit-tool-{next(audit_ids)}",
        ).invoke(call)
    assert result.result() == {"count": 2}

    async with sessions() as session:
        rows = (
            await session.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.correlation_id == "correlation-tool")
                .order_by(AuditEventRow.sequence)
            )
        ).all()
    assert [row.event_type for row in rows] == ["tool.call_started", "tool.call_succeeded"]
    assert rows[0].request_hash == call.request_hash.value
    assert rows[0].result_hash is None
    assert rows[1].result_hash == result.content_hash.value
    assert {row.tenant_id for row in rows} == {"tenant-tool-gateway"}


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
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

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
    assert hidden.json()["code"] == "RESOURCE_NOT_FOUND"

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
    assert illegal.json()["code"] == stale.json()["code"] == "INCIDENT_STATE_CONFLICT"
    assert invalid_id.status_code == 422
    assert invalid_id.json()["code"] == "DOMAIN_VALIDATION_FAILED"
    assert invalid_header.status_code == 422
    assert invalid_header.json()["code"] == "REQUEST_VALIDATION_FAILED"

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
    """Confirmed projections bind vectors, replay idempotently, and mark old versions stale."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    closed_at = NOW + timedelta(hours=1)
    incident = Incident(
        id=IncidentId("incident-memory"),
        tenant_id=TenantId("tenant-1"),
        severity=IncidentSeverity.SEV3,
        opened_at=NOW,
        updated_at=closed_at,
        state=IncidentState.CLOSED,
        version=AggregateVersion(5),
        closed_at=closed_at,
    )
    projection = IncidentMemoryProjection.create(
        memory_id=IncidentMemoryId("memory-1"),
        incident=incident,
        service="orders",
        root_cause_summary="Connection pool exhausted after deployment.",
        outcome=IncidentMemoryOutcome.RECOVERED,
        outcome_summary="Rollback passed the stability window.",
        source_evidence_ids=(EvidenceId("evidence-memory-1"),),
        diagnosis_report_fingerprint=Sha256Digest("a" * 64),
        evidence_gate_decision_fingerprint=Sha256Digest("b" * 64),
        confirmation_source=IncidentMemoryConfirmationSource.DETERMINISTIC_VERIFIER,
        confirmation_reference=OpaqueIdentifier("verification-memory-1"),
        recovery_action_reference=OpaqueIdentifier("rollback-memory-1"),
        projected_at=closed_at + timedelta(minutes=1),
    )
    async with sessions.begin() as session:
        await IncidentRepository(session).add(incident)
        first = await DeterministicIncidentMemoryEmbedder(dimensions=3).generate(
            projection,
            embedding_id=OpaqueIdentifier("embedding-1"),
            created_at=closed_at + timedelta(minutes=2),
        )
        stored = await IncidentMemoryRepository(session).store(projection, first)
        assert stored.id == first.id

    async with sessions.begin() as session:
        replay = await DeterministicIncidentMemoryEmbedder(dimensions=3).generate(
            projection,
            embedding_id=OpaqueIdentifier("embedding-replay"),
            created_at=closed_at + timedelta(minutes=3),
        )
        replayed = await IncidentMemoryRepository(session).store(projection, replay)
        assert replayed.id == OpaqueIdentifier("embedding-1")

        replacement = await DeterministicIncidentMemoryEmbedder(
            dimensions=4, model_version="2.0.0"
        ).generate(
            projection,
            embedding_id=OpaqueIdentifier("embedding-2"),
            created_at=closed_at + timedelta(minutes=4),
        )
        await IncidentMemoryRepository(session).store(projection, replacement)

    async with sessions() as session:
        memory_row = await session.get(IncidentMemoryProjectionRow, "memory-1")
        rows = (
            await session.scalars(
                select(IncidentMemoryEmbeddingRow).order_by(
                    IncidentMemoryEmbeddingRow.model_version
                )
            )
        ).all()
        assert memory_row is not None
        assert memory_row.tenant_id == "tenant-1"
        assert memory_row.content_fingerprint == projection.content_fingerprint.value
        assert [(row.model_version, row.reindex_required) for row in rows] == [
            ("1.0.0", True),
            ("2.0.0", False),
        ]
        assert rows[1].embedding == pytest.approx(list(replacement.vector))

    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="active memory projection"):
            await IncidentMemoryRepository(session).store(
                projection,
                replace(first, tenant_id=TenantId("tenant-other")),
            )

        missing_incident = replace(
            incident,
            id=IncidentId("incident-memory-missing"),
            tenant_id=TenantId("tenant-missing"),
        )
        missing_projection = IncidentMemoryProjection.create(
            memory_id=IncidentMemoryId("memory-missing"),
            incident=missing_incident,
            service="orders",
            root_cause_summary="Confirmed but not persisted.",
            outcome=IncidentMemoryOutcome.HUMAN_RESOLVED,
            outcome_summary="Resolved by operator.",
            source_evidence_ids=(EvidenceId("evidence-missing"),),
            diagnosis_report_fingerprint=Sha256Digest("d" * 64),
            evidence_gate_decision_fingerprint=Sha256Digest("e" * 64),
            confirmation_source=IncidentMemoryConfirmationSource.HUMAN_REVIEW,
            confirmation_reference=OpaqueIdentifier("review-missing"),
            recovery_action_reference=None,
            projected_at=closed_at + timedelta(minutes=1),
        )
        missing_embedding = await DeterministicIncidentMemoryEmbedder(dimensions=3).generate(
            missing_projection,
            embedding_id=OpaqueIdentifier("embedding-missing"),
            created_at=closed_at + timedelta(minutes=2),
        )
        with pytest.raises(InvalidDomainValueError, match="closed Incident"):
            await IncidentMemoryRepository(session).store(missing_projection, missing_embedding)

        changed_projection = IncidentMemoryProjection.create(
            memory_id=projection.id,
            incident=incident,
            service="orders",
            root_cause_summary="A conflicting confirmed cause.",
            outcome=IncidentMemoryOutcome.RECOVERED,
            outcome_summary="Rollback passed the stability window.",
            source_evidence_ids=(EvidenceId("evidence-memory-1"),),
            diagnosis_report_fingerprint=Sha256Digest("a" * 64),
            evidence_gate_decision_fingerprint=Sha256Digest("b" * 64),
            confirmation_source=IncidentMemoryConfirmationSource.DETERMINISTIC_VERIFIER,
            confirmation_reference=OpaqueIdentifier("verification-memory-1"),
            recovery_action_reference=OpaqueIdentifier("rollback-memory-1"),
            projected_at=closed_at + timedelta(minutes=1),
        )
        changed_embedding = await DeterministicIncidentMemoryEmbedder(dimensions=3).generate(
            changed_projection,
            embedding_id=OpaqueIdentifier("embedding-conflict"),
            created_at=closed_at + timedelta(minutes=5),
        )
        with pytest.raises(InvalidDomainValueError, match="different memory projection"):
            await IncidentMemoryRepository(session).store(changed_projection, changed_embedding)

        rebound = replace(first, vector=(-first.vector[0], *first.vector[1:]))
        with pytest.raises(InvalidDomainValueError, match="version identity"):
            await IncidentMemoryRepository(session).store(projection, rebound)

    async with sessions.begin() as session:
        session.add(
            IncidentMemoryEmbeddingRow(
                id="embedding-unbound",
                incident_id=incident.id.value,
                source_content_hash="c" * 64,
                provider="agentops-mock",
                model="deterministic-embedding",
                model_version="3.0.0",
                dimensions=3,
                content_schema_version="1.0.0",
                normalization_version="l2-v1",
                embedding=[0.1, 0.2, 0.3],
                reindex_required=False,
                created_at=NOW,
            )
        )
        with pytest.raises(DBAPIError, match="authoritative memory projection"):
            await session.flush()


@pytest.mark.anyio
async def test_similar_incident_retrieval_is_tenant_fresh_versioned_and_minimal(
    engine: AsyncEngine,
) -> None:
    """Similarity lookup hides stale, self, incompatible, and cross-tenant memories."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    requested_at = NOW + timedelta(days=60)

    def memory(
        incident_id: str,
        *,
        tenant: str = "tenant-1",
        age_days: int = 2,
        vector: tuple[float, ...] = (1.0, 0.0),
        model_version: str = "1.0.0",
    ) -> tuple[Incident, IncidentMemoryProjection, IncidentMemoryEmbedding]:
        closed_at = requested_at - timedelta(days=age_days)
        incident = Incident(
            id=IncidentId(incident_id),
            tenant_id=TenantId(tenant),
            severity=IncidentSeverity.SEV3,
            opened_at=closed_at - timedelta(hours=1),
            updated_at=closed_at,
            state=IncidentState.CLOSED,
            version=AggregateVersion(4),
            closed_at=closed_at,
        )
        item = IncidentMemoryProjection.create(
            memory_id=IncidentMemoryId(f"memory-{incident_id}"),
            incident=incident,
            service="orders",
            root_cause_summary=f"Confirmed cause for {incident_id}",
            outcome=IncidentMemoryOutcome.RECOVERED,
            outcome_summary="Recovery passed deterministic verification.",
            source_evidence_ids=(EvidenceId(f"evidence-{incident_id}"),),
            diagnosis_report_fingerprint=Sha256Digest("a" * 64),
            evidence_gate_decision_fingerprint=Sha256Digest("b" * 64),
            confirmation_source=IncidentMemoryConfirmationSource.DETERMINISTIC_VERIFIER,
            confirmation_reference=OpaqueIdentifier(f"verify-{incident_id}"),
            recovery_action_reference=OpaqueIdentifier(f"action-{incident_id}"),
            projected_at=closed_at + timedelta(minutes=1),
        )
        embedding = IncidentMemoryEmbedding(
            id=OpaqueIdentifier(f"embedding-{incident_id}"),
            tenant_id=incident.tenant_id,
            memory_id=item.id,
            incident_id=incident.id,
            source_content_fingerprint=item.content_fingerprint,
            provider="agentops-mock",
            model="deterministic-sha256",
            model_version=model_version,
            content_schema_version=item.schema_version,
            normalization_version="l2-v1",
            vector=vector,
            created_at=closed_at + timedelta(minutes=2),
        )
        return incident, item, embedding

    records = (
        memory("incident-current"),
        memory("incident-similar-a"),
        memory("incident-similar-b", vector=(0.8, 0.6)),
        memory("incident-reindexed", vector=(0.9, 0.435889894)),
        memory("incident-stale", age_days=31),
        memory("incident-other-tenant", tenant="tenant-2"),
        memory("incident-old-model", model_version="0.9.0"),
    )
    async with sessions.begin() as session:
        repository = IncidentMemoryRepository(session)
        for incident, item, embedding in records:
            await IncidentRepository(session).add(incident)
            await repository.store(item, embedding)
            if incident.id == IncidentId("incident-reindexed"):
                await repository.store(
                    item,
                    replace(
                        embedding,
                        id=OpaqueIdentifier("embedding-incident-reindexed-v2"),
                        model_version="2.0.0",
                    ),
                )

    query = IncidentMemorySearchQuery(
        tenant_id=TenantId("tenant-1"),
        current_incident_id=IncidentId("incident-current"),
        provider="agentops-mock",
        model="deterministic-sha256",
        model_version="1.0.0",
        content_schema_version="1.0.0",
        normalization_version="l2-v1",
        vector=(1.0, 0.0),
        max_results=3,
        requested_at=requested_at,
        max_age=timedelta(days=30),
    )
    viewer = Principal(ActorId("viewer-memory"), TenantId("tenant-1"), frozenset({Role.VIEWER}))
    async with sessions() as session:
        results = await SimilarIncidentRetriever(IncidentMemoryRepository(session)).search(
            viewer, query
        )

    assert [result.incident_id.value for result in results] == [
        "incident-similar-a",
        "incident-similar-b",
    ]
    assert [result.similarity for result in results] == pytest.approx([1.0, 0.8])
    assert all(result.historical_reference_only for result in results)
    assert results[0].root_cause_summary == "Confirmed cause for incident-similar-a"
    assert not hasattr(results[0], "tenant_id")
    assert not hasattr(results[0], "source_evidence_ids")

    async with sessions() as session:
        with pytest.raises(AuthorizationError, match="not available"):
            await IncidentMemoryRepository(session).search(
                replace(
                    query,
                    current_incident_id=IncidentId("incident-other-tenant"),
                )
            )
        with pytest.raises(AuthorizationError, match="another tenant"):
            await SimilarIncidentRetriever(IncidentMemoryRepository(session)).search(
                Principal(
                    ActorId("viewer-other"),
                    TenantId("tenant-2"),
                    frozenset({Role.VIEWER}),
                ),
                query,
            )


def evidence_artifact(*, tenant: str = "tenant-1", incident: str = "incident-evidence") -> Artifact:
    return Artifact(
        id=ArtifactId("artifact-evidence"),
        tenant_id=TenantId(tenant),
        incident_id=IncidentId(incident),
        locator="local-artifact:v1:artifact-evidence",
        media_type="application/json",
        content_schema_version="1.0.0",
        content_hash=Sha256Digest(hashlib.sha256(b"evidence").hexdigest()),
        size_bytes=8,
        retention_class=RetentionClass.INCIDENT,
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
        redaction_status=RedactionStatus.REDACTED,
        encrypted=False,
    )


def evidence_record(*, tenant: str = "tenant-1", incident: str = "incident-evidence") -> Evidence:
    stored_artifact = evidence_artifact(tenant=tenant, incident=incident)
    return Evidence(
        id=EvidenceId("evidence-1"),
        tenant_id=TenantId(tenant),
        incident_id=IncidentId(incident),
        source_type=EvidenceSourceType.LOG,
        source_instance="loki-primary",
        tool_name="query_logs",
        tool_version="1.0.0",
        tool_schema_version="1.0.0",
        normalized_query=NormalizedQuery((QueryParameter("service", "order"),)),
        observed_from=NOW,
        observed_to=NOW + timedelta(minutes=1),
        collected_at=NOW + timedelta(minutes=2),
        artifact_id=stored_artifact.id,
        content_hash=stored_artifact.content_hash,
        parser_version="1.0.0",
        normalizer_version="1.0.0",
        quality=EvidenceQuality(9000, ("complete-window",)),
        lineage=EvidenceLineage(
            ToolCallId("tool-call-1"),
            WorkflowRunId("workflow-1"),
            RedactionTransformId("redaction-1"),
        ),
        trust=TrustClassification.DIRECT_OBSERVATION,
        prompt_injection_status=PromptInjectionStatus.NONE,
        expires_at=NOW + timedelta(days=7),
    )


@pytest.mark.anyio
async def test_evidence_repository_round_trip_is_incident_and_tenant_scoped(
    engine: AsyncEngine,
) -> None:
    await add_incident(engine, "incident-evidence", tenant="tenant-1")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    value = evidence_record()
    async with sessions.begin() as session:
        await EvidenceRepository(session).add(value, evidence_artifact())

    async with sessions() as session:
        repository = EvidenceRepository(session)
        assert (
            await repository.get(value.id, tenant_id=value.tenant_id, incident_id=value.incident_id)
            == value
        )
        assert (
            await repository.get(
                value.id, tenant_id=TenantId("tenant-2"), incident_id=value.incident_id
            )
            is None
        )
        assert await session.scalar(select(func.count()).select_from(EvidenceRow)) == 1


@pytest.mark.anyio
async def test_database_rejects_cross_tenant_evidence_and_duplicate_artifact(
    engine: AsyncEngine,
) -> None:
    await add_incident(engine, "incident-evidence", tenant="tenant-1")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    cross_tenant = evidence_record(tenant="tenant-2")
    async with sessions.begin() as session:
        with pytest.raises(IntegrityError, match="fk_evidence_incident_tenant"):
            await EvidenceRepository(session).add(
                cross_tenant, evidence_artifact(tenant="tenant-2")
            )

    value = evidence_record()
    async with sessions.begin() as session:
        await EvidenceRepository(session).add(value, evidence_artifact())
    duplicate = replace(value, id=EvidenceId("evidence-2"))
    async with sessions.begin() as session:
        with pytest.raises(IntegrityError, match="uq_evidence_artifact"):
            await EvidenceRepository(session).add(duplicate, evidence_artifact())


def gate_evaluation() -> tuple[
    RootCauseEvidenceClaim,
    tuple[Evidence, ...],
    EvidenceGateRules,
    EvidenceGateDecision,
]:
    first = replace(
        evidence_record(incident="incident-gate-storage"),
        quality=EvidenceQuality(9_000, ("source-available",)),
    )
    second = replace(
        first,
        id=EvidenceId("evidence-2"),
        source_type=EvidenceSourceType.METRIC,
        source_instance="prometheus-primary",
        artifact_id=ArtifactId("artifact-evidence-2"),
        lineage=EvidenceLineage(ToolCallId("tool-call-2"), WorkflowRunId("workflow-1"), None),
    )
    claim = RootCauseEvidenceClaim(
        first.incident_id,
        "candidate-database-pool",
        (first.id, second.id),
        missing_evidence=("Need a deployment marker",),
        model_confidence_basis_points=9_500,
    )
    rules = EvidenceGateRules()
    evaluated_at = NOW + timedelta(minutes=3)
    decision = evaluate_evidence_gate(
        claim,
        EvidenceReferenceResolution((first, second), ()),
        rules=rules,
        at=evaluated_at,
    )
    return claim, (first, second), rules, decision


def gate_audit(
    event_id: str, decision: EvidenceGateDecision, *, tenant: str = "tenant-1"
) -> AuditEvent:
    return AuditEvent(
        id=AuditEventId(event_id),
        tenant_id=TenantId(tenant),
        type="evidence.gate_decided",
        event_version=1,
        payload_schema_version="evidence_gate/v1",
        actor_id=ActorId("worker-gate"),
        correlation_id=CorrelationId("correlation-gate"),
        causation_id=CausationId("diagnosis-run-gate"),
        target=AuditTarget(
            "evidence.gate_decision", OpaqueIdentifier(decision.input_fingerprint.value)
        ),
        occurred_at=decision.evaluated_at,
        request_hash=decision.input_fingerprint,
        result_hash=evidence_gate_decision_fingerprint(decision),
    )


@pytest.mark.anyio
async def test_evidence_gate_repository_persists_replays_and_scopes_decision(
    engine: AsyncEngine,
) -> None:
    await add_incident(engine, "incident-gate-storage", tenant="tenant-1")
    claim, evidence, rules, decision = gate_evaluation()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        stored = await EvidenceGateRepository(session).record(
            tenant_id=TenantId("tenant-1"),
            claim=claim,
            evidence=evidence,
            rules=rules,
            decision=decision,
            audit_event=gate_audit("audit-gate-1", decision),
        )
    assert stored == decision
    assert stored.outcome is EvidenceGateOutcome.FAIL
    assert stored.reasons[0].code is EvidenceGateReasonCode.MISSING_EVIDENCE_DECLARED

    async with sessions.begin() as session:
        replayed = await EvidenceGateRepository(session).record(
            tenant_id=TenantId("tenant-1"),
            claim=claim,
            evidence=tuple(reversed(evidence)),
            rules=rules,
            decision=decision,
            audit_event=gate_audit("audit-gate-replay", decision),
        )
    assert replayed == decision

    async with sessions() as session:
        repository = EvidenceGateRepository(session)
        assert (
            await repository.get(
                tenant_id=TenantId("tenant-1"),
                incident_id=claim.incident_id,
                candidate_id=claim.candidate_id,
                input_fingerprint=decision.input_fingerprint,
            )
            == decision
        )
        assert (
            await repository.get(
                tenant_id=TenantId("tenant-2"),
                incident_id=claim.incident_id,
                candidate_id=claim.candidate_id,
                input_fingerprint=decision.input_fingerprint,
            )
            is None
        )
        row = await session.scalar(select(EvidenceGateDecisionRow))
        assert row is not None
        snapshot_rules = cast(dict[str, object], row.input_snapshot["rules"])
        assert snapshot_rules["version"] == rules.version
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEventRow)
                .where(AuditEventRow.event_type == "evidence.gate_decided")
            )
            == 1
        )


@pytest.mark.anyio
async def test_evidence_gate_repository_rejects_conflict_scope_and_unbound_audit(
    engine: AsyncEngine,
) -> None:
    await add_incident(engine, "incident-gate-storage", tenant="tenant-1")
    claim, evidence, rules, decision = gate_evaluation()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        repository = EvidenceGateRepository(session)
        await repository.record(
            tenant_id=TenantId("tenant-1"),
            claim=claim,
            evidence=evidence,
            rules=rules,
            decision=decision,
            audit_event=gate_audit("audit-gate-2", decision),
        )

    conflicting = replace(
        decision,
        reasons=(
            EvidenceGateReason(
                EvidenceGateReasonCode.EVIDENCE_STALE,
                "Conflicting stored result.",
                (evidence[0].id,),
            ),
        ),
    )
    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="conflicts with storage"):
            await EvidenceGateRepository(session).record(
                tenant_id=TenantId("tenant-1"),
                claim=claim,
                evidence=evidence,
                rules=rules,
                decision=conflicting,
                audit_event=gate_audit("audit-gate-conflict", conflicting),
            )

    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="input snapshot"):
            await EvidenceGateRepository(session).record(
                tenant_id=TenantId("tenant-1"),
                claim=claim,
                evidence=(replace(evidence[0], tenant_id=TenantId("tenant-2")), evidence[1]),
                rules=rules,
                decision=decision,
                audit_event=gate_audit("audit-gate-scope", decision),
            )

    async with sessions.begin() as session:
        mismatched = replace(decision, rules_version="2.0.0")
        with pytest.raises(InvalidDomainValueError, match="input snapshot"):
            await EvidenceGateRepository(session).record(
                tenant_id=TenantId("tenant-1"),
                claim=claim,
                evidence=evidence,
                rules=rules,
                decision=mismatched,
                audit_event=gate_audit("audit-gate-mismatch", mismatched),
            )

    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="audit event"):
            await EvidenceGateRepository(session).record(
                tenant_id=TenantId("tenant-1"),
                claim=claim,
                evidence=evidence,
                rules=rules,
                decision=decision,
                audit_event=gate_audit("audit-gate-unbound", decision, tenant="tenant-2"),
            )


@pytest.mark.anyio
async def test_evidence_gate_decision_and_audit_commit_or_rollback_together(
    engine: AsyncEngine,
) -> None:
    await add_incident(engine, "incident-gate-storage", tenant="tenant-1")
    claim, evidence, rules, decision = gate_evaluation()
    duplicate_audit = gate_audit("audit-gate-atomic", decision)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        await AuditRepository(session).append(duplicate_audit)

    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            await EvidenceGateRepository(session).record(
                tenant_id=TenantId("tenant-1"),
                claim=claim,
                evidence=evidence,
                rules=rules,
                decision=decision,
                audit_event=duplicate_audit,
            )

    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(EvidenceGateDecisionRow)) == 0


@pytest.mark.anyio
async def test_remediation_admission_requires_exact_stored_passing_gate_decision(
    engine: AsyncEngine,
) -> None:
    await add_incident(engine, "incident-gate-storage", tenant="tenant-1")
    original_claim, evidence, rules, _ = gate_evaluation()
    claim = replace(original_claim, missing_evidence=())
    decision = evaluate_evidence_gate(
        claim,
        EvidenceReferenceResolution(evidence, ()),
        rules=rules,
        at=NOW + timedelta(minutes=3),
    )
    assert decision.outcome is EvidenceGateOutcome.PASS
    proposal = RemediationProposal(
        schema_version=REMEDIATION_PROPOSAL_SCHEMA_VERSION,
        proposal_id="remediation-storage-1",
        proposal_version=1,
        incident_id=claim.incident_id.value,
        candidate_id=claim.candidate_id,
        evidence_gate_input_fingerprint=decision.input_fingerprint.value,
        evidence_gate_decision_fingerprint=evidence_gate_decision_fingerprint(decision).value,
        action=RecoveryAction.ROLLBACK_SERVICE,
        parameters=RollbackServiceParameters(
            service="orders",
            introducing_deployment_evidence_id=evidence[0].id.value,
        ),
        prerequisites=RollbackPrerequisites(current_version_evidence_id=evidence[1].id.value),
        verification_conditions=RollbackVerificationConditions(
            max_error_rate_basis_points=100,
            max_p95_latency_ms=500,
            stability_window_seconds=300,
        ),
        failure_handling=RemediationFailureHandling(
            route=RemediationFailureRoute.HUMAN_HANDOFF,
            max_rediagnosis_attempts=0,
        ),
        risk_assumptions=("The current deployment is bound by fresh Evidence.",),
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as session:
        gate = RemediationEvidenceGate(EvidenceGateRepository(session))
        with pytest.raises(InvalidDomainValueError, match="stored passing"):
            await gate.admit(proposal, tenant_id=TenantId("tenant-1"))

    async with sessions.begin() as session:
        await EvidenceGateRepository(session).record(
            tenant_id=TenantId("tenant-1"),
            claim=claim,
            evidence=evidence,
            rules=rules,
            decision=decision,
            audit_event=gate_audit("audit-gate-remediation", decision),
        )

    async with sessions() as session:
        gate = RemediationEvidenceGate(EvidenceGateRepository(session))
        admitted = await gate.admit(proposal, tenant_id=TenantId("tenant-1"))
        assert admitted.evidence_gate_decision == decision
        with pytest.raises(InvalidDomainValueError, match="stored passing"):
            await gate.admit(proposal, tenant_id=TenantId("tenant-2"))


def prompt_definition(
    version: str,
    content: str,
    *,
    memory_context_version: SemanticVersion | None = None,
) -> PromptDefinition:
    semantic = SemanticVersion(version)
    return PromptDefinition.create(
        prompt_id=PromptId("diagnosis-root-cause"),
        version=semantic,
        purpose=PromptPurpose.DIAGNOSIS,
        content=content,
        model_parameters=PromptModelParameters("mock", "model-v1", 0, 10_000, 2_048, 7),
        schema_compatibility=PromptSchemaCompatibility(
            SemanticVersion("1.0.0"),
            SemanticVersion("1.0.0"),
            memory_context_version,
        ),
        trace=PromptTraceLink(
            ActorId("admin-prompt"),
            CorrelationId("correlation-prompt"),
            CausationId(f"create-{version}"),
            NOW,
        ),
    )


@pytest.mark.anyio
async def test_prompt_lifecycle_repository_commits_versions_transitions_and_audit(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    audit_ids = count(1)
    owner = Principal(ActorId("admin-prompt"), TenantId("tenant-1"), frozenset({Role.ADMIN}))
    first = prompt_definition("1.0.0", "Diagnose only from resolvable evidence.")
    reference = PromptVersionReference(first.prompt_id, first.version)
    regression = PromptRegressionEvaluation(
        reference,
        SemanticVersion("1.0.0"),
        (PromptRegressionFixtureResult("valid-output", True),),
        NOW,
    )

    async def invoke(action: str) -> PromptDefinition:
        async with sessions.begin() as session:
            service = PromptLifecycleManager(
                PromptLifecycleRepository(session),
                clock=lambda: NOW,
                id_factory=lambda: f"audit-prompt-db-{next(audit_ids)}",
            )
            if action == "draft":
                return await service.draft(
                    first,
                    principal=owner,
                    correlation_id=CorrelationId("correlation-prompt"),
                    causation_id=CausationId("command-draft"),
                )
            if action == "evaluate":
                return await service.evaluate(
                    regression,
                    principal=owner,
                    correlation_id=CorrelationId("correlation-prompt"),
                    causation_id=CausationId("command-evaluate"),
                )
            return await service.promote(
                reference,
                principal=owner,
                correlation_id=CorrelationId("correlation-prompt"),
                causation_id=CausationId("command-promote"),
            )

    await invoke("draft")
    await invoke("evaluate")
    promoted = await invoke("promote")
    assert promoted.status is PromptLifecycleStatus.ACTIVE

    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="stale Prompt"):
            await PromptLifecycleRepository(session).apply(
                PromptLifecycleChange("stale", (first,), (first,)),
                audit_event("audit-prompt-stale"),
            )

    async with sessions() as session:
        repository = PromptLifecycleRepository(session)
        assert (
            await repository.resolve(TenantId("tenant-1"), first.prompt_id, first.version)
            == promoted
        )
        assert await repository.active(TenantId("tenant-1"), first.prompt_id) == promoted
        assert (
            await repository.resolve(TenantId("tenant-2"), first.prompt_id, first.version) is None
        )
        assert await repository.active(TenantId("tenant-2"), first.prompt_id) is None
        assert await session.scalar(select(func.count()).select_from(PromptVersionRow)) == 1
        assert await session.scalar(select(func.count()).select_from(PromptLifecycleEventRow)) == 3
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEventRow)
                .where(AuditEventRow.event_type.like("prompt.%"))
            )
            == 3
        )


@pytest.mark.anyio
async def test_prompt_repository_retains_memory_schema_and_paired_regression(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner = Principal(ActorId("admin-prompt"), TenantId("tenant-1"), frozenset({Role.ADMIN}))
    definition = prompt_definition(
        "1.1.0",
        "Treat historical incidents only as non-authoritative context.",
        memory_context_version=SemanticVersion("1.0.0"),
    )
    reference = PromptVersionReference(definition.prompt_id, definition.version)
    regression = PromptRegressionEvaluation(
        reference,
        SemanticVersion("1.1.0"),
        (
            PromptRegressionFixtureResult(
                "historical-context", True, PromptRegressionContext.WITHOUT_MEMORY
            ),
            PromptRegressionFixtureResult(
                "historical-context", True, PromptRegressionContext.WITH_MEMORY
            ),
        ),
        NOW,
    )
    audit_ids = count(1)

    async with sessions.begin() as session:
        service = PromptLifecycleManager(
            PromptLifecycleRepository(session),
            clock=lambda: NOW,
            id_factory=lambda: f"audit-memory-prompt-{next(audit_ids)}",
        )
        await service.draft(
            definition,
            principal=owner,
            correlation_id=CorrelationId("correlation-memory-prompt"),
            causation_id=CausationId("draft-memory-prompt"),
        )
        await service.evaluate(
            regression,
            principal=owner,
            correlation_id=CorrelationId("correlation-memory-prompt"),
            causation_id=CausationId("evaluate-memory-prompt"),
        )

    async with sessions() as session:
        stored = await PromptLifecycleRepository(session).resolve(
            TenantId("tenant-1"), definition.prompt_id, definition.version
        )
        assert stored is not None
        assert stored.memory_aware
        event = await session.scalar(
            select(PromptLifecycleEventRow).where(PromptLifecycleEventRow.action == "evaluated")
        )
        assert event is not None
        assert event.regression_evaluation is not None
        fixtures = cast(list[dict[str, object]], event.regression_evaluation["results"])
        assert {fixture["context"] for fixture in fixtures} == {
            "WITHOUT_MEMORY",
            "WITH_MEMORY",
        }
        assert all(fixture["fabricated_references"] == 0 for fixture in fixtures)


async def activate_prompt_for_model_call(
    sessions: async_sessionmaker[AsyncSession],
) -> PromptDefinition:
    ids = count(1)
    owner = Principal(ActorId("admin-model"), TenantId("tenant-1"), frozenset({Role.ADMIN}))
    definition = prompt_definition("2.0.0", "Return evidence-linked candidates only.")
    reference = PromptVersionReference(definition.prompt_id, definition.version)
    regression = PromptRegressionEvaluation(
        reference,
        SemanticVersion("1.0.0"),
        (PromptRegressionFixtureResult("trace-safe", True),),
        NOW,
    )
    async with sessions.begin() as session:
        await PromptLifecycleManager(
            PromptLifecycleRepository(session),
            clock=lambda: NOW,
            id_factory=lambda: f"audit-model-prompt-{next(ids)}",
        ).draft(
            definition,
            principal=owner,
            correlation_id=CorrelationId("correlation-model"),
            causation_id=CausationId("draft-model-prompt"),
        )
    async with sessions.begin() as session:
        await PromptLifecycleManager(
            PromptLifecycleRepository(session),
            clock=lambda: NOW,
            id_factory=lambda: f"audit-model-prompt-{next(ids)}",
        ).evaluate(
            regression,
            principal=owner,
            correlation_id=CorrelationId("correlation-model"),
            causation_id=CausationId("evaluate-model-prompt"),
        )
    async with sessions.begin() as session:
        return await PromptLifecycleManager(
            PromptLifecycleRepository(session),
            clock=lambda: NOW,
            id_factory=lambda: f"audit-model-prompt-{next(ids)}",
        ).promote(
            reference,
            principal=owner,
            correlation_id=CorrelationId("correlation-model"),
            causation_id=CausationId("promote-model-prompt"),
        )


@pytest.mark.anyio
async def test_model_call_trace_repository_records_exact_metadata_and_atomic_audit(
    engine: AsyncEngine,
) -> None:
    await add_incident(engine, "incident-model-call", tenant="tenant-1")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    prompt = await activate_prompt_for_model_call(sessions)
    ids = count(1)
    async with sessions.begin() as session:
        started = await ModelCallTraceManager(
            ModelCallTraceRepository(session),
            clock=lambda: NOW + timedelta(minutes=1),
            id_factory=lambda: f"model-trace-{next(ids)}",
        ).start(
            tenant_id=TenantId("tenant-1"),
            incident_id=IncidentId("incident-model-call"),
            workflow_run_id=WorkflowRunId("workflow-model-call"),
            node="diagnosis.hypothesis",
            attempt=1,
            prompt=prompt,
            request_hash=Sha256Digest("d" * 64),
            actor_id=ActorId("diagnosis-worker"),
            correlation_id=CorrelationId("correlation-model"),
            causation_id=CausationId("node-model"),
        )
    exact_metering = ModelMetering(
        ModelTokenUsage(100, 20, 10, 5, 120),
        ModelCost(
            12_345,
            "USD",
            ModelCostSource.RATE_CARD_CALCULATED,
            SemanticVersion("1.0.0"),
        ),
    )
    async with sessions.begin() as session:
        completed = await ModelCallTraceManager(
            ModelCallTraceRepository(session),
            clock=lambda: NOW + timedelta(minutes=2),
            id_factory=lambda: f"model-trace-{next(ids)}",
        ).finish(
            started,
            status=ModelCallStatus.SUCCEEDED,
            metering=exact_metering,
            actor_id=ActorId("diagnosis-worker"),
            response_hash=Sha256Digest("e" * 64),
        )

    async with sessions.begin() as session:
        timed_out_started = await ModelCallTraceManager(
            ModelCallTraceRepository(session),
            clock=lambda: NOW + timedelta(minutes=3),
            id_factory=lambda: f"model-trace-{next(ids)}",
        ).start(
            tenant_id=TenantId("tenant-1"),
            incident_id=IncidentId("incident-model-call"),
            workflow_run_id=WorkflowRunId("workflow-model-call"),
            node="diagnosis.replan",
            attempt=2,
            prompt=prompt,
            request_hash=Sha256Digest("f" * 64),
            actor_id=ActorId("diagnosis-worker"),
            correlation_id=CorrelationId("correlation-model"),
            causation_id=CausationId("node-replan"),
        )
    unavailable = ModelMetering(
        None,
        None,
        ModelMeteringUnavailableReason.CALL_FAILED_BEFORE_METERING,
    )
    async with sessions.begin() as session:
        timed_out = await ModelCallTraceManager(
            ModelCallTraceRepository(session),
            clock=lambda: NOW + timedelta(minutes=4),
            id_factory=lambda: f"model-trace-{next(ids)}",
        ).finish(
            timed_out_started,
            status=ModelCallStatus.TIMED_OUT,
            metering=unavailable,
            actor_id=ActorId("diagnosis-worker"),
            failure_code="provider_timeout",
        )

    async with sessions() as session:
        repository = ModelCallTraceRepository(session)
        assert await repository.get(TenantId("tenant-1"), started.id) == completed
        assert await repository.get(TenantId("tenant-1"), timed_out_started.id) == timed_out
        assert await repository.get(TenantId("tenant-2"), started.id) is None
        row = await session.get(ModelCallTraceRow, started.id.value)
        assert row is not None
        assert row.input_tokens == 100
        assert row.cost_nanounits == 12_345
        assert row.request_hash == "d" * 64
        assert row.response_hash == "e" * 64
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEventRow)
                .where(AuditEventRow.event_type.like("model.call_%"))
            )
            == 4
        )

    forged = replace(started, id=ModelCallId("model-call-forged"), provider="other-provider")
    forged_fingerprint = model_call_trace_fingerprint(forged)
    forged_audit = AuditEvent(
        id=AuditEventId("audit-model-forged"),
        tenant_id=forged.tenant_id,
        type="model.call_started",
        event_version=1,
        payload_schema_version="model_call/v1",
        actor_id=ActorId("diagnosis-worker"),
        correlation_id=forged.correlation_id,
        causation_id=forged.causation_id,
        target=AuditTarget("model.call", forged.id),
        occurred_at=forged.started_at,
        request_hash=forged_fingerprint,
        result_hash=forged_fingerprint,
    )
    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="does not match"):
            await ModelCallTraceRepository(session).start(forged, forged_audit)

    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="audit event"):
            await ModelCallTraceRepository(session).start(
                forged,
                replace(forged_audit, tenant_id=TenantId("tenant-2")),
            )

    unregistered = replace(
        started,
        id=ModelCallId("model-call-unregistered"),
        prompt=PromptVersionReference(PromptId("missing-prompt"), SemanticVersion("1.0.0")),
    )
    unregistered_fingerprint = model_call_trace_fingerprint(unregistered)
    unregistered_audit = replace(
        forged_audit,
        id=AuditEventId("audit-model-unregistered"),
        target=AuditTarget("model.call", unregistered.id),
        request_hash=unregistered_fingerprint,
        result_hash=unregistered_fingerprint,
    )
    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="not registered"):
            await ModelCallTraceRepository(session).start(unregistered, unregistered_audit)

    async with sessions.begin() as session:
        immutable_started = await ModelCallTraceManager(
            ModelCallTraceRepository(session),
            clock=lambda: NOW + timedelta(minutes=5),
            id_factory=lambda: f"model-trace-{next(ids)}",
        ).start(
            tenant_id=TenantId("tenant-1"),
            incident_id=IncidentId("incident-model-call"),
            workflow_run_id=WorkflowRunId("workflow-model-call"),
            node="diagnosis.final",
            attempt=3,
            prompt=prompt,
            request_hash=Sha256Digest("1" * 64),
            actor_id=ActorId("diagnosis-worker"),
            correlation_id=CorrelationId("correlation-model"),
            causation_id=CausationId("node-final"),
        )
    changed_completion = replace(
        immutable_started.finish(
            status=ModelCallStatus.SUCCEEDED,
            completed_at=NOW + timedelta(minutes=6),
            metering=exact_metering,
            response_hash=Sha256Digest("2" * 64),
        ),
        model="changed-model",
    )
    changed_audit = AuditEvent(
        id=AuditEventId("audit-model-changed"),
        tenant_id=changed_completion.tenant_id,
        type="model.call_finished",
        event_version=1,
        payload_schema_version="model_call/v1",
        actor_id=ActorId("diagnosis-worker"),
        correlation_id=changed_completion.correlation_id,
        causation_id=changed_completion.causation_id,
        target=AuditTarget("model.call", changed_completion.id),
        occurred_at=changed_completion.completed_at or NOW,
        request_hash=model_call_trace_fingerprint(immutable_started),
        result_hash=model_call_trace_fingerprint(changed_completion),
    )
    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="immutable metadata"):
            await ModelCallTraceRepository(session).finish(
                immutable_started,
                changed_completion,
                changed_audit,
            )

    async with sessions.begin() as session:
        with pytest.raises(InvalidDomainValueError, match="stale model call"):
            await ModelCallTraceManager(
                ModelCallTraceRepository(session),
                clock=lambda: NOW + timedelta(minutes=3),
                id_factory=lambda: f"model-trace-{next(ids)}",
            ).finish(
                started,
                status=ModelCallStatus.TIMED_OUT,
                metering=ModelMetering(
                    None,
                    None,
                    ModelMeteringUnavailableReason.CALL_FAILED_BEFORE_METERING,
                ),
                actor_id=ActorId("diagnosis-worker"),
                failure_code="provider_timeout",
            )
