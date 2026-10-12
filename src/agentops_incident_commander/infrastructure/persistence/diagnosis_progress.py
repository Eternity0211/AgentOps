"""PostgreSQL-backed, replay-safe Diagnosis progress projection."""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.domain import InvalidDomainValueError, as_utc
from agentops_incident_commander.workflows import (
    DIAGNOSIS_PROGRESS_SCHEMA_VERSION,
    DiagnosisGraphState,
    DiagnosisProgressSnapshot,
    DiagnosisProgressStatus,
    InvestigationPlan,
    InvestigationPlanProgress,
    InvestigationStepProgress,
    PlanToolCallReference,
    ReplanProgress,
    ToolProgressStatus,
    build_plan_progress,
    progress_fingerprint,
    progress_status_for_phase,
)

from .models import DiagnosisProgressRow


class PostgresDiagnosisProgressRecorder:
    """Persist one bounded read model without making it workflow authority."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_plan(
        self,
        state: DiagnosisGraphState,
        *,
        plan: InvestigationPlan,
        calls: tuple[PlanToolCallReference, ...],
        model_call_id: str,
        next_state: DiagnosisGraphState,
        operation_id: str,
    ) -> None:
        _validate_operation(operation_id)
        _require_transition_identity(state, next_state)
        async with self._session_factory() as session, session.begin():
            row = await _locked_row(session, state.workflow_run_id)
            if row is None:
                if state.budgets.used_replans != 0:
                    raise InvalidDomainValueError(
                        "diagnosis progress cannot begin after an unrecorded replan"
                    )
                attempt = 1
                progress = build_plan_progress(
                    attempt=attempt,
                    plan=plan,
                    calls=calls,
                    model_call_id=model_call_id,
                    created_at=next_state.updated_at,
                )
                snapshot = DiagnosisProgressSnapshot(
                    schema_version=DIAGNOSIS_PROGRESS_SCHEMA_VERSION,
                    tenant_id=next_state.tenant_id,
                    incident_id=next_state.incident_id,
                    workflow_run_id=next_state.workflow_run_id,
                    graph_version=next_state.graph_version,
                    phase=next_state.phase,
                    status=progress_status_for_phase(next_state.phase),
                    budgets=next_state.budgets,
                    plans=(progress,),
                    checkpoint_sequence=next_state.checkpoint_sequence,
                    error_code=next_state.error_code,
                    updated_at=next_state.updated_at,
                )
                row = DiagnosisProgressRow(workflow_run_id=state.workflow_run_id)
                session.add(row)
            else:
                snapshot = _snapshot(row)
                _require_state_scope(snapshot, state)
                replay = build_plan_progress(
                    attempt=len(snapshot.plans),
                    plan=plan,
                    calls=calls,
                    model_call_id=model_call_id,
                    created_at=next_state.updated_at,
                )
                if snapshot.plans[-1] == replay:
                    return
                if len(snapshot.replans) != len(snapshot.plans):
                    raise InvalidDomainValueError(
                        "diagnosis progress has no pending replan for a new plan"
                    )
                attempt = len(snapshot.plans) + 1
                progress = build_plan_progress(
                    attempt=attempt,
                    plan=plan,
                    calls=calls,
                    model_call_id=model_call_id,
                    created_at=next_state.updated_at,
                )
                snapshot = _replace_snapshot(
                    snapshot,
                    plans=(*snapshot.plans, progress),
                )
                snapshot = _apply_state(snapshot, next_state)
            _save(row, snapshot)

    async def record_tool_status(
        self,
        state: DiagnosisGraphState,
        *,
        tool_call_id: str,
        status: ToolProgressStatus,
        failure_code: str | None,
        occurred_at: datetime,
        operation_id: str,
    ) -> None:
        _validate_operation(operation_id)
        occurred_at = as_utc(occurred_at)
        async with self._session_factory() as session, session.begin():
            row = await _locked_row(session, state.workflow_run_id)
            if row is None:
                raise InvalidDomainValueError("diagnosis tool progress has no recorded plan")
            snapshot = _snapshot(row)
            _require_state_scope(snapshot, state)
            plans = list(snapshot.plans)
            found: tuple[int, int] | None = None
            for plan_index, plan in enumerate(plans):
                for step_index, step in enumerate(plan.steps):
                    if step.tool_call_id == tool_call_id:
                        found = (plan_index, step_index)
                        break
                if found is not None:
                    break
            if found is None:
                raise InvalidDomainValueError("diagnosis tool progress call is not planned")
            plan_index, step_index = found
            plan = plans[plan_index]
            step = plan.steps[step_index]
            updated_step = _advance_tool_step(
                step,
                status=status,
                failure_code=failure_code,
                occurred_at=occurred_at,
            )
            if updated_step == step:
                return
            steps = list(plan.steps)
            steps[step_index] = updated_step
            plans[plan_index] = InvestigationPlanProgress.model_validate(
                {**plan.model_dump(mode="python"), "steps": tuple(steps)}
            )
            progress_status = snapshot.status
            if status in {ToolProgressStatus.FAILED, ToolProgressStatus.CANCELLED}:
                progress_status = DiagnosisProgressStatus.FAILED
            snapshot = _replace_snapshot(
                snapshot,
                plans=tuple(plans),
                status=progress_status,
                updated_at=max(snapshot.updated_at, occurred_at),
            )
            _save(row, snapshot)

    async def record_replan(
        self,
        state: DiagnosisGraphState,
        *,
        decision_fingerprint: str,
        reason_code: str,
        next_state: DiagnosisGraphState,
        operation_id: str,
    ) -> None:
        _validate_operation(operation_id)
        _require_transition_identity(state, next_state)
        async with self._session_factory() as session, session.begin():
            row = await _locked_row(session, state.workflow_run_id)
            if row is None:
                raise InvalidDomainValueError("diagnosis replan progress has no recorded plan")
            snapshot = _snapshot(row)
            _require_state_scope(snapshot, state)
            if len(snapshot.replans) == len(snapshot.plans):
                existing = snapshot.replans[-1]
                if (
                    existing.decision_fingerprint == decision_fingerprint
                    and existing.reason_code == reason_code
                ):
                    return
                raise InvalidDomainValueError("diagnosis replan progress conflicts with replay")
            if len(snapshot.replans) != len(snapshot.plans) - 1:
                raise InvalidDomainValueError("diagnosis replan history is inconsistent")
            completed_attempt = len(snapshot.plans)
            replan = ReplanProgress(
                completed_attempt=completed_attempt,
                next_attempt=completed_attempt + 1,
                decision_fingerprint=decision_fingerprint,
                reason_code=reason_code,
                occurred_at=next_state.updated_at,
            )
            snapshot = _replace_snapshot(snapshot, replans=(*snapshot.replans, replan))
            snapshot = _apply_state(snapshot, next_state)
            _save(row, snapshot)

    async def record_state(self, state: DiagnosisGraphState, *, operation_id: str) -> None:
        _validate_operation(operation_id)
        async with self._session_factory() as session, session.begin():
            row = await _locked_row(session, state.workflow_run_id)
            if row is None:
                return
            snapshot = _snapshot(row)
            _require_state_scope(snapshot, state)
            if state.checkpoint_sequence < snapshot.checkpoint_sequence:
                return
            if state.checkpoint_sequence == snapshot.checkpoint_sequence:
                if (
                    state.phase != snapshot.phase
                    or state.budgets != snapshot.budgets
                    or state.error_code != snapshot.error_code
                ):
                    raise InvalidDomainValueError(
                        "diagnosis progress state conflicts at one checkpoint sequence"
                    )
                return
            _save(row, _apply_state(snapshot, state))


def diagnosis_progress_from_row(row: DiagnosisProgressRow) -> DiagnosisProgressSnapshot:
    """Validate the JSON projection and every duplicated relational binding."""
    return _snapshot(row)


async def _locked_row(session: AsyncSession, workflow_run_id: str) -> DiagnosisProgressRow | None:
    return await session.scalar(
        select(DiagnosisProgressRow)
        .where(DiagnosisProgressRow.workflow_run_id == workflow_run_id)
        .with_for_update()
    )


def _snapshot(row: DiagnosisProgressRow) -> DiagnosisProgressSnapshot:
    try:
        snapshot = DiagnosisProgressSnapshot.model_validate_json(
            json.dumps(row.snapshot, sort_keys=True, separators=(",", ":"))
        )
    except ValidationError as error:
        raise InvalidDomainValueError("persisted diagnosis progress is invalid") from error
    if (
        snapshot.workflow_run_id != row.workflow_run_id
        or snapshot.tenant_id != row.tenant_id
        or snapshot.incident_id != row.incident_id
        or snapshot.schema_version != row.schema_version
        or snapshot.graph_version != row.graph_version
        or snapshot.phase.value != row.phase
        or snapshot.status.value != row.status
        or snapshot.checkpoint_sequence != row.checkpoint_sequence
        or snapshot.updated_at != as_utc(row.updated_at)
        or progress_fingerprint(snapshot) != row.snapshot_fingerprint
    ):
        raise InvalidDomainValueError("persisted diagnosis progress binding is invalid")
    return snapshot


def _save(row: DiagnosisProgressRow, snapshot: DiagnosisProgressSnapshot) -> None:
    row.tenant_id = snapshot.tenant_id
    row.incident_id = snapshot.incident_id
    row.schema_version = snapshot.schema_version
    row.graph_version = snapshot.graph_version
    row.phase = snapshot.phase.value
    row.status = snapshot.status.value
    row.checkpoint_sequence = snapshot.checkpoint_sequence
    row.snapshot = snapshot.model_dump(mode="json", exclude_none=False)
    row.snapshot_fingerprint = progress_fingerprint(snapshot)
    row.updated_at = snapshot.updated_at


def _apply_state(
    snapshot: DiagnosisProgressSnapshot, state: DiagnosisGraphState
) -> DiagnosisProgressSnapshot:
    _require_state_scope(snapshot, state)
    return _replace_snapshot(
        snapshot,
        phase=state.phase,
        status=progress_status_for_phase(state.phase),
        budgets=state.budgets,
        checkpoint_sequence=state.checkpoint_sequence,
        error_code=state.error_code,
        updated_at=state.updated_at,
    )


def _replace_snapshot(
    snapshot: DiagnosisProgressSnapshot, **updates: object
) -> DiagnosisProgressSnapshot:
    return DiagnosisProgressSnapshot.model_validate(
        {**snapshot.model_dump(mode="python"), **updates}
    )


def _advance_tool_step(
    step: InvestigationStepProgress,
    *,
    status: ToolProgressStatus,
    failure_code: str | None,
    occurred_at: datetime,
) -> InvestigationStepProgress:
    if not isinstance(status, ToolProgressStatus):
        raise InvalidDomainValueError("diagnosis tool progress status is invalid")
    if step.status in {
        ToolProgressStatus.SUCCEEDED,
        ToolProgressStatus.FAILED,
        ToolProgressStatus.CANCELLED,
    }:
        if status is ToolProgressStatus.RUNNING:
            return step
        if step.status is status and step.failure_code == failure_code:
            return step
        raise InvalidDomainValueError("terminal diagnosis tool progress cannot change")
    if status is ToolProgressStatus.RUNNING and step.status is ToolProgressStatus.PLANNED:
        return InvestigationStepProgress.model_validate(
            {
                **step.model_dump(mode="python"),
                "status": status,
                "started_at": occurred_at,
            }
        )
    if (
        status
        in {
            ToolProgressStatus.SUCCEEDED,
            ToolProgressStatus.FAILED,
            ToolProgressStatus.CANCELLED,
        }
        and step.status is ToolProgressStatus.RUNNING
    ):
        return InvestigationStepProgress.model_validate(
            {
                **step.model_dump(mode="python"),
                "status": status,
                "failure_code": failure_code,
                "completed_at": occurred_at,
            }
        )
    raise InvalidDomainValueError("diagnosis tool progress transition is invalid")


def _require_state_scope(snapshot: DiagnosisProgressSnapshot, state: DiagnosisGraphState) -> None:
    if (
        snapshot.tenant_id != state.tenant_id
        or snapshot.incident_id != state.incident_id
        or snapshot.workflow_run_id != state.workflow_run_id
        or snapshot.graph_version != state.graph_version
    ):
        raise InvalidDomainValueError("diagnosis progress state scope does not match")


def _require_transition_identity(
    state: DiagnosisGraphState, next_state: DiagnosisGraphState
) -> None:
    if next_state.checkpoint_sequence != state.checkpoint_sequence + 1:
        raise InvalidDomainValueError("diagnosis progress transition sequence is invalid")
    for name in ("tenant_id", "incident_id", "workflow_run_id", "graph_version"):
        if getattr(state, name) != getattr(next_state, name):
            raise InvalidDomainValueError("diagnosis progress transition changes run identity")


def _validate_operation(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise InvalidDomainValueError("diagnosis progress operation identity is invalid")
