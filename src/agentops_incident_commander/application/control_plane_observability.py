"""Typed, content-free control-plane observability contract."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from agentops_incident_commander.domain import (
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    ModelMetering,
    OpaqueIdentifier,
    TenantId,
    WorkflowRunId,
    as_utc,
)

CONTROL_PLANE_OBSERVATION_SCHEMA_VERSION = "1.0"
_BOUNDED_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
logger = logging.getLogger("agentops.control_plane.observability")


class ControlPlaneComponent(StrEnum):
    DIAGNOSIS_GRAPH = "DIAGNOSIS_GRAPH"
    MODEL = "MODEL"
    TOOL = "TOOL"
    EVIDENCE_GATE = "EVIDENCE_GATE"
    CHECKPOINT = "CHECKPOINT"
    JOB_LEASE = "JOB_LEASE"
    APPROVAL = "APPROVAL"
    RECOVERY_EXECUTION = "RECOVERY_EXECUTION"
    VERIFICATION = "VERIFICATION"
    FAILURE_ROUTE = "FAILURE_ROUTE"
    REVERSIBILITY_GUARD = "REVERSIBILITY_GUARD"


class ControlPlaneOperation(StrEnum):
    GRAPH_LOAD_CONTEXT = "GRAPH_LOAD_CONTEXT"
    GRAPH_PLAN = "GRAPH_PLAN"
    GRAPH_EXECUTE_READ_TOOLS = "GRAPH_EXECUTE_READ_TOOLS"
    GRAPH_PERSIST_EVIDENCE = "GRAPH_PERSIST_EVIDENCE"
    GRAPH_HYPOTHESIS = "GRAPH_HYPOTHESIS"
    EVIDENCE_GATE_EVALUATE = "EVIDENCE_GATE_EVALUATE"
    GRAPH_HUMAN_HANDOFF = "GRAPH_HUMAN_HANDOFF"
    MODEL_CALL = "MODEL_CALL"
    TOOL_CALL = "TOOL_CALL"
    CHECKPOINT_SAVE = "CHECKPOINT_SAVE"
    CHECKPOINT_RESTORE = "CHECKPOINT_RESTORE"
    JOB_ENQUEUE = "JOB_ENQUEUE"
    JOB_CLAIM = "JOB_CLAIM"
    JOB_HEARTBEAT = "JOB_HEARTBEAT"
    JOB_COMPLETE = "JOB_COMPLETE"
    JOB_FAIL = "JOB_FAIL"
    JOB_STALE_RECOVERY = "JOB_STALE_RECOVERY"
    APPROVAL_REQUEST = "APPROVAL_REQUEST"
    APPROVAL_DECIDE = "APPROVAL_DECIDE"
    APPROVAL_EXPIRE = "APPROVAL_EXPIRE"
    APPROVAL_RESUME = "APPROVAL_RESUME"
    RECOVERY_EXECUTE = "RECOVERY_EXECUTE"
    HEALTH_VERIFY = "HEALTH_VERIFY"
    VERIFICATION_FAILURE_ROUTE = "VERIFICATION_FAILURE_ROUTE"
    FUTURE_INVERSE_GUARD = "FUTURE_INVERSE_GUARD"


class ControlPlaneOutcome(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    REFUSED = "REFUSED"
    RETRYING = "RETRYING"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    PASSED = "PASSED"
    HANDED_OFF = "HANDED_OFF"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    REPLAYED = "REPLAYED"


@dataclass(frozen=True, slots=True)
class ControlPlaneObservation:
    """One bounded operation observation; payload bodies are not representable."""

    component: ControlPlaneComponent
    operation: ControlPlaneOperation
    outcome: ControlPlaneOutcome
    occurred_at: datetime
    tenant_id: TenantId
    incident_id: IncidentId
    correlation_id: CorrelationId
    causation_id: CausationId
    operation_id: OpaqueIdentifier
    workflow_run_id: WorkflowRunId | None = None
    duration_ms: int | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    route: str | None = None
    result_code: str | None = None
    subject_name: str | None = None
    subject_version: str | None = None
    model_metering: ModelMetering | None = None
    schema_version: str = CONTROL_PLANE_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.component, ControlPlaneComponent) or not isinstance(
            self.operation, ControlPlaneOperation
        ):
            raise InvalidDomainValueError("control-plane component and operation must be typed")
        if not isinstance(self.outcome, ControlPlaneOutcome):
            raise InvalidDomainValueError("control-plane outcome must be typed")
        for identity, expected in (
            (self.tenant_id, TenantId),
            (self.incident_id, IncidentId),
            (self.correlation_id, CorrelationId),
            (self.causation_id, CausationId),
            (self.operation_id, OpaqueIdentifier),
        ):
            if not isinstance(identity, expected):
                raise InvalidDomainValueError("control-plane observation identity is invalid")
        if self.workflow_run_id is not None and not isinstance(self.workflow_run_id, WorkflowRunId):
            raise InvalidDomainValueError("control-plane workflow identity is invalid")
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))
        if self.duration_ms is not None and (
            not isinstance(self.duration_ms, int)
            or isinstance(self.duration_ms, bool)
            or self.duration_ms < 0
            or self.duration_ms > 86_400_000
        ):
            raise InvalidDomainValueError("control-plane duration must be bounded milliseconds")
        if self.outcome is ControlPlaneOutcome.STARTED and self.duration_ms is not None:
            raise InvalidDomainValueError("started observation cannot have terminal duration")
        if self.outcome is not ControlPlaneOutcome.STARTED and self.duration_ms is None:
            raise InvalidDomainValueError("terminal observation requires duration")
        if self.max_attempts is not None and self.attempt is None:
            raise InvalidDomainValueError("maximum attempts require a current attempt")
        if self.attempt is not None and (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt < 1
            or self.attempt > 128
        ):
            raise InvalidDomainValueError("control-plane attempt bounds are invalid")
        if self.max_attempts is not None:
            assert self.attempt is not None
            if (
                not isinstance(self.max_attempts, int)
                or isinstance(self.max_attempts, bool)
                or self.max_attempts < self.attempt
                or self.max_attempts > 128
            ):
                raise InvalidDomainValueError("control-plane attempt bounds are invalid")
        for value, field_name in (
            (self.route, "route"),
            (self.result_code, "result code"),
            (self.subject_name, "subject name"),
            (self.subject_version, "subject version"),
        ):
            if value is not None and (
                not isinstance(value, str) or _BOUNDED_COMPONENT.fullmatch(value) is None
            ):
                raise InvalidDomainValueError(f"control-plane {field_name} is invalid")
        if self.model_metering is not None and not isinstance(self.model_metering, ModelMetering):
            raise InvalidDomainValueError("control-plane model metering is invalid")
        if (
            self.model_metering is not None
            and self.operation is not ControlPlaneOperation.MODEL_CALL
        ):
            raise InvalidDomainValueError("model metering belongs only to model observations")
        if self.schema_version != CONTROL_PLANE_OBSERVATION_SCHEMA_VERSION:
            raise InvalidDomainValueError("control-plane observation schema is unsupported")


class ControlPlaneObserver(Protocol):
    """Best-effort output port; implementations must not become execution authority."""

    def record(self, observation: ControlPlaneObservation) -> None: ...


class NullControlPlaneObserver:
    def record(self, observation: ControlPlaneObservation) -> None:
        return None


NOOP_CONTROL_PLANE_OBSERVER = NullControlPlaneObserver()


def safely_record(
    observer: ControlPlaneObserver,
    observation: ControlPlaneObservation,
) -> None:
    """Keep telemetry failures from changing authoritative workflow behavior."""
    try:
        observer.record(observation)
    except Exception:
        logger.warning(
            "control_plane_observation_failed component=%s operation=%s",
            observation.component.value,
            observation.operation.value,
        )


def utc_observation_time() -> datetime:
    """Return an explicitly UTC timestamp for adapters without a domain clock."""
    return datetime.now(UTC)
