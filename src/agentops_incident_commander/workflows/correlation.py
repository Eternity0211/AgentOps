"""Deterministic runtime wiring for the eight authoritative correlation boundaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.application.tool_gateway import (
    ToolCallRequest,
    ToolCallResult,
)
from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    Alert,
    Approval,
    ApprovalStatus,
    CausationId,
    CorrelationComponent,
    CorrelationEventId,
    CorrelationId,
    CorrelationLink,
    CorrelationTimeline,
    HealthVerificationDecision,
    Incident,
    IncidentId,
    InvalidDomainValueError,
    ModelCallStatus,
    ModelCallTrace,
    OpaqueIdentifier,
    TenantId,
    TraceId,
    WorkflowRunId,
    as_utc,
)

from .state import DiagnosisGraphState

CORRELATION_WORKFLOW_SCHEMA_VERSION = "1.0.0"
_INVESTIGATION_COMPONENTS = frozenset(
    {CorrelationComponent.GRAPH, CorrelationComponent.TOOL, CorrelationComponent.MODEL}
)
_TERMINAL_COMPONENTS = (
    CorrelationComponent.APPROVAL,
    CorrelationComponent.EXECUTION,
    CorrelationComponent.VERIFICATION,
)


class CorrelationLinkStore(Protocol):
    async def append(self, link: CorrelationLink) -> CorrelationLink: ...

    async def by_correlation(
        self,
        tenant_id: TenantId,
        incident_id: IncidentId,
        correlation_id: CorrelationId,
    ) -> CorrelationTimeline: ...


@dataclass(frozen=True, slots=True)
class CorrelationCursor:
    """Immutable resume token containing only validated content-free links."""

    timeline: CorrelationTimeline

    def __post_init__(self) -> None:
        _validate_runtime_sequence(self.timeline)

    @property
    def last(self) -> CorrelationLink:
        return self.timeline.links[-1]

    @property
    def tenant_id(self) -> TenantId:
        return self.timeline.tenant_id

    @property
    def incident_id(self) -> IncidentId:
        return self.timeline.incident_id

    @property
    def correlation_id(self) -> CorrelationId:
        return self.timeline.correlation_id


def _event_id(
    *,
    tenant_id: TenantId,
    incident_id: IncidentId,
    correlation_id: CorrelationId,
    component: CorrelationComponent,
    resource_id: OpaqueIdentifier,
) -> CorrelationEventId:
    document = {
        "component": component.value,
        "correlation_id": correlation_id.value,
        "incident_id": incident_id.value,
        "resource_id": resource_id.value,
        "schema_version": CORRELATION_WORKFLOW_SCHEMA_VERSION,
        "tenant_id": tenant_id.value,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return CorrelationEventId(f"correlation-{hashlib.sha256(encoded).hexdigest()}")


def _validate_runtime_sequence(timeline: CorrelationTimeline) -> None:
    components = tuple(link.component for link in timeline.links)
    if len(components) == 1:
        return
    if components[1] is not CorrelationComponent.INCIDENT:
        raise InvalidDomainValueError("runtime correlation must bind its Incident second")

    tail_start = next(
        (
            index
            for index, component in enumerate(components[2:], start=2)
            if component in _TERMINAL_COMPONENTS
        ),
        len(components),
    )
    investigation = components[2:tail_start]
    if any(component not in _INVESTIGATION_COMPONENTS for component in investigation):
        raise InvalidDomainValueError("runtime correlation investigation order is invalid")
    terminal = components[tail_start:]
    if terminal != _TERMINAL_COMPONENTS[: len(terminal)]:
        raise InvalidDomainValueError("runtime correlation safety-chain order is invalid")
    if terminal and frozenset(investigation) != _INVESTIGATION_COMPONENTS:
        raise InvalidDomainValueError(
            "runtime correlation requires graph, tool, and model before Approval"
        )


class IncidentCorrelationWorkflow:
    """Append typed boundary links without granting any execution authority."""

    def __init__(self, store: CorrelationLinkStore) -> None:
        self._store = store

    async def start(
        self,
        alert: Alert,
        incident: Incident,
        *,
        correlation_id: CorrelationId,
        alert_trace_id: TraceId,
        incident_trace_id: TraceId,
    ) -> CorrelationCursor:
        """Bind one normalized Alert root to its tenant-owned Incident."""
        if not isinstance(alert, Alert) or not isinstance(incident, Incident):
            raise InvalidDomainValueError("correlation start requires typed Alert and Incident")
        if alert.tenant_id != incident.tenant_id:
            raise InvalidDomainValueError("Alert and Incident correlation scope does not match")
        root = await self._store.append(
            self._link(
                tenant_id=incident.tenant_id,
                incident_id=incident.id,
                component=CorrelationComponent.ALERT,
                resource_id=alert.id,
                trace_id=alert_trace_id,
                correlation_id=correlation_id,
                causation_id=None,
                occurred_at=alert.received_at,
            )
        )
        bound = await self._store.append(
            self._link(
                tenant_id=incident.tenant_id,
                incident_id=incident.id,
                component=CorrelationComponent.INCIDENT,
                resource_id=incident.id,
                trace_id=incident_trace_id,
                correlation_id=correlation_id,
                causation_id=CausationId(root.event_id.value),
                occurred_at=incident.opened_at,
            )
        )
        return CorrelationCursor(CorrelationTimeline((root, bound)))

    async def resume(
        self,
        tenant_id: TenantId,
        incident_id: IncidentId,
        correlation_id: CorrelationId,
    ) -> CorrelationCursor:
        """Recover a validated cursor from durable storage after worker replacement."""
        return CorrelationCursor(
            await self._store.by_correlation(tenant_id, incident_id, correlation_id)
        )

    async def record_graph(
        self,
        cursor: CorrelationCursor,
        state: DiagnosisGraphState,
        *,
        trace_id: TraceId,
    ) -> CorrelationCursor:
        if not isinstance(state, DiagnosisGraphState):
            raise InvalidDomainValueError("graph correlation requires typed Diagnosis state")
        if (
            state.tenant_id != cursor.tenant_id.value
            or state.incident_id != cursor.incident_id.value
            or state.correlation_id != cursor.correlation_id.value
            or state.causation_id != cursor.last.event_id.value
        ):
            raise InvalidDomainValueError("Diagnosis graph correlation scope is inconsistent")
        return await self._append(
            cursor,
            CorrelationComponent.GRAPH,
            WorkflowRunId(state.workflow_run_id),
            trace_id,
            state.updated_at,
        )

    async def record_tool(
        self,
        cursor: CorrelationCursor,
        request: ToolCallRequest,
        result: ToolCallResult,
        *,
        trace_id: TraceId,
        completed_at: datetime,
    ) -> CorrelationCursor:
        if not isinstance(request, ToolCallRequest) or not isinstance(result, ToolCallResult):
            raise InvalidDomainValueError("tool correlation requires typed request and result")
        if (
            request.principal.tenant_id != cursor.tenant_id
            or request.incident_id != cursor.incident_id
            or request.correlation_id != cursor.correlation_id
            or request.causation_id.value != cursor.last.event_id.value
            or result.call_id != request.call_id
            or result.tool_name != request.tool_name
            or result.tool_version != request.tool_version
        ):
            raise InvalidDomainValueError("Tool Call correlation scope is inconsistent")
        return await self._append(
            cursor,
            CorrelationComponent.TOOL,
            request.call_id,
            trace_id,
            completed_at,
        )

    async def record_model(
        self,
        cursor: CorrelationCursor,
        trace: ModelCallTrace,
        *,
        trace_id: TraceId,
    ) -> CorrelationCursor:
        if not isinstance(trace, ModelCallTrace):
            raise InvalidDomainValueError("model correlation requires a typed Model Call trace")
        if (
            trace.tenant_id != cursor.tenant_id
            or trace.incident_id != cursor.incident_id
            or trace.correlation_id != cursor.correlation_id
            or trace.causation_id.value != cursor.last.event_id.value
            or trace.status is not ModelCallStatus.SUCCEEDED
            or trace.completed_at is None
        ):
            raise InvalidDomainValueError("Model Call correlation scope or status is inconsistent")
        return await self._append(
            cursor,
            CorrelationComponent.MODEL,
            trace.id,
            trace_id,
            trace.completed_at,
        )

    async def record_approval(
        self,
        cursor: CorrelationCursor,
        approval: Approval,
        *,
        trace_id: TraceId,
    ) -> CorrelationCursor:
        if (
            not isinstance(approval, Approval)
            or approval.tenant_id != cursor.tenant_id
            or approval.incident_id != cursor.incident_id
            or approval.status is not ApprovalStatus.APPROVED
            or approval.decided_at is None
        ):
            raise InvalidDomainValueError("Approval correlation scope or status is inconsistent")
        return await self._append(
            cursor,
            CorrelationComponent.APPROVAL,
            approval.id,
            trace_id,
            approval.decided_at,
        )

    async def record_execution(
        self,
        cursor: CorrelationCursor,
        execution: ActionExecution,
        *,
        trace_id: TraceId,
    ) -> CorrelationCursor:
        if (
            not isinstance(execution, ActionExecution)
            or execution.tenant_id != cursor.tenant_id
            or execution.incident_id != cursor.incident_id
            or execution.status is not ActionExecutionStatus.SUCCEEDED
            or execution.completed_at is None
        ):
            raise InvalidDomainValueError("execution correlation scope or status is inconsistent")
        return await self._append(
            cursor,
            CorrelationComponent.EXECUTION,
            execution.id,
            trace_id,
            execution.completed_at,
        )

    async def record_verification(
        self,
        cursor: CorrelationCursor,
        decision: HealthVerificationDecision,
        *,
        trace_id: TraceId,
    ) -> CorrelationCursor:
        if (
            not isinstance(decision, HealthVerificationDecision)
            or decision.tenant_id != cursor.tenant_id
            or decision.incident_id != cursor.incident_id
            or decision.action_execution_id.value != cursor.last.resource_id.value
        ):
            raise InvalidDomainValueError("verification correlation scope is inconsistent")
        result = await self._append(
            cursor,
            CorrelationComponent.VERIFICATION,
            decision.id,
            trace_id,
            decision.evaluated_at,
        )
        result.timeline.require_complete()
        return result

    async def _append(
        self,
        cursor: CorrelationCursor,
        component: CorrelationComponent,
        resource_id: OpaqueIdentifier,
        trace_id: TraceId,
        occurred_at: datetime,
    ) -> CorrelationCursor:
        _validate_next_component(cursor.timeline, component)
        stored = await self._store.append(
            self._link(
                tenant_id=cursor.tenant_id,
                incident_id=cursor.incident_id,
                component=component,
                resource_id=resource_id,
                trace_id=trace_id,
                correlation_id=cursor.correlation_id,
                causation_id=CausationId(cursor.last.event_id.value),
                occurred_at=occurred_at,
            )
        )
        return CorrelationCursor(CorrelationTimeline((*cursor.timeline.links, stored)))

    @staticmethod
    def _link(
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
        component: CorrelationComponent,
        resource_id: OpaqueIdentifier,
        trace_id: TraceId,
        correlation_id: CorrelationId,
        causation_id: CausationId | None,
        occurred_at: datetime,
    ) -> CorrelationLink:
        if not isinstance(trace_id, TraceId):
            raise InvalidDomainValueError("runtime correlation requires a typed Trace ID")
        return CorrelationLink(
            event_id=_event_id(
                tenant_id=tenant_id,
                incident_id=incident_id,
                correlation_id=correlation_id,
                component=component,
                resource_id=resource_id,
            ),
            tenant_id=tenant_id,
            incident_id=incident_id,
            component=component,
            resource_id=resource_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=as_utc(occurred_at),
        )


def _validate_next_component(
    timeline: CorrelationTimeline, component: CorrelationComponent
) -> None:
    components = tuple(link.component for link in timeline.links)
    if CorrelationComponent.VERIFICATION in components:
        raise InvalidDomainValueError("completed runtime correlation cannot be extended")
    if component in _INVESTIGATION_COMPONENTS:
        if any(item in _TERMINAL_COMPONENTS for item in components):
            raise InvalidDomainValueError("investigation correlation cannot follow Approval")
        return
    if component is CorrelationComponent.APPROVAL:
        if frozenset(components) & _INVESTIGATION_COMPONENTS != _INVESTIGATION_COMPONENTS:
            raise InvalidDomainValueError("Approval requires graph, tool, and model correlation")
        return
    if component is CorrelationComponent.EXECUTION:
        if components[-1] is not CorrelationComponent.APPROVAL:
            raise InvalidDomainValueError("execution correlation requires Approval")
        return
    if component is CorrelationComponent.VERIFICATION:
        if components[-1] is not CorrelationComponent.EXECUTION:
            raise InvalidDomainValueError("verification correlation requires execution")
        return
    raise InvalidDomainValueError("runtime correlation component cannot be appended directly")
