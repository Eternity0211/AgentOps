"""Durable LangGraph interrupt for proposal-bound human Approval."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentops_incident_commander.application.control_plane_observability import (
    NOOP_CONTROL_PLANE_OBSERVER,
    ControlPlaneComponent,
    ControlPlaneObservation,
    ControlPlaneObserver,
    ControlPlaneOperation,
    ControlPlaneOutcome,
    safely_record,
)
from agentops_incident_commander.domain import (
    Approval,
    ApprovalId,
    ApprovalInvalidation,
    ApprovalStatus,
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    WorkflowRunId,
    as_utc,
    utc_now,
)

APPROVAL_GRAPH_STATE_SCHEMA_VERSION = "1.1.0"
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")]


class ApprovalGraphPhase(StrEnum):
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class ApprovalWaitState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    state_schema_version: Literal["1.1.0"]
    graph_version: Version
    tenant_id: Identifier
    incident_id: Identifier
    workflow_run_id: Identifier
    correlation_id: Identifier
    causation_id: Identifier
    approval_id: Identifier
    proposal_fingerprint: Digest
    policy_decision_fingerprint: Digest
    phase: ApprovalGraphPhase
    error_code: Identifier | None = None
    checkpoint_sequence: int = Field(ge=0)
    updated_at: datetime

    @field_validator("phase", mode="before")
    @classmethod
    def restore_phase(cls, value: Any) -> Any:
        return ApprovalGraphPhase(value) if isinstance(value, str) else value

    @field_validator("updated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Approval graph timestamp must be timezone-aware")
        return value.astimezone(UTC)


class ApprovalResumeStore(Protocol):
    async def get(self, approval_id: ApprovalId, *, tenant_id: TenantId) -> Approval | None: ...

    async def get_invalidation(
        self,
        approval_id: ApprovalId,
        *,
        tenant_id: TenantId,
    ) -> ApprovalInvalidation | None: ...


@dataclass(frozen=True, slots=True)
class ApprovalRuntimeContext:
    approvals: ApprovalResumeStore
    clock: Callable[[], datetime] = field(default=utc_now)
    observer: ControlPlaneObserver = field(default=NOOP_CONTROL_PLANE_OBSERVER)


async def await_approval_node(
    state: ApprovalWaitState,
    runtime: Runtime[ApprovalRuntimeContext],
) -> dict[str, object]:
    if state.phase is not ApprovalGraphPhase.AWAITING_APPROVAL:
        raise InvalidDomainValueError("Approval interrupt requires awaiting state")
    started_at = as_utc(runtime.context.clock())
    try:
        response: Any = interrupt(
            {
                "kind": "APPROVAL_REQUIRED",
                "tenant_id": state.tenant_id,
                "incident_id": state.incident_id,
                "approval_id": state.approval_id,
                "proposal_fingerprint": state.proposal_fingerprint,
                "policy_decision_fingerprint": state.policy_decision_fingerprint,
            }
        )
    except GraphInterrupt:
        _observe_resume(
            state,
            runtime,
            outcome=ControlPlaneOutcome.PAUSED,
            started_at=started_at,
            route="AWAITING_APPROVAL",
            result_code="INTERRUPTED",
        )
        raise
    if response != {"action": "RECHECK"}:
        raise InvalidDomainValueError("Approval resume directive is invalid")
    tenant_id = TenantId(state.tenant_id)
    approval_id = ApprovalId(state.approval_id)
    approval = await runtime.context.approvals.get(approval_id, tenant_id=tenant_id)
    if approval is None:
        return _observed_transition(
            state,
            runtime,
            started_at,
            ApprovalGraphPhase.NEEDS_HUMAN,
            "APPROVAL_NOT_FOUND",
        )
    invalidation = await runtime.context.approvals.get_invalidation(
        approval_id,
        tenant_id=tenant_id,
    )
    if invalidation is not None:
        return _observed_transition(
            state,
            runtime,
            started_at,
            ApprovalGraphPhase.NEEDS_HUMAN,
            "APPROVAL_INVALIDATED",
        )
    if (
        approval.tenant_id != tenant_id
        or approval.incident_id.value != state.incident_id
        or approval.proposal_fingerprint != Sha256Digest(state.proposal_fingerprint)
        or approval.policy_decision_fingerprint != Sha256Digest(state.policy_decision_fingerprint)
    ):
        return _observed_transition(
            state,
            runtime,
            started_at,
            ApprovalGraphPhase.NEEDS_HUMAN,
            "APPROVAL_MISMATCH",
        )
    now = as_utc(runtime.context.clock())
    if now >= approval.expires_at or approval.status is ApprovalStatus.EXPIRED:
        return _observed_transition(
            state,
            runtime,
            started_at,
            ApprovalGraphPhase.NEEDS_HUMAN,
            "APPROVAL_EXPIRED",
        )
    if approval.status is ApprovalStatus.REJECTED:
        return _observed_transition(
            state,
            runtime,
            started_at,
            ApprovalGraphPhase.NEEDS_HUMAN,
            "APPROVAL_REJECTED",
        )
    if approval.status is ApprovalStatus.APPROVED:
        return _observed_transition(
            state,
            runtime,
            started_at,
            ApprovalGraphPhase.READY_TO_EXECUTE,
        )
    return _observed_transition(
        state,
        runtime,
        started_at,
        ApprovalGraphPhase.AWAITING_APPROVAL,
    )


def _observed_transition(
    state: ApprovalWaitState,
    runtime: Runtime[ApprovalRuntimeContext],
    started_at: datetime,
    phase: ApprovalGraphPhase,
    error_code: str | None = None,
) -> dict[str, object]:
    update = _transition(state, runtime, phase, error_code)
    _observe_resume(
        state,
        runtime,
        outcome=(
            ControlPlaneOutcome.RESUMED
            if phase is ApprovalGraphPhase.READY_TO_EXECUTE
            else (
                ControlPlaneOutcome.PAUSED
                if phase is ApprovalGraphPhase.AWAITING_APPROVAL
                else ControlPlaneOutcome.HANDED_OFF
            )
        ),
        started_at=started_at,
        route=phase.value,
        result_code=error_code or phase.value,
    )
    return update


def _observe_resume(
    state: ApprovalWaitState,
    runtime: Runtime[ApprovalRuntimeContext],
    *,
    outcome: ControlPlaneOutcome,
    started_at: datetime,
    route: str,
    result_code: str,
) -> None:
    finished_at = as_utc(runtime.context.clock())
    safely_record(
        runtime.context.observer,
        ControlPlaneObservation(
            component=ControlPlaneComponent.APPROVAL,
            operation=ControlPlaneOperation.APPROVAL_RESUME,
            outcome=outcome,
            occurred_at=finished_at,
            tenant_id=TenantId(state.tenant_id),
            incident_id=IncidentId(state.incident_id),
            correlation_id=CorrelationId(state.correlation_id),
            causation_id=CausationId(state.causation_id),
            operation_id=OpaqueIdentifier(
                "approval-resume-"
                + hashlib.sha256(
                    f"{state.approval_id}:{state.checkpoint_sequence}".encode()
                ).hexdigest()
            ),
            workflow_run_id=WorkflowRunId(state.workflow_run_id),
            duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
            route=route,
            result_code=result_code,
            subject_name="approval_wait",
            subject_version=state.graph_version,
        ),
    )


def _transition(
    state: ApprovalWaitState,
    runtime: Runtime[ApprovalRuntimeContext],
    phase: ApprovalGraphPhase,
    error_code: str | None = None,
) -> dict[str, object]:
    return {
        "phase": phase,
        "error_code": error_code,
        "checkpoint_sequence": state.checkpoint_sequence + 1,
        "updated_at": as_utc(runtime.context.clock()),
    }


def _route(state: ApprovalWaitState) -> str:
    return {
        ApprovalGraphPhase.AWAITING_APPROVAL: "await_approval",
        ApprovalGraphPhase.READY_TO_EXECUTE: END,
        ApprovalGraphPhase.NEEDS_HUMAN: END,
    }[state.phase]


def build_approval_graph(
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[
    ApprovalWaitState,
    ApprovalRuntimeContext,
    ApprovalWaitState,
    ApprovalWaitState,
]:
    graph = StateGraph(ApprovalWaitState, context_schema=ApprovalRuntimeContext)
    graph.add_node("await_approval", await_approval_node)
    graph.add_edge(START, "await_approval")
    graph.add_conditional_edges("await_approval", _route)
    return graph.compile(checkpointer=checkpointer)
