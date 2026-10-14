"""Fast API contract tests complementing PostgreSQL behavior tests."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import HTTPException, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from agentops_incident_commander.application import (
    ApprovalLifecycleChange,
    ApprovalReviewSnapshot,
    approval_review_snapshot_from_document,
)
from agentops_incident_commander.apps.api import create_app
from agentops_incident_commander.apps.api_errors import ApiProblem
from agentops_incident_commander.apps.api_v1 import (
    ApprovalDecisionRequest,
    ControlRequest,
    SessionFactory,
    _canonical_hash,
    _proposal_diff,
    build_api_v1_router,
    new_identifier,
)
from agentops_incident_commander.apps.config import ApiSettings
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    ApprovalId,
    Artifact,
    ArtifactContent,
    ArtifactExpiredError,
    ArtifactId,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceId,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    MaintenanceWindowStatus,
    ModelCallId,
    OpaqueIdentifier,
    PolicyAction,
    PolicyBlastRadius,
    PolicyDecision,
    PolicyEnvironment,
    PolicyEvaluationInput,
    PolicyOutcome,
    PolicyReason,
    PolicyReasonCode,
    Principal,
    RedactionStatus,
    RetentionClass,
    RiskLevel,
    Role,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.persistence.models import (
    ApprovalInvalidationRow,
    ApprovalReviewSnapshotRow,
    ApprovalRow,
    AuditEventRow,
    DiagnosisProgressRow,
    EvidenceRow,
    IdempotencyRecordRow,
    IncidentCancellationRequestRow,
    IncidentRow,
    IncidentTransitionRow,
)
from agentops_incident_commander.infrastructure.persistence.repositories import (
    ApprovalLifecycleRepository,
)
from agentops_incident_commander.workflows import (
    CounterEvidenceTreatment,
    DiagnosisDisposition,
    DiagnosisReport,
    DiagnosisReportRecord,
    RecoveryAction,
    RemediationFailureHandling,
    RemediationFailureRoute,
    RemediationProposal,
    RollbackPrerequisites,
    RollbackServiceParameters,
    RollbackVerificationConditions,
    RootCauseCandidate,
    diagnosis_report_fingerprint,
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
        self.scalar_statements: list[object] = []
        self.added: list[object] = []

    async def scalar(self, _: object) -> Any:
        return self.scalar_values.pop(0)

    async def scalars(self, statement: object) -> FakeScalars:
        self.scalar_statements.append(statement)
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
        service="orders",
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


def approval_rows(
    *, approval_id: str = "approval-api", independent: bool = True
) -> tuple[ApprovalRow, ApprovalReviewSnapshotRow]:
    proposed = RemediationProposal(
        schema_version="1.0.0",
        proposal_id=f"remediation-{approval_id}",
        proposal_version=1,
        incident_id="incident-approval-api",
        candidate_id="candidate-approval-api",
        evidence_gate_input_fingerprint="c" * 64,
        evidence_gate_decision_fingerprint="b" * 64,
        action=RecoveryAction.ROLLBACK_SERVICE,
        parameters=RollbackServiceParameters(
            service="orders",
            introducing_deployment_evidence_id="evidence-deployment",
        ),
        prerequisites=RollbackPrerequisites(current_version_evidence_id="evidence-current"),
        verification_conditions=RollbackVerificationConditions(
            max_error_rate_basis_points=100,
            max_p95_latency_ms=500,
            stability_window_seconds=300,
        ),
        failure_handling=RemediationFailureHandling(
            route=RemediationFailureRoute.HUMAN_HANDOFF,
            max_rediagnosis_attempts=0,
        ),
        risk_assumptions=("The current deployment is faulty.",),
    )
    value = PolicyEvaluationInput(
        tenant_id=TenantId("tenant-api"),
        incident_id=IncidentId("incident-approval-api"),
        proposal_id=OpaqueIdentifier(proposed.proposal_id),
        proposal_version=proposed.proposal_version,
        proposal_fingerprint=proposed.fingerprint,
        evidence_gate_decision_fingerprint=Sha256Digest(
            proposed.evidence_gate_decision_fingerprint
        ),
        requester_actor_id=ActorId("operator-approval-api"),
        requester_roles=frozenset({Role.OPERATOR}),
        environment=PolicyEnvironment.PRODUCTION,
        action=PolicyAction.ROLLBACK_SERVICE,
        service="orders",
        blast_radius=PolicyBlastRadius.SINGLE_SERVICE,
        maintenance_window=MaintenanceWindowStatus.ACTIVE,
        separation_of_duties_required=independent,
        requested_at=NOW,
    )
    decision = PolicyDecision(
        id=OpaqueIdentifier(f"policy-{approval_id}"),
        policy_version=SemanticVersion("1.0.0"),
        input_fingerprint=value.fingerprint,
        proposal_fingerprint=proposed.fingerprint,
        outcome=PolicyOutcome.APPROVAL_REQUIRED,
        risk_level=RiskLevel.HIGH if independent else RiskLevel.LOW,
        reasons=(
            PolicyReason(
                PolicyReasonCode.APPROVAL_REQUIRED,
                "Human approval is required before rollback execution.",
            ),
        ),
        evaluated_at=NOW,
        approval_ttl=timedelta(minutes=30),
    )
    snapshot = ApprovalReviewSnapshot(proposed, value, decision)
    approval = ApprovalRow(
        id=approval_id,
        tenant_id="tenant-api",
        incident_id=value.incident_id.value,
        proposal_id=value.proposal_id.value,
        proposal_version=value.proposal_version,
        proposal_fingerprint=value.proposal_fingerprint.value,
        policy_decision_id=decision.id.value,
        policy_decision_fingerprint=decision.fingerprint.value,
        policy_input_fingerprint=value.fingerprint.value,
        proposer_actor_id=value.requester_actor_id.value,
        risk_level=decision.risk_level.value,
        independent_approver_required=independent,
        status="PENDING",
        version=1,
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        decided_at=None,
        decided_by=None,
        decision_reason=None,
        schema_version="1.0.0",
    )
    review = ApprovalReviewSnapshotRow(
        approval_id=approval_id,
        tenant_id="tenant-api",
        incident_id=value.incident_id.value,
        snapshot=snapshot.document,
        snapshot_fingerprint=snapshot.fingerprint.value,
        created_at=NOW,
        schema_version=snapshot.schema_version,
    )
    return approval, review


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
async def test_session_exposes_only_server_derived_identity_and_authority() -> None:
    route = endpoint("/api/v1/session", "GET")
    principal = Principal(
        ActorId("operator-approver"),
        TenantId("tenant-api"),
        frozenset({Role.OPERATOR, Role.APPROVER}),
    )

    session = await route(principal=principal)

    assert session.model_dump() == {
        "actor_id": "operator-approver",
        "tenant_id": "tenant-api",
        "roles": ["APPROVER", "OPERATOR"],
        "permissions": [
            "approval:decide",
            "approved_action:execute",
            "audit:read",
            "evidence:read",
            "incident:read",
            "investigation:cancel",
            "investigation:start",
            "postmortem:edit",
            "remediation:request",
        ],
    }


@pytest.mark.anyio
async def test_approval_read_routes_resume_after_database_awaits() -> None:
    first, first_review = approval_rows(approval_id="approval-api-a")
    second, _ = approval_rows(approval_id="approval-api-b", independent=False)
    second.requested_at = NOW - timedelta(seconds=1)
    route = endpoint("/api/v1/approvals", "GET")
    approver = Principal(
        ActorId("approver-api"), TenantId("tenant-api"), frozenset({Role.APPROVER})
    )
    page = await route(
        session=FakeSession(
            scalar_values=[first],
            scalar_lists=[[first, second], []],
        ),
        principal=approver,
        limit=1,
        cursor=None,
        approval_status=None,
    )
    assert page.items[0].id == first.id
    assert page.next_cursor is not None
    continued = await route(
        session=FakeSession(
            scalar_values=[second],
            scalar_lists=[[second], []],
        ),
        principal=approver,
        limit=1,
        cursor=page.next_cursor,
        approval_status=None,
    )
    assert continued.items[0].id == second.id
    assert continued.items[0].separation_of_duties.code == "NOT_REQUIRED"
    assert continued.next_cursor is None

    detail_route = endpoint("/api/v1/approvals/{approval_id}", "GET")
    detail = await detail_route(
        approval_id=first.id,
        session=FakeSession(scalar_values=[first, first_review, None, None]),
        principal=approver,
    )
    assert detail.proposal["proposal_id"] == first.proposal_id
    with pytest.raises(HTTPException) as missing:
        await detail_route(
            approval_id="approval-missing",
            session=FakeSession(scalar_values=[None]),
            principal=approver,
        )
    assert missing.value.status_code == 404
    with pytest.raises(ApiProblem) as missing_snapshot:
        await detail_route(
            approval_id=first.id,
            session=FakeSession(scalar_values=[first, None]),
            principal=approver,
        )
    assert missing_snapshot.value.code == "APPROVAL_REVIEW_INTEGRITY_FAILED"

    changes = _proposal_diff(
        {"removed": 1, "changed": {"before": True}},
        {"added": 2, "changed": {"after": True}},
    )
    assert {change.path for change in changes} == {
        "$.added",
        "$.changed.after",
        "$.changed.before",
        "$.removed",
    }


@pytest.mark.anyio
async def test_approval_repository_rejects_corrupt_or_mismatched_review_snapshots() -> None:
    row_value, review = approval_rows(approval_id="approval-review-integrity")
    review.snapshot_fingerprint = "f" * 64
    repository = ApprovalLifecycleRepository(cast(Any, FakeSession(scalar_values=[review])))
    with pytest.raises(InvalidDomainValueError, match="integrity check failed"):
        await repository.get_review_snapshot(
            ApprovalId(row_value.id), tenant_id=TenantId("tenant-api")
        )

    lookup = ApprovalLifecycleRepository(cast(Any, FakeSession(scalar_values=[row_value])))
    approval = await lookup.get(ApprovalId(row_value.id), tenant_id=TenantId("tenant-api"))
    assert approval is not None
    _, other_review = approval_rows(approval_id="approval-other-review")
    other_snapshot = approval_review_snapshot_from_document(other_review.snapshot)
    audit = AuditEvent(
        id=AuditEventId("audit-review-integrity"),
        tenant_id=approval.tenant_id,
        type="approval.requested",
        event_version=1,
        payload_schema_version="approval/v1",
        actor_id=approval.proposer_actor_id,
        correlation_id=CorrelationId("correlation-review-integrity"),
        causation_id=CausationId("request-review-integrity"),
        target=AuditTarget("approval.record", OpaqueIdentifier(approval.id.value)),
        occurred_at=approval.requested_at,
        request_hash=approval.policy_decision_fingerprint,
        result_hash=approval.fingerprint,
    )
    mismatched = ApprovalLifecycleRepository(cast(Any, FakeSession(scalar_values=[None])))
    with pytest.raises(InvalidDomainValueError, match="does not match Approval"):
        await mismatched.apply(
            ApprovalLifecycleChange("requested", None, approval, other_snapshot),
            audit,
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
    assert response.headers["x-content-sha256"] == "a" * 64
    assert response.headers["x-content-schema-version"] == "1.0.0"
    assert response.headers["x-redaction-status"] == "REDACTED"
    assert response.headers["etag"] == f'"sha256:{"a" * 64}"'
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
    assert listed.items[0].service == "orders"
    assert listed.next_cursor is not None
    filtered_session = FakeSession(scalar_lists=[[row("incident-filtered")]])
    filtered = await list_route(
        session=filtered_session,
        principal=VIEWER,
        limit=50,
        cursor=None,
        severity=IncidentSeverity.SEV2,
        state=IncidentState.TRIAGED,
        service="orders",
    )
    assert [item.id for item in filtered.items] == ["incident-filtered"]
    statement = str(filtered_session.scalar_statements[0])
    assert "incidents.severity" in statement
    assert "incidents.state" in statement
    assert "incidents.service" in statement
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
async def test_investigation_route_handles_missing_empty_valid_and_corrupt_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agentops_incident_commander.apps.api_v1 as api_v1

    route = endpoint("/api/v1/incidents/{incident_id}/investigation", "GET")
    with pytest.raises(HTTPException) as missing:
        await route(
            incident_id="missing",
            session=FakeSession(scalar_values=[None]),
            principal=VIEWER,
        )
    assert missing.value.status_code == 404

    empty = await route(
        incident_id="incident-a",
        session=FakeSession(scalar_values=["incident-a", None]),
        principal=VIEWER,
    )
    assert empty.run is None

    progress_row = DiagnosisProgressRow(workflow_run_id="run-a")
    view = api_v1.InvestigationProgressView.model_validate(
        {
            "schema_version": "1.0.0",
            "workflow_run_id": "run-a",
            "graph_version": "1.0.0",
            "phase": "INVESTIGATING",
            "status": "ACTIVE",
            "budgets": {
                name: {"used": 0, "maximum": 1, "remaining": 1}
                for name in (
                    "steps",
                    "replans",
                    "tool_calls",
                    "model_calls",
                    "tokens",
                    "cost_nanounits",
                )
            },
            "plans": [],
            "replans": [],
            "checkpoint_sequence": 1,
            "error_code": None,
            "updated_at": NOW,
        }
    )
    monkeypatch.setattr(api_v1, "_investigation_progress_view", lambda _: view)
    visible = await route(
        incident_id="incident-a",
        session=FakeSession(scalar_values=["incident-a", progress_row]),
        principal=VIEWER,
    )
    assert visible.run == view

    def corrupt(_: DiagnosisProgressRow) -> api_v1.InvestigationProgressView:
        raise InvalidDomainValueError("corrupt progress")

    monkeypatch.setattr(api_v1, "_investigation_progress_view", corrupt)
    with pytest.raises(ApiProblem) as integrity:
        await route(
            incident_id="incident-a",
            session=FakeSession(scalar_values=["incident-a", progress_row]),
            principal=VIEWER,
        )
    assert integrity.value.status_code == 409
    assert integrity.value.code == "INVESTIGATION_PROGRESS_INTEGRITY_FAILED"


@pytest.mark.anyio
async def test_diagnosis_route_scopes_maps_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agentops_incident_commander.apps.api_v1 as api_v1

    route = endpoint("/api/v1/incidents/{incident_id}/diagnosis", "GET")
    with pytest.raises(HTTPException) as missing:
        await route(
            incident_id="missing",
            session=FakeSession(scalar_values=[None]),
            principal=VIEWER,
        )
    assert missing.value.status_code == 404

    diagnosis = DiagnosisReport(
        schema_version="1.0.0",
        incident_id="incident-a",
        disposition=DiagnosisDisposition.CANDIDATES,
        candidates=(
            RootCauseCandidate(
                candidate_id="candidate-a",
                rank=1,
                statement="Database pool exhaustion.",
                supporting_evidence_ids=("evidence-a",),
                counter_evidence_ids=(),
                counter_evidence_treatment=CounterEvidenceTreatment.NOT_APPLICABLE,
                missing_evidence=(),
                uncertainty="The sample window is bounded.",
                confidence_basis_points=8000,
            ),
        ),
        missing_evidence=(),
        explanation="One ranked candidate.",
    )
    report_record = DiagnosisReportRecord(
        tenant_id=TenantId("tenant-api"),
        workflow_run_id=WorkflowRunId("run-a"),
        model_call_id=ModelCallId("call-a"),
        report=diagnosis,
        report_fingerprint=diagnosis_report_fingerprint(diagnosis),
        produced_at=NOW,
    )
    gate = EvidenceGateDecision(
        incident_id=IncidentId("incident-a"),
        candidate_id="candidate-a",
        outcome=EvidenceGateOutcome.PASS,
        reasons=(),
        evaluated_evidence_ids=(EvidenceId("evidence-a"),),
        rules_version="1.1.0",
        input_fingerprint=Sha256Digest("b" * 64),
        evaluated_at=NOW,
        model_confidence_basis_points=8000,
    )

    class StubRepository:
        record: DiagnosisReportRecord | None = report_record
        error = False

        def __init__(self, _: object) -> None:
            pass

        async def latest(self, **_: object) -> DiagnosisReportRecord | None:
            if self.error:
                raise InvalidDomainValueError("corrupt")
            return self.record

        async def matching_gate_decisions(
            self, _: DiagnosisReportRecord
        ) -> tuple[EvidenceGateDecision, ...]:
            return (gate,)

    monkeypatch.setattr(api_v1, "DiagnosisReportRepository", StubRepository)
    visible = await route(
        incident_id="incident-a",
        session=FakeSession(scalar_values=["incident-a"]),
        principal=VIEWER,
    )
    assert visible.result is not None
    assert visible.result.candidates[0].gate is not None
    assert visible.result.candidates[0].gate.outcome == "PASS"
    assert visible.result.candidates[0].supporting_evidence_ids == ["evidence-a"]

    StubRepository.record = None
    empty = await route(
        incident_id="incident-a",
        session=FakeSession(scalar_values=["incident-a"]),
        principal=VIEWER,
    )
    assert empty.result is None

    StubRepository.error = True
    with pytest.raises(ApiProblem) as integrity:
        await route(
            incident_id="incident-a",
            session=FakeSession(scalar_values=["incident-a"]),
            principal=VIEWER,
        )
    assert integrity.value.status_code == 409
    assert integrity.value.code == "DIAGNOSIS_RESULT_INTEGRITY_FAILED"


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


def approval_command() -> ApprovalDecisionRequest:
    return ApprovalDecisionRequest(
        expected_version=AggregateVersion.initial().value,
        reason="Reviewed evidence and rollback scope.",
        correlation_id="correlation-approval-api",
        causation_id="decision-approval-api",
    )


def approval_idempotency_record(
    operation: str,
    approval_id: str,
    *,
    response_body: dict[str, object] | None = None,
    request_hash: str | None = None,
) -> IdempotencyRecordRow:
    command = approval_command()
    calculated = _canonical_hash(
        {
            "operation": operation,
            "approval_id": approval_id,
            "command": command.model_dump(mode="json"),
        }
    )
    return IdempotencyRecordRow(
        tenant_id="tenant-api",
        actor_id="approver-api",
        operation=f"approval:{operation}:{approval_id}",
        idempotency_key="approval-key",
        request_hash=calculated if request_hash is None else request_hash,
        response_status=200 if response_body is not None else None,
        response_body=response_body,
        created_at=NOW,
        completed_at=NOW if response_body is not None else None,
    )


@pytest.mark.anyio
async def test_approval_decision_routes_cover_success_replay_and_refusals() -> None:
    approver = Principal(
        ActorId("approver-api"), TenantId("tenant-api"), frozenset({Role.APPROVER})
    )
    command_value = approval_command()
    approve = endpoint(
        "/api/v1/approvals/{approval_id}/approve",
        "POST",
        audit_ids=["audit-approval-api"],
    )
    pending, _ = approval_rows()
    record = approval_idempotency_record("approve", pending.id)
    response = Response()
    result = await approve(
        approval_id=pending.id,
        command=command_value,
        idempotency_key="approval-key",
        session=FakeSession(
            scalar_values=[1, record, pending, None, pending, pending],
        ),
        principal=approver,
        response=response,
    )
    assert result.approval.status == "APPROVED"
    assert response.headers["Idempotency-Replayed"] == "false"
    assert record.response_body is not None

    replay_response = Response()
    replayed = await approve(
        approval_id="approval-api",
        command=command_value,
        idempotency_key="approval-key",
        session=FakeSession(scalar_values=[None, record]),
        principal=approver,
        response=replay_response,
    )
    assert replayed == result
    assert replay_response.headers["Idempotency-Replayed"] == "true"

    conflict = approval_idempotency_record("approve", "approval-api", request_hash="f" * 64)
    with pytest.raises(ApiProblem) as reused:
        await approve(
            approval_id="approval-api",
            command=command_value,
            idempotency_key="approval-key",
            session=FakeSession(scalar_values=[None, conflict]),
            principal=approver,
            response=Response(),
        )
    assert reused.value.code == "IDEMPOTENCY_CONFLICT"

    incomplete = approval_idempotency_record("approve", "approval-api")
    with pytest.raises(RuntimeError, match="no response"):
        await approve(
            approval_id="approval-api",
            command=command_value,
            idempotency_key="approval-key",
            session=FakeSession(scalar_values=[None, incomplete]),
            principal=approver,
            response=Response(),
        )

    missing_record = approval_idempotency_record("approve", "approval-missing")
    with pytest.raises(HTTPException) as missing:
        await approve(
            approval_id="approval-missing",
            command=command_value,
            idempotency_key="approval-key",
            session=FakeSession(scalar_values=[1, missing_record, None]),
            principal=approver,
            response=Response(),
        )
    assert missing.value.status_code == 404

    invalidated_pending, _ = approval_rows(approval_id="approval-invalidated")
    invalidated_record = approval_idempotency_record("approve", invalidated_pending.id)
    invalidation = ApprovalInvalidationRow(
        approval_id=invalidated_pending.id,
        tenant_id="tenant-api",
        incident_id=invalidated_pending.incident_id,
        approval_fingerprint="a" * 64,
        prior_proposal_fingerprint=invalidated_pending.proposal_fingerprint,
        replacement_proposal_id="remediation-replacement",
        replacement_proposal_version=2,
        replacement_proposal_fingerprint="d" * 64,
        replacement_material_fingerprint="e" * 64,
        replacement_proposal=None,
        invalidated_by="operator-approval-api",
        invalidated_at=NOW + timedelta(seconds=30),
        audit_event_id="audit-invalidation-api",
        schema_version="1.0.0",
    )
    with pytest.raises(ApiProblem) as invalidated:
        await approve(
            approval_id=invalidated_pending.id,
            command=command_value,
            idempotency_key="approval-key",
            session=FakeSession(
                scalar_values=[1, invalidated_record, invalidated_pending, invalidation]
            ),
            principal=approver,
            response=Response(),
        )
    assert invalidated.value.code == "APPROVAL_INVALIDATED"

    terminal, _ = approval_rows(approval_id="approval-terminal")
    terminal.status = "APPROVED"
    terminal.version = 2
    terminal.decided_at = NOW + timedelta(seconds=30)
    terminal.decided_by = "approver-other"
    terminal.decision_reason = "Previously approved."
    terminal_record = approval_idempotency_record("approve", terminal.id)
    with pytest.raises(ApiProblem) as state_conflict:
        await approve(
            approval_id=terminal.id,
            command=command_value,
            idempotency_key="approval-key",
            session=FakeSession(scalar_values=[1, terminal_record, terminal, None, terminal]),
            principal=approver,
            response=Response(),
        )
    assert state_conflict.value.code == "APPROVAL_STATE_CONFLICT"

    reject = endpoint(
        "/api/v1/approvals/{approval_id}/reject",
        "POST",
        audit_ids=["audit-reject-api"],
    )
    rejected_pending, _ = approval_rows(approval_id="approval-reject")
    rejected_record = approval_idempotency_record("reject", rejected_pending.id)
    rejected = await reject(
        approval_id=rejected_pending.id,
        command=command_value,
        idempotency_key="approval-key",
        session=FakeSession(
            scalar_values=[
                1,
                rejected_record,
                rejected_pending,
                None,
                rejected_pending,
                rejected_pending,
            ]
        ),
        principal=approver,
        response=Response(),
    )
    assert rejected.approval.status == "REJECTED"


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
            "service": "orders",
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
