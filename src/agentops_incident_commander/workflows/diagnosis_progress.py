"""Bounded, content-safe projections for Diagnosis workflow progress."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .diagnosis import InvestigationPlan
from .state import DiagnosisGraphState, GraphBudgetState, GraphPhase

DIAGNOSIS_PROGRESS_SCHEMA_VERSION: Final[Literal["1.0.0"]] = "1.0.0"
MAX_PLAN_ATTEMPTS = 17
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_TOOL_PATTERN = r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"
_VERSION_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
_HASH_PATTERN = r"^[0-9a-f]{64}$"

Identifier = Annotated[str, Field(pattern=_ID_PATTERN)]
Digest = Annotated[str, Field(pattern=_HASH_PATTERN)]


class StrictProgressModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ToolProgressStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DiagnosisProgressStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    COMPLETE = "COMPLETE"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"
    CANCELLED = "CANCELLED"


class PlanToolCallReference(StrictProgressModel):
    call_id: Identifier
    step_id: Identifier
    tool_name: str = Field(pattern=_TOOL_PATTERN)
    tool_version: str = Field(pattern=_VERSION_PATTERN)


class InvestigationStepProgress(StrictProgressModel):
    position: int = Field(ge=1, le=16)
    step_id: Identifier
    objective: str = Field(min_length=1, max_length=512)
    expected_source: str = Field(min_length=1, max_length=64)
    depends_on: tuple[Identifier, ...] = Field(default=(), max_length=16)
    parallel_group: int = Field(ge=0, le=16)
    tool_call_id: Identifier
    tool_name: str = Field(pattern=_TOOL_PATTERN)
    tool_version: str = Field(pattern=_VERSION_PATTERN)
    status: ToolProgressStatus = ToolProgressStatus.PLANNED
    failure_code: Identifier | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_utc_optional(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _as_utc(value)

    @model_validator(mode="after")
    def validate_status_times(self) -> InvestigationStepProgress:
        if self.status is ToolProgressStatus.PLANNED:
            if self.started_at is not None or self.completed_at is not None or self.failure_code:
                raise ValueError("planned tool progress cannot contain execution metadata")
        elif self.status is ToolProgressStatus.RUNNING:
            if self.started_at is None or self.completed_at is not None or self.failure_code:
                raise ValueError("running tool progress has invalid execution metadata")
        elif self.status is ToolProgressStatus.SUCCEEDED:
            if self.started_at is None or self.completed_at is None or self.failure_code:
                raise ValueError("successful tool progress has invalid execution metadata")
        elif self.status in {
            ToolProgressStatus.FAILED,
            ToolProgressStatus.CANCELLED,
        } and (self.started_at is None or self.completed_at is None or self.failure_code is None):
            raise ValueError("terminal unsuccessful tool progress requires a failure code")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("tool progress completion precedes its start")
        return self


class InvestigationPlanProgress(StrictProgressModel):
    attempt: int = Field(ge=1, le=MAX_PLAN_ATTEMPTS)
    plan_id: Identifier
    summary: str = Field(min_length=1, max_length=512)
    model_call_id: Identifier
    created_at: datetime
    steps: tuple[InvestigationStepProgress, ...] = Field(min_length=1, max_length=16)

    @field_validator("created_at")
    @classmethod
    def require_utc_created_at(cls, value: datetime) -> datetime:
        return _as_utc(value)

    @model_validator(mode="after")
    def validate_steps(self) -> InvestigationPlanProgress:
        if tuple(step.position for step in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("investigation progress step positions must be consecutive")
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError("investigation progress step IDs must be unique")
        if len({step.tool_call_id for step in self.steps}) != len(self.steps):
            raise ValueError("investigation progress tool calls must be unique")
        return self


class ReplanProgress(StrictProgressModel):
    completed_attempt: int = Field(ge=1, le=MAX_PLAN_ATTEMPTS)
    next_attempt: int = Field(ge=2, le=MAX_PLAN_ATTEMPTS)
    decision_fingerprint: Digest
    reason_code: Identifier
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_utc_occurred_at(cls, value: datetime) -> datetime:
        return _as_utc(value)

    @model_validator(mode="after")
    def validate_attempts(self) -> ReplanProgress:
        if self.next_attempt != self.completed_attempt + 1:
            raise ValueError("replan progress attempts must be consecutive")
        return self


class DiagnosisProgressSnapshot(StrictProgressModel):
    schema_version: Literal["1.0.0"]
    tenant_id: Identifier
    incident_id: Identifier
    workflow_run_id: Identifier
    graph_version: str = Field(pattern=_VERSION_PATTERN)
    phase: GraphPhase
    status: DiagnosisProgressStatus
    budgets: GraphBudgetState
    plans: tuple[InvestigationPlanProgress, ...] = Field(min_length=1, max_length=MAX_PLAN_ATTEMPTS)
    replans: tuple[ReplanProgress, ...] = Field(default=(), max_length=16)
    checkpoint_sequence: int = Field(ge=0)
    error_code: Identifier | None = None
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_utc_updated_at(cls, value: datetime) -> datetime:
        return _as_utc(value)

    @model_validator(mode="after")
    def validate_history(self) -> DiagnosisProgressSnapshot:
        attempts = tuple(plan.attempt for plan in self.plans)
        if attempts != tuple(range(1, len(self.plans) + 1)):
            raise ValueError("investigation plan attempts must be consecutive")
        if len(self.replans) not in {len(self.plans) - 1, len(self.plans)}:
            raise ValueError("replan history must connect persisted plan attempts")
        for index, replan in enumerate(self.replans, start=1):
            if replan.completed_attempt != index or replan.next_attempt != index + 1:
                raise ValueError("replan history does not match plan attempts")
        expected = progress_status_for_phase(self.phase)
        if self.status is not DiagnosisProgressStatus.FAILED and self.status is not expected:
            raise ValueError("diagnosis progress status does not match graph phase")
        return self


class DiagnosisProgressRecorder(Protocol):
    async def record_plan(
        self,
        state: DiagnosisGraphState,
        *,
        plan: InvestigationPlan,
        calls: tuple[PlanToolCallReference, ...],
        model_call_id: str,
        next_state: DiagnosisGraphState,
        operation_id: str,
    ) -> None: ...

    async def record_tool_status(
        self,
        state: DiagnosisGraphState,
        *,
        tool_call_id: str,
        status: ToolProgressStatus,
        failure_code: str | None,
        occurred_at: datetime,
        operation_id: str,
    ) -> None: ...

    async def record_replan(
        self,
        state: DiagnosisGraphState,
        *,
        decision_fingerprint: str,
        reason_code: str,
        next_state: DiagnosisGraphState,
        operation_id: str,
    ) -> None: ...

    async def record_state(self, state: DiagnosisGraphState, *, operation_id: str) -> None: ...


def build_plan_progress(
    *,
    attempt: int,
    plan: InvestigationPlan,
    calls: tuple[PlanToolCallReference, ...],
    model_call_id: str,
    created_at: datetime,
) -> InvestigationPlanProgress:
    if len(calls) != len(plan.steps):
        raise ValueError("plan progress requires one tool call per step")
    calls_by_step = {call.step_id: call for call in calls}
    if len(calls_by_step) != len(calls):
        raise ValueError("plan progress tool steps must be unique")
    steps = []
    for position, step in enumerate(plan.steps, start=1):
        call = calls_by_step.get(step.step_id)
        if call is None:
            raise ValueError("plan progress tool calls do not match plan steps")
        steps.append(
            InvestigationStepProgress(
                position=position,
                step_id=step.step_id,
                objective=step.objective,
                expected_source=step.expected_source.value,
                depends_on=step.depends_on,
                parallel_group=step.parallel_group,
                tool_call_id=call.call_id,
                tool_name=call.tool_name,
                tool_version=call.tool_version,
            )
        )
    return InvestigationPlanProgress(
        attempt=attempt,
        plan_id=plan.plan_id,
        summary=plan.summary,
        model_call_id=model_call_id,
        created_at=created_at,
        steps=tuple(steps),
    )


def progress_status_for_phase(phase: GraphPhase) -> DiagnosisProgressStatus:
    if phase is GraphPhase.COMPLETE:
        return DiagnosisProgressStatus.COMPLETE
    if phase is GraphPhase.HUMAN_HANDOFF:
        return DiagnosisProgressStatus.HUMAN_HANDOFF
    if phase is GraphPhase.CANCELLED:
        return DiagnosisProgressStatus.CANCELLED
    return DiagnosisProgressStatus.ACTIVE


def canonical_progress_bytes(snapshot: DiagnosisProgressSnapshot) -> bytes:
    return json.dumps(
        snapshot.model_dump(mode="json", exclude_none=False),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def progress_fingerprint(snapshot: DiagnosisProgressSnapshot) -> str:
    return sha256(canonical_progress_bytes(snapshot)).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("diagnosis progress timestamp must be timezone-aware")
    return value.astimezone(UTC)


def valid_failure_code(value: BaseException) -> str:
    name = type(value).__name__.upper()
    normalized = re.sub(r"[^A-Z0-9._:-]", "_", name)[:128]
    return normalized if re.fullmatch(_ID_PATTERN, normalized) else "TOOL_EXECUTION_FAILED"
