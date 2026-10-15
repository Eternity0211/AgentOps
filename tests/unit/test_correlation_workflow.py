"""Tests for deterministic runtime correlation across all authoritative boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import cast

import pytest

from agentops_incident_commander.application import ToolCallRequest, ToolCallResult
from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    ActionSnapshot,
    ActorId,
    AggregateVersion,
    Alert,
    AlertId,
    Approval,
    ApprovalId,
    ApprovalStatus,
    ArtifactId,
    CausationId,
    CorrelationComponent,
    CorrelationEventId,
    CorrelationId,
    CorrelationLink,
    CorrelationTimeline,
    EventReason,
    HealthVerificationDecision,
    HealthVerificationOutcome,
    HealthVerificationScenario,
    IdempotencyKey,
    Incident,
    IncidentId,
    IncidentSeverity,
    InvalidDomainValueError,
    ModelCallId,
    ModelCallStatus,
    ModelCallTrace,
    ModelMetering,
    ModelMeteringUnavailableReason,
    OpaqueIdentifier,
    PolicyEnvironment,
    Principal,
    PromptDefinition,
    PromptId,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptPurpose,
    PromptSchemaCompatibility,
    PromptTraceLink,
    ResolvedRollbackTarget,
    RiskLevel,
    Role,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    ToolCallId,
    TraceId,
    WorkflowRunId,
    correlation_link_fingerprint,
)
from agentops_incident_commander.workflows import (
    CORRELATION_WORKFLOW_SCHEMA_VERSION,
    CorrelationCursor,
    DiagnosisGraphState,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
    IncidentCorrelationWorkflow,
)

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
TENANT = TenantId("tenant-1")
INCIDENT_ID = IncidentId("incident-1")
CORRELATION = CorrelationId("correlation-1")


class MemoryStore:
    def __init__(self) -> None:
        self.links: list[CorrelationLink] = []

    async def append(self, link: CorrelationLink) -> CorrelationLink:
        for stored in self.links:
            if stored.event_id == link.event_id:
                if correlation_link_fingerprint(stored) != correlation_link_fingerprint(link):
                    raise InvalidDomainValueError("changed replay")
                return stored
        CorrelationTimeline((*self.links, link))
        self.links.append(link)
        return link

    async def by_correlation(
        self,
        tenant_id: TenantId,
        incident_id: IncidentId,
        correlation_id: CorrelationId,
    ) -> CorrelationTimeline:
        timeline = CorrelationTimeline(tuple(self.links))
        if (tenant_id, incident_id, correlation_id) != (
            timeline.tenant_id,
            timeline.incident_id,
            timeline.correlation_id,
        ):
            raise InvalidDomainValueError("scope mismatch")
        return timeline


def alert(*, tenant_id: TenantId = TENANT) -> Alert:
    return Alert(
        id=AlertId("alert-1"),
        tenant_id=tenant_id,
        environment="production",
        service="orders",
        rule="http-errors",
        severity=IncidentSeverity.SEV2,
        observed_at=NOW - timedelta(seconds=1),
        received_at=NOW,
    )


def incident(*, tenant_id: TenantId = TENANT) -> Incident:
    return Incident(
        id=INCIDENT_ID,
        tenant_id=tenant_id,
        severity=IncidentSeverity.SEV2,
        service="orders",
        opened_at=NOW + timedelta(seconds=1),
        updated_at=NOW + timedelta(seconds=1),
    )


def graph_state(cursor: CorrelationCursor) -> DiagnosisGraphState:
    return DiagnosisGraphState(
        state_schema_version="1.3.0",
        graph_version="1.0.0",
        tenant_id=TENANT.value,
        incident_id=INCIDENT_ID.value,
        workflow_run_id="workflow-1",
        correlation_id=CORRELATION.value,
        causation_id=cursor.last.event_id.value,
        phase=GraphPhase.INVESTIGATING,
        budgets=GraphBudgetState(
            max_steps=4,
            used_steps=1,
            max_replans=1,
            used_replans=0,
            max_tool_calls=4,
            used_tool_calls=0,
            max_model_calls=4,
            used_model_calls=0,
            max_tokens=100,
            used_tokens=0,
            max_cost_nanounits=100,
            used_cost_nanounits=0,
        ),
        prompt=GraphPromptReference(
            prompt_id="diagnosis",
            version="1.0.0",
            content_fingerprint="a" * 64,
        ),
        checkpoint_sequence=1,
        updated_at=NOW + timedelta(seconds=2),
    )


def tool_call(cursor: CorrelationCursor) -> tuple[ToolCallRequest, ToolCallResult]:
    request = ToolCallRequest.from_mapping(
        call_id=ToolCallId("tool-1"),
        tool_name="query_metrics",
        tool_version=SemanticVersion("1.0.0"),
        incident_id=INCIDENT_ID,
        workflow_run_id=WorkflowRunId("workflow-1"),
        principal=Principal(ActorId("worker-1"), TENANT, frozenset({Role.VIEWER})),
        correlation_id=CORRELATION,
        causation_id=CausationId(cursor.last.event_id.value),
        arguments={"service": "orders"},
    )
    result_json = json.dumps({"items": []}, sort_keys=True, separators=(",", ":"))
    result = ToolCallResult(
        call_id=request.call_id,
        tool_name=request.tool_name,
        tool_version=request.tool_version,
        attempts=1,
        result_json=result_json,
        content_hash=Sha256Digest("b" * 64),
    )
    return request, result


def prompt() -> PromptDefinition:
    return PromptDefinition.create(
        prompt_id=PromptId("diagnosis"),
        version=SemanticVersion("1.0.0"),
        purpose=PromptPurpose.DIAGNOSIS,
        content="Use evidence only.",
        model_parameters=PromptModelParameters("mock", "model-v1", 0, 10_000, 100, 1),
        schema_compatibility=PromptSchemaCompatibility(
            SemanticVersion("1.0.0"), SemanticVersion("1.0.0")
        ),
        trace=PromptTraceLink(
            ActorId("admin"), CorrelationId("prompt-correlation"), CausationId("prompt-cause"), NOW
        ),
        status=PromptLifecycleStatus.ACTIVE,
    )


def model_trace(cursor: CorrelationCursor, *, succeeded: bool = True) -> ModelCallTrace:
    started = ModelCallTrace.start(
        call_id=ModelCallId("model-1"),
        tenant_id=TENANT,
        incident_id=INCIDENT_ID,
        workflow_run_id=WorkflowRunId("workflow-1"),
        node="diagnosis.hypothesis",
        attempt=1,
        prompt=prompt(),
        request_hash=Sha256Digest("c" * 64),
        correlation_id=CORRELATION,
        causation_id=CausationId(cursor.last.event_id.value),
        started_at=NOW + timedelta(seconds=3),
    )
    if not succeeded:
        return started
    return started.finish(
        status=ModelCallStatus.SUCCEEDED,
        completed_at=NOW + timedelta(seconds=4),
        metering=ModelMetering(None, None, ModelMeteringUnavailableReason.PROVIDER_DID_NOT_RETURN),
        response_hash=Sha256Digest("d" * 64),
    )


def approval(*, status: ApprovalStatus = ApprovalStatus.APPROVED) -> Approval:
    decided = status is not ApprovalStatus.PENDING
    return Approval(
        id=ApprovalId("approval-1"),
        tenant_id=TENANT,
        incident_id=INCIDENT_ID,
        proposal_id=OpaqueIdentifier("proposal-1"),
        proposal_version=1,
        proposal_fingerprint=Sha256Digest("e" * 64),
        policy_decision_id=OpaqueIdentifier("policy-1"),
        policy_decision_fingerprint=Sha256Digest("f" * 64),
        policy_input_fingerprint=Sha256Digest("1" * 64),
        proposer_actor_id=ActorId("operator-1"),
        risk_level=RiskLevel.HIGH,
        independent_approver_required=True,
        status=status,
        version=AggregateVersion(2 if decided else 1),
        requested_at=NOW + timedelta(seconds=4),
        expires_at=NOW + timedelta(minutes=10),
        decided_at=NOW + timedelta(seconds=5) if decided else None,
        decided_by=ActorId("approver-1") if decided else None,
        decision_reason=EventReason("Approved safely.") if decided else None,
    )


def execution(*, succeeded: bool = True) -> ActionExecution:
    target = ResolvedRollbackTarget(
        tenant_id=TENANT,
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=OpaqueIdentifier("orders-target"),
        expected_current_version=SemanticVersion("2.0.0"),
        stable_version=SemanticVersion("1.0.0"),
    )
    before = ActionSnapshot(
        artifact_id=ArtifactId("before"),
        tenant_id=TENANT,
        incident_id=INCIDENT_ID,
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=target.target_reference,
        deployed_version=target.expected_current_version,
        observed_at=NOW + timedelta(seconds=5),
        content_hash=Sha256Digest("2" * 64),
    )
    started = ActionExecution(
        id=OpaqueIdentifier("execution-1"),
        tenant_id=TENANT,
        incident_id=INCIDENT_ID,
        approval_id=ApprovalId("approval-1"),
        idempotency_key=IdempotencyKey("rollback-1"),
        actor_id=ActorId("operator-1"),
        proposal_fingerprint=Sha256Digest("e" * 64),
        policy_decision_fingerprint=Sha256Digest("f" * 64),
        target=target,
        before_snapshot=before,
        status=ActionExecutionStatus.STARTED,
        version=AggregateVersion(1),
        started_at=NOW + timedelta(seconds=5),
    )
    if not succeeded:
        return started
    after = replace(
        before,
        artifact_id=ArtifactId("after"),
        deployed_version=target.stable_version,
        observed_at=NOW + timedelta(seconds=6),
        content_hash=Sha256Digest("3" * 64),
    )
    return started.succeed(after_snapshot=after, at=NOW + timedelta(seconds=6))


def verification(action: ActionExecution) -> HealthVerificationDecision:
    return HealthVerificationDecision(
        id=OpaqueIdentifier("verification-1"),
        tenant_id=TENANT,
        incident_id=INCIDENT_ID,
        action_execution_id=action.id,
        scenario=HealthVerificationScenario.RELEASE_HTTP_500,
        outcome=HealthVerificationOutcome.PASS,
        reasons=(),
        criteria_fingerprint=Sha256Digest("4" * 64),
        observation_fingerprint=Sha256Digest("5" * 64),
        execution_fingerprint=action.fingerprint,
        input_fingerprint=Sha256Digest("6" * 64),
        evaluated_at=NOW + timedelta(seconds=7),
    )


def traces() -> list[TraceId]:
    return [TraceId(f"{index:032x}") for index in range(1, 9)]


async def started_workflow() -> tuple[IncidentCorrelationWorkflow, MemoryStore, CorrelationCursor]:
    store = MemoryStore()
    workflow = IncidentCorrelationWorkflow(store)
    cursor = await workflow.start(
        alert(),
        incident(),
        correlation_id=CORRELATION,
        alert_trace_id=traces()[0],
        incident_trace_id=traces()[1],
    )
    return workflow, store, cursor


@pytest.mark.anyio
async def test_complete_runtime_chain_is_typed_replay_safe_and_resumable() -> None:
    workflow, store, cursor = await started_workflow()
    trace_ids = traces()
    cursor = await workflow.record_graph(cursor, graph_state(cursor), trace_id=trace_ids[2])
    request, result = tool_call(cursor)
    cursor = await workflow.record_tool(
        cursor,
        request,
        result,
        trace_id=trace_ids[3],
        completed_at=NOW + timedelta(seconds=3),
    )
    cursor = await workflow.record_model(cursor, model_trace(cursor), trace_id=trace_ids[4])
    cursor = await workflow.record_approval(cursor, approval(), trace_id=trace_ids[5])
    action = execution()
    cursor = await workflow.record_execution(cursor, action, trace_id=trace_ids[6])
    cursor = await workflow.record_verification(cursor, verification(action), trace_id=trace_ids[7])

    assert tuple(link.component for link in cursor.timeline.links) == tuple(CorrelationComponent)
    assert tuple(link.trace_id for link in cursor.timeline.links) == tuple(trace_ids)
    assert len({link.event_id for link in cursor.timeline.links}) == 8
    assert all(
        child.causation_id == CausationId(parent.event_id.value)
        for parent, child in pairwise(cursor.timeline.links)
    )
    assert await workflow.resume(TENANT, INCIDENT_ID, CORRELATION) == cursor
    assert len(store.links) == 8
    with pytest.raises(InvalidDomainValueError, match="cannot be extended"):
        await workflow.record_graph(cursor, graph_state(cursor), trace_id=trace_ids[2])


@pytest.mark.anyio
async def test_start_replays_deterministic_events_and_rejects_invalid_inputs() -> None:
    workflow, store, cursor = await started_workflow()
    replayed = await workflow.start(
        alert(),
        incident(),
        correlation_id=CORRELATION,
        alert_trace_id=traces()[0],
        incident_trace_id=traces()[1],
    )
    assert replayed == cursor
    assert len(store.links) == 2

    with pytest.raises(InvalidDomainValueError, match="typed Alert and Incident"):
        await workflow.start(
            cast(Alert, object()),
            incident(),
            correlation_id=CORRELATION,
            alert_trace_id=traces()[0],
            incident_trace_id=traces()[1],
        )
    with pytest.raises(InvalidDomainValueError, match="scope does not match"):
        await IncidentCorrelationWorkflow(MemoryStore()).start(
            alert(tenant_id=TenantId("tenant-2")),
            incident(),
            correlation_id=CORRELATION,
            alert_trace_id=traces()[0],
            incident_trace_id=traces()[1],
        )
    with pytest.raises(InvalidDomainValueError, match="typed Trace ID"):
        await IncidentCorrelationWorkflow(MemoryStore()).start(
            alert(),
            incident(),
            correlation_id=CORRELATION,
            alert_trace_id=cast(TraceId, "bad"),
            incident_trace_id=traces()[1],
        )


@pytest.mark.anyio
async def test_investigation_boundaries_reject_untyped_mismatched_or_nonterminal_data() -> None:
    workflow, _, cursor = await started_workflow()
    with pytest.raises(InvalidDomainValueError, match="typed Diagnosis state"):
        await workflow.record_graph(
            cursor, cast(DiagnosisGraphState, object()), trace_id=traces()[2]
        )
    with pytest.raises(InvalidDomainValueError, match="graph correlation scope"):
        await workflow.record_graph(
            cursor,
            graph_state(cursor).model_copy(update={"correlation_id": "other"}),
            trace_id=traces()[2],
        )
    cursor = await workflow.record_graph(cursor, graph_state(cursor), trace_id=traces()[2])

    request, result = tool_call(cursor)
    with pytest.raises(InvalidDomainValueError, match="typed request and result"):
        await workflow.record_tool(
            cursor,
            request,
            cast(ToolCallResult, object()),
            trace_id=traces()[3],
            completed_at=NOW + timedelta(seconds=3),
        )
    with pytest.raises(InvalidDomainValueError, match="Tool Call correlation scope"):
        await workflow.record_tool(
            cursor,
            replace(request, causation_id=CausationId("other")),
            result,
            trace_id=traces()[3],
            completed_at=NOW + timedelta(seconds=3),
        )
    cursor = await workflow.record_tool(
        cursor,
        request,
        result,
        trace_id=traces()[3],
        completed_at=NOW + timedelta(seconds=3),
    )

    with pytest.raises(InvalidDomainValueError, match="typed Model Call"):
        await workflow.record_model(cursor, cast(ModelCallTrace, object()), trace_id=traces()[4])
    with pytest.raises(InvalidDomainValueError, match="scope or status"):
        await workflow.record_model(
            cursor, model_trace(cursor, succeeded=False), trace_id=traces()[4]
        )


@pytest.mark.anyio
async def test_safety_boundaries_reject_missing_prerequisites_scope_and_status() -> None:
    workflow, _, cursor = await started_workflow()
    with pytest.raises(InvalidDomainValueError, match="graph, tool, and model"):
        await workflow.record_approval(cursor, approval(), trace_id=traces()[5])

    cursor = await workflow.record_graph(cursor, graph_state(cursor), trace_id=traces()[2])
    request, result = tool_call(cursor)
    cursor = await workflow.record_tool(
        cursor,
        request,
        result,
        trace_id=traces()[3],
        completed_at=NOW + timedelta(seconds=3),
    )
    cursor = await workflow.record_model(cursor, model_trace(cursor), trace_id=traces()[4])
    with pytest.raises(InvalidDomainValueError, match="Approval correlation"):
        await workflow.record_approval(
            cursor, approval(status=ApprovalStatus.PENDING), trace_id=traces()[5]
        )
    cursor = await workflow.record_approval(cursor, approval(), trace_id=traces()[5])

    with pytest.raises(InvalidDomainValueError, match="investigation correlation"):
        await workflow.record_graph(cursor, graph_state(cursor), trace_id=traces()[2])
    with pytest.raises(InvalidDomainValueError, match="execution correlation scope"):
        await workflow.record_execution(cursor, execution(succeeded=False), trace_id=traces()[6])
    action = execution()
    cursor = await workflow.record_execution(cursor, action, trace_id=traces()[6])

    with pytest.raises(InvalidDomainValueError, match="verification correlation scope"):
        await workflow.record_verification(
            cursor,
            replace(verification(action), action_execution_id=OpaqueIdentifier("other")),
            trace_id=traces()[7],
        )


def raw_link(
    component: CorrelationComponent,
    index: int,
    *,
    cause: int | None,
) -> CorrelationLink:
    return CorrelationLink(
        event_id=CorrelationEventId(f"raw-event-{index}"),
        tenant_id=TENANT,
        incident_id=INCIDENT_ID,
        component=component,
        resource_id=OpaqueIdentifier(f"raw-resource-{index}"),
        trace_id=TraceId(f"{index:032x}"),
        correlation_id=CORRELATION,
        causation_id=None if cause is None else CausationId(f"raw-event-{cause}"),
        occurred_at=NOW + timedelta(seconds=index),
    )


@pytest.mark.parametrize(
    ("components", "message"),
    [
        ((CorrelationComponent.ALERT, CorrelationComponent.GRAPH), "Incident second"),
        (
            (
                CorrelationComponent.ALERT,
                CorrelationComponent.INCIDENT,
                CorrelationComponent.INCIDENT,
            ),
            "investigation order",
        ),
        (
            (
                CorrelationComponent.ALERT,
                CorrelationComponent.INCIDENT,
                CorrelationComponent.APPROVAL,
            ),
            "requires graph, tool, and model",
        ),
        (
            (
                CorrelationComponent.ALERT,
                CorrelationComponent.INCIDENT,
                CorrelationComponent.GRAPH,
                CorrelationComponent.APPROVAL,
                CorrelationComponent.MODEL,
            ),
            "safety-chain order",
        ),
    ],
)
def test_cursor_rejects_invalid_runtime_sequence(
    components: tuple[CorrelationComponent, ...], message: str
) -> None:
    links = tuple(
        raw_link(component, index, cause=None if index == 1 else index - 1)
        for index, component in enumerate(components, start=1)
    )
    with pytest.raises(InvalidDomainValueError, match=message):
        CorrelationCursor(CorrelationTimeline(links))


def test_alert_root_cursor_is_a_valid_partial_resume_point() -> None:
    cursor = CorrelationCursor(
        CorrelationTimeline((raw_link(CorrelationComponent.ALERT, 1, cause=None),))
    )
    assert cursor.last.component is CorrelationComponent.ALERT


@pytest.mark.anyio
async def test_direct_append_rejects_execution_and_verification_without_predecessor() -> None:
    workflow, _, cursor = await started_workflow()
    with pytest.raises(InvalidDomainValueError, match="requires Approval"):
        await workflow._append(
            cursor,
            CorrelationComponent.EXECUTION,
            OpaqueIdentifier("execution"),
            traces()[6],
            NOW + timedelta(seconds=6),
        )
    with pytest.raises(InvalidDomainValueError, match="requires execution"):
        await workflow._append(
            cursor,
            CorrelationComponent.VERIFICATION,
            OpaqueIdentifier("verification"),
            traces()[7],
            NOW + timedelta(seconds=7),
        )
    with pytest.raises(InvalidDomainValueError, match="cannot be appended directly"):
        await workflow._append(
            cursor,
            CorrelationComponent.INCIDENT,
            OpaqueIdentifier("incident"),
            traces()[1],
            NOW + timedelta(seconds=2),
        )


def test_workflow_schema_version_is_explicit() -> None:
    assert CORRELATION_WORKFLOW_SCHEMA_VERSION == "1.0.0"
