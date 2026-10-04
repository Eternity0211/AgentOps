"""Fast API contract tests complementing PostgreSQL behavior tests."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import HTTPException, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from agentops_incident_commander.apps.api import create_app
from agentops_incident_commander.apps.api_errors import ApiProblem
from agentops_incident_commander.apps.api_v1 import (
    ControlRequest,
    SessionFactory,
    build_api_v1_router,
    new_identifier,
)
from agentops_incident_commander.apps.config import ApiSettings
from agentops_incident_commander.domain import (
    ActorId,
    Artifact,
    ArtifactContent,
    ArtifactExpiredError,
    ArtifactId,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    IncidentId,
    Principal,
    RedactionStatus,
    RetentionClass,
    Role,
    Sha256Digest,
    TenantId,
)
from agentops_incident_commander.infrastructure.persistence.models import (
    AuditEventRow,
    EvidenceRow,
    IdempotencyRecordRow,
    IncidentCancellationRequestRow,
    IncidentRow,
    IncidentTransitionRow,
)

NOW = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
OPERATOR = Principal(ActorId("operator-api"), TenantId("tenant-api"), frozenset({Role.OPERATOR}))
VIEWER = Principal(ActorId("viewer-api"), TenantId("tenant-api"), frozenset({Role.VIEWER}))


class FakeScalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class FakeCursor:
    rowcount = 1


class Transaction(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    def __init__(
        self,
        *,
        scalar_values: list[object | None] | None = None,
        scalar_lists: list[list[object]] | None = None,
    ) -> None:
        self.scalar_values = list(scalar_values or [])
        self.scalar_lists = list(scalar_lists or [])
        self.added: list[object] = []

    async def scalar(self, _: object) -> Any:
        return self.scalar_values.pop(0)

    async def scalars(self, _: object) -> FakeScalars:
        return FakeScalars(self.scalar_lists.pop(0))

    async def execute(self, _: object) -> FakeCursor:
        return FakeCursor()

    def add(self, value: object) -> None:
        if isinstance(value, AuditEventRow):
            value.sequence = 1
        self.added.append(value)

    async def flush(self) -> None:
        return None

    def begin(self) -> Transaction:
        return Transaction()


def row(
    incident_id: str,
    *,
    state: str = "TRIAGED",
    version: int = 1,
    tenant: str = "tenant-api",
) -> IncidentRow:
    return IncidentRow(
        id=incident_id,
        tenant_id=tenant,
        severity="SEV2",
        state=state,
        version=version,
        opened_at=NOW,
        updated_at=NOW,
        closed_at=None,
        cancelled_at=NOW if state == "CANCELLED" else None,
        cancellation_requested_at=None,
    )


def evidence_row(
    evidence_id: str = "evidence-a",
    *,
    incident_id: str = "incident-a",
    artifact_id: str = "artifact-a",
    content_hash: str = "a" * 64,
    expires_at: datetime = NOW + timedelta(days=1),
) -> EvidenceRow:
    return EvidenceRow(
        id=evidence_id,
        tenant_id="tenant-api",
        incident_id=incident_id,
        source_type="LOG",
        source_instance="loki-primary",
        tool_name="query_logs",
        tool_version="1.0.0",
        tool_schema_version="1.0.0",
        normalized_query={"service": "orders"},
        observed_from=NOW - timedelta(minutes=2),
        observed_to=NOW - timedelta(minutes=1),
        collected_at=NOW,
        artifact_id=artifact_id,
        content_hash=content_hash,
        parser_version="1.0.0",
        normalizer_version="1.0.0",
        quality_score_basis_points=9000,
        quality_reasons=["complete-window"],
        tool_call_id="tool-call-a",
        workflow_run_id="workflow-a",
        redaction_transform_id="redaction-a",
        parent_evidence_ids=[],
        trust="DIRECT_OBSERVATION",
        prompt_injection_status="NONE",
        expires_at=expires_at,
        schema_version="1.0.0",
    )


def artifact(
    *,
    artifact_id: str = "artifact-a",
    incident_id: str = "incident-a",
    tenant_id: str = "tenant-api",
    content_hash: str = "a" * 64,
) -> Artifact:
    return Artifact(
        id=ArtifactId(artifact_id),
        tenant_id=TenantId(tenant_id),
        incident_id=IncidentId(incident_id),
        locator=f"local-artifact:v1:{artifact_id}",
        media_type="application/json",
        content_schema_version="1.0.0",
        content_hash=Sha256Digest(content_hash),
        size_bytes=2,
        retention_class=RetentionClass.INCIDENT,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        redaction_status=RedactionStatus.REDACTED,
        encrypted=False,
    )


class FakeArtifactStorage:
    def __init__(self, result: ArtifactContent | Exception) -> None:
        self.result = result

    def store(self, metadata: Artifact, content: bytes) -> Artifact:
        return metadata

    def retrieve(self, *_: object, **__: object) -> ArtifactContent:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def endpoint(
    path: str,
    method: str,
    *,
    audit_ids: list[str] | None = None,
    artifact_storage: FakeArtifactStorage | None = None,
) -> Any:
    ids = iter(audit_ids or ["audit-default"])
    router = build_api_v1_router(
        cast(SessionFactory, lambda: None),
        clock=lambda: NOW + timedelta(minutes=1),
        id_factory=lambda: next(ids),
        artifact_storage=artifact_storage,
    )
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path and method in (route.methods or set())
    )


@pytest.mark.anyio
async def test_evidence_routes_are_scoped_paginated_and_report_expiry() -> None:
    list_route = endpoint("/api/v1/incidents/{incident_id}/evidence", "GET")
    first = evidence_row("evidence-b")
    second = evidence_row("evidence-a", expires_at=NOW)
    page = await list_route(
        incident_id="incident-a",
        session=FakeSession(scalar_values=["incident-a"], scalar_lists=[[first, second]]),
        principal=VIEWER,
        limit=1,
        cursor=None,
    )
    assert [item.id for item in page.items] == ["evidence-b"]
    assert page.items[0].normalized_query == {"service": "orders"}
    assert page.next_cursor is not None

    final = await list_route(
        incident_id="incident-a",
        session=FakeSession(scalar_values=["incident-a"], scalar_lists=[[second]]),
        principal=VIEWER,
        limit=50,
        cursor=page.next_cursor,
    )
    assert final.items[0].expired is True
    assert final.next_cursor is None

    with pytest.raises(HTTPException) as missing_incident:
        await list_route(
            incident_id="missing",
            session=FakeSession(scalar_values=[None]),
            principal=VIEWER,
            limit=50,
            cursor=None,
        )
    assert missing_incident.value.status_code == 404

    for invalid_cursor in ("WzEsMl0", "WyJub3QtYS10aW1lIiwiaWQiXQ"):
        with pytest.raises(HTTPException) as invalid:
            await list_route(
                incident_id="incident-a",
                session=FakeSession(scalar_values=["incident-a"]),
                principal=VIEWER,
                limit=50,
                cursor=invalid_cursor,
            )
        assert invalid.value.status_code == 400

    detail_route = endpoint("/api/v1/incidents/{incident_id}/evidence/{evidence_id}", "GET")
    detail = await detail_route(
        incident_id="incident-a",
        evidence_id="evidence-a",
        session=FakeSession(scalar_values=[first]),
        principal=VIEWER,
    )
    assert detail.artifact_id == "artifact-a"
    assert detail.expired is False
    with pytest.raises(HTTPException) as missing_evidence:
        await detail_route(
            incident_id="incident-a",
            evidence_id="missing",
            session=FakeSession(scalar_values=[None]),
            principal=VIEWER,
        )
    assert missing_evidence.value.status_code == 404


@pytest.mark.anyio
async def test_artifact_route_verifies_binding_and_maps_storage_failures() -> None:
    content = ArtifactContent(artifact(), b"{}")
    route = endpoint(
        "/api/v1/incidents/{incident_id}/evidence/{evidence_id}/artifact",
        "GET",
        artifact_storage=FakeArtifactStorage(content),
    )
    response = await route(
        incident_id="incident-a",
        evidence_id="evidence-a",
        session=FakeSession(scalar_values=[evidence_row()]),
        principal=VIEWER,
    )
    assert response.body == b"{}"
    assert response.media_type == "application/json"
    assert response.headers["x-artifact-id"] == "artifact-a"
    assert response.headers["cache-control"] == "private, no-store"

    failure_cases = [
        (ArtifactNotFoundError("missing"), HTTPException, 404),
        (ArtifactExpiredError("expired"), ApiProblem, 410),
        (ArtifactIntegrityError("corrupt"), ApiProblem, 409),
    ]
    for storage_error, error_type, expected_status in failure_cases:
        failing = endpoint(
            "/api/v1/incidents/{incident_id}/evidence/{evidence_id}/artifact",
            "GET",
            artifact_storage=FakeArtifactStorage(storage_error),
        )
        with pytest.raises(error_type) as raised:
            await failing(
                incident_id="incident-a",
                evidence_id="evidence-a",
                session=FakeSession(scalar_values=[evidence_row()]),
                principal=VIEWER,
            )
        assert cast(HTTPException | ApiProblem, raised.value).status_code == expected_status


@pytest.mark.anyio
async def test_artifact_route_fails_closed_for_expiry_configuration_and_binding() -> None:
    path = "/api/v1/incidents/{incident_id}/evidence/{evidence_id}/artifact"
    unconfigured = endpoint(path, "GET")
    with pytest.raises(ApiProblem) as unavailable:
        await unconfigured(
            incident_id="incident-a",
            evidence_id="evidence-a",
            session=FakeSession(scalar_values=[evidence_row()]),
            principal=VIEWER,
        )
    assert unavailable.value.status_code == 503

    with pytest.raises(ApiProblem) as expired:
        await unconfigured(
            incident_id="incident-a",
            evidence_id="evidence-a",
            session=FakeSession(scalar_values=[evidence_row(expires_at=NOW)]),
            principal=VIEWER,
        )
    assert expired.value.status_code == 410

    mismatches = [
        artifact(artifact_id="artifact-other"),
        artifact(tenant_id="tenant-other"),
        artifact(incident_id="incident-other"),
        artifact(content_hash="b" * 64),
    ]
    for wrong in mismatches:
        mismatch = endpoint(
            path,
            "GET",
            artifact_storage=FakeArtifactStorage(ArtifactContent(wrong, b"{}")),
        )
        with pytest.raises(ApiProblem) as rejected:
            await mismatch(
                incident_id="incident-a",
                evidence_id="evidence-a",
                session=FakeSession(scalar_values=[evidence_row()]),
                principal=VIEWER,
            )
        assert rejected.value.status_code == 409


def command() -> ControlRequest:
    return ControlRequest(
        expected_version=1,
        reason="perform controlled action",
        correlation_id="correlation-api",
        causation_id="command-api",
    )


@pytest.mark.anyio
async def test_read_route_return_paths_and_pagination() -> None:
    list_route = endpoint("/api/v1/incidents", "GET")
    listed = await list_route(
        session=FakeSession(scalar_lists=[[row("incident-b"), row("incident-a")]]),
        principal=VIEWER,
        limit=1,
        cursor=None,
    )
    assert [item.id for item in listed.items] == ["incident-b"]
    assert listed.next_cursor is not None
    final_page = await list_route(
        session=FakeSession(scalar_lists=[[row("incident-a")]]),
        principal=VIEWER,
        limit=50,
        cursor=None,
    )
    assert final_page.next_cursor is None

    detail_route = endpoint("/api/v1/incidents/{incident_id}", "GET")
    detail = await detail_route(
        incident_id="incident-a",
        session=FakeSession(scalar_values=[row("incident-a")]),
        principal=VIEWER,
    )
    assert detail.id == "incident-a"
    with pytest.raises(HTTPException) as missing:
        await detail_route(
            incident_id="missing", session=FakeSession(scalar_values=[None]), principal=VIEWER
        )
    assert missing.value.status_code == 404


@pytest.mark.anyio
async def test_timeline_and_audit_route_return_paths() -> None:
    transition = IncidentTransitionRow(
        incident_id="incident-a",
        prior_state="DETECTED",
        new_state="TRIAGED",
        prior_version=1,
        new_version=2,
        actor_id="operator-api",
        reason="triage",
        correlation_id="correlation-api",
        causation_id="command-api",
        occurred_at=NOW,
    )
    cancellation = IncidentCancellationRequestRow(
        incident_id="incident-a",
        state_when_requested="TRIAGED",
        prior_version=2,
        new_version=3,
        disposition="CANCELLED",
        actor_id="operator-api",
        reason="cancel",
        correlation_id="correlation-api",
        causation_id="command-cancel",
        occurred_at=NOW,
    )
    timeline_route = endpoint("/api/v1/incidents/{incident_id}/timeline", "GET")
    timeline = await timeline_route(
        incident_id="incident-a",
        session=FakeSession(
            scalar_values=["incident-a"], scalar_lists=[[transition], [cancellation]]
        ),
        principal=VIEWER,
        limit=1,
        cursor=None,
    )
    assert timeline.items[0].kind == "transition"
    assert timeline.next_cursor is not None
    continued = await timeline_route(
        incident_id="incident-a",
        session=FakeSession(scalar_values=["incident-a"], scalar_lists=[[], []]),
        principal=VIEWER,
        limit=50,
        cursor="WzIsMF0",
    )
    assert continued.items == []
    for invalid_cursor in (
        "WyJub3QtYS12ZXJzaW9uIiwwXQ",
        "Wy0xLDBd",
        "WzEsIm5vdC1hLXJhbmsiXQ",
        "WzEsMl0",
    ):
        with pytest.raises(HTTPException) as invalid:
            await timeline_route(
                incident_id="incident-a",
                session=FakeSession(scalar_values=["incident-a"]),
                principal=VIEWER,
                limit=50,
                cursor=invalid_cursor,
            )
        assert invalid.value.status_code == 400
    with pytest.raises(HTTPException) as missing:
        await timeline_route(
            incident_id="missing",
            session=FakeSession(scalar_values=[None]),
            principal=VIEWER,
            limit=50,
            cursor=None,
        )
    assert missing.value.status_code == 404

    audit = AuditEventRow(
        sequence=10,
        id="audit-a",
        tenant_id="tenant-api",
        event_type="incident.transitioned",
        event_version=1,
        payload_schema_version="incident/v1",
        actor_id="operator-api",
        correlation_id="correlation-api",
        causation_id="command-api",
        target_type="incident.lifecycle",
        target_id="incident-a",
        request_hash="a" * 64,
        result_hash="b" * 64,
        occurred_at=NOW,
    )
    audit_route = endpoint("/api/v1/audit", "GET")
    page = await audit_route(
        session=FakeSession(scalar_lists=[[audit, audit]]),
        principal=VIEWER,
        limit=1,
        after_sequence=0,
    )
    assert page.items[0].sequence == 10
    assert page.next_after_sequence == 10


def idempotency_record(
    *, request_hash: str, response_body: dict[str, object] | None = None
) -> IdempotencyRecordRow:
    return IdempotencyRecordRow(
        tenant_id="tenant-api",
        actor_id="operator-api",
        operation="incident:start-investigation:incident-a",
        idempotency_key="key-a",
        request_hash=request_hash,
        response_status=200 if response_body is not None else None,
        response_body=response_body,
        created_at=NOW,
        completed_at=NOW if response_body is not None else None,
    )


@pytest.mark.anyio
async def test_control_route_success_paths() -> None:
    start = endpoint(
        "/api/v1/incidents/{incident_id}/controls/start-investigation",
        "POST",
        audit_ids=["audit-start"],
    )
    start_record = idempotency_record(request_hash="0" * 64)
    start_session = FakeSession(
        scalar_values=[
            1,
            start_record,
            row("incident-a"),
            row("incident-a", state="INVESTIGATING", version=2),
        ]
    )
    response = Response()
    result = await start(
        incident_id="incident-a",
        command=command(),
        idempotency_key="key-a",
        session=start_session,
        principal=OPERATOR,
        response=response,
    )
    assert result.incident.state == "INVESTIGATING"
    assert response.headers["Idempotency-Replayed"] == "false"
    assert start_record.response_body is not None

    cancel = endpoint(
        "/api/v1/incidents/{incident_id}/controls/cancel",
        "POST",
        audit_ids=["audit-cancel"],
    )
    cancel_record = idempotency_record(request_hash="0" * 64)
    cancel_session = FakeSession(
        scalar_values=[
            1,
            cancel_record,
            row("incident-a", state="EXECUTING"),
            row("incident-a", state="EXECUTING", version=2),
        ]
    )
    deferred = await cancel(
        incident_id="incident-a",
        command=command(),
        idempotency_key="key-a",
        session=cancel_session,
        principal=OPERATOR,
        response=Response(),
    )
    assert deferred.cancellation_disposition == "DEFERRED"


@pytest.mark.anyio
async def test_control_route_replay_conflict_incomplete_and_hidden_paths() -> None:
    route = endpoint("/api/v1/incidents/{incident_id}/controls/start-investigation", "POST")
    cmd = command()
    response_body: dict[str, object] = {
        "incident": {
            "id": "incident-a",
            "severity": "SEV2",
            "state": "INVESTIGATING",
            "version": 2,
            "opened_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
            "closed_at": None,
            "cancelled_at": None,
            "cancellation_requested_at": None,
        },
        "cancellation_disposition": None,
    }
    replay_record = idempotency_record(request_hash="placeholder", response_body=response_body)
    replay_session = FakeSession(scalar_values=[None, replay_record])

    # Capture the canonical request hash from the first conflict, then replay it.
    with pytest.raises(ApiProblem):
        await route(
            incident_id="incident-a",
            command=cmd,
            idempotency_key="key-a",
            session=replay_session,
            principal=OPERATOR,
            response=Response(),
        )
    import agentops_incident_commander.apps.api_v1 as api_v1

    expected_hash = api_v1._canonical_hash(
        {
            "operation": "start-investigation",
            "incident_id": "incident-a",
            "command": cmd.model_dump(mode="json"),
        }
    )
    replay_record.request_hash = expected_hash
    response = Response()
    replayed = await route(
        incident_id="incident-a",
        command=cmd,
        idempotency_key="key-a",
        session=FakeSession(scalar_values=[None, replay_record]),
        principal=OPERATOR,
        response=response,
    )
    assert replayed.incident.version == 2
    assert response.headers["Idempotency-Replayed"] == "true"

    incomplete = idempotency_record(request_hash=expected_hash)
    with pytest.raises(RuntimeError, match="has no response"):
        await route(
            incident_id="incident-a",
            command=cmd,
            idempotency_key="key-a",
            session=FakeSession(scalar_values=[None, incomplete]),
            principal=OPERATOR,
            response=Response(),
        )
    with pytest.raises(HTTPException) as hidden:
        await route(
            incident_id="incident-a",
            command=cmd,
            idempotency_key="key-a",
            session=FakeSession(
                scalar_values=[1, idempotency_record(request_hash=expected_hash), None]
            ),
            principal=OPERATOR,
            response=Response(),
        )
    assert hidden.value.status_code == 404


def test_default_identifier_is_valid() -> None:
    assert len(new_identifier()) == 32


def test_injected_session_factory_lifespan_does_not_own_engine() -> None:
    app = create_app(
        ApiSettings("postgresql+asyncpg://unused:unused@localhost/unused", "127.0.0.1", 8000),
        session_factory=cast(SessionFactory, lambda: None),
    )
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
