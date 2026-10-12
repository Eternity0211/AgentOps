"""Bounded and content-safe Diagnosis progress contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import agentops_incident_commander.infrastructure.persistence.diagnosis_progress as progress_store
from agentops_incident_commander.domain import EvidenceSourceType, InvalidDomainValueError
from agentops_incident_commander.infrastructure.persistence.diagnosis_progress import (
    PostgresDiagnosisProgressRecorder,
    _advance_tool_step,
    _apply_state,
    _locked_row,
    _require_state_scope,
    _require_transition_identity,
    _save,
    _snapshot,
    _validate_operation,
)
from agentops_incident_commander.infrastructure.persistence.models import DiagnosisProgressRow
from agentops_incident_commander.workflows import (
    DIAGNOSIS_PROGRESS_SCHEMA_VERSION,
    DiagnosisGraphState,
    DiagnosisProgressSnapshot,
    DiagnosisProgressStatus,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
    InvestigationPlan,
    InvestigationPlanProgress,
    InvestigationStep,
    InvestigationStepProgress,
    PlanToolCallReference,
    ReplanProgress,
    ToolProgressStatus,
    build_plan_progress,
    canonical_progress_bytes,
    progress_fingerprint,
    progress_status_for_phase,
    valid_failure_code,
)

NOW = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)


class NullAsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class NullSession:
    async def __aenter__(self) -> NullSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> NullAsyncContext:
        return NullAsyncContext()


class NullSessionFactory:
    def __call__(self) -> NullSession:
        return NullSession()


def recorder() -> PostgresDiagnosisProgressRecorder:
    return PostgresDiagnosisProgressRecorder(cast(Any, NullSessionFactory()))


def budgets(**updates: int) -> GraphBudgetState:
    values = {
        "max_steps": 4,
        "used_steps": 1,
        "max_replans": 2,
        "used_replans": 0,
        "max_tool_calls": 4,
        "used_tool_calls": 0,
        "max_model_calls": 6,
        "used_model_calls": 1,
        "max_tokens": 1_000,
        "used_tokens": 10,
        "max_cost_nanounits": 100,
        "used_cost_nanounits": 1,
    }
    values.update(updates)
    return GraphBudgetState(**values)


def plan() -> InvestigationPlan:
    return InvestigationPlan(
        schema_version="1.0.0",
        plan_id="plan-1",
        summary="Collect independent telemetry",
        steps=(
            InvestigationStep(
                step_id="metrics",
                objective="Inspect error rate",
                expected_source=EvidenceSourceType.METRIC,
                parallel_group=0,
            ),
            InvestigationStep(
                step_id="logs",
                objective="Inspect correlated errors",
                expected_source=EvidenceSourceType.LOG,
                depends_on=("metrics",),
                parallel_group=1,
            ),
        ),
    )


def calls() -> tuple[PlanToolCallReference, ...]:
    return (
        PlanToolCallReference(
            call_id="call-metrics",
            step_id="metrics",
            tool_name="query_metrics",
            tool_version="1.0.0",
        ),
        PlanToolCallReference(
            call_id="call-logs",
            step_id="logs",
            tool_name="query_logs",
            tool_version="1.0.0",
        ),
    )


def progress_plan(*, attempt: int = 1) -> InvestigationPlanProgress:
    value = plan().model_copy(update={"plan_id": f"plan-{attempt}"})
    return build_plan_progress(
        attempt=attempt,
        plan=value,
        calls=calls(),
        model_call_id=f"model-{attempt}",
        created_at=NOW + timedelta(minutes=attempt),
    )


def snapshot(**updates: Any) -> DiagnosisProgressSnapshot:
    values: dict[str, Any] = {
        "schema_version": DIAGNOSIS_PROGRESS_SCHEMA_VERSION,
        "tenant_id": "tenant-1",
        "incident_id": "incident-1",
        "workflow_run_id": "run-1",
        "graph_version": "1.0.0",
        "phase": GraphPhase.INVESTIGATING,
        "status": DiagnosisProgressStatus.ACTIVE,
        "budgets": budgets(),
        "plans": (progress_plan(),),
        "replans": (),
        "checkpoint_sequence": 2,
        "error_code": None,
        "updated_at": NOW,
    }
    values.update(updates)
    return DiagnosisProgressSnapshot.model_validate(values)


def graph_state(**updates: Any) -> DiagnosisGraphState:
    values: dict[str, Any] = {
        "state_schema_version": "1.3.0",
        "graph_version": "1.0.0",
        "tenant_id": "tenant-1",
        "incident_id": "incident-1",
        "workflow_run_id": "run-1",
        "correlation_id": "correlation-1",
        "causation_id": "cause-1",
        "phase": GraphPhase.INVESTIGATING,
        "budgets": budgets(),
        "prompt": GraphPromptReference(
            prompt_id="diagnosis",
            version="1.0.0",
            content_fingerprint="a" * 64,
        ),
        "checkpoint_sequence": 2,
        "updated_at": NOW,
    }
    values.update(updates)
    return DiagnosisGraphState.model_validate(values)


def test_builds_bounded_plan_projection_without_arguments() -> None:
    result = progress_plan()
    assert result.plan_id == "plan-1"
    assert [step.tool_name for step in result.steps] == ["query_metrics", "query_logs"]
    assert result.steps[1].depends_on == ("metrics",)
    assert "arguments" not in result.model_dump_json()


@pytest.mark.parametrize(
    "tool_calls",
    [
        calls()[:1],
        (calls()[0], calls()[0]),
        (
            calls()[0],
            PlanToolCallReference(
                call_id="call-orphan",
                step_id="orphan",
                tool_name="query_logs",
                tool_version="1.0.0",
            ),
        ),
    ],
)
def test_plan_projection_rejects_missing_duplicate_or_misaligned_calls(
    tool_calls: tuple[PlanToolCallReference, ...],
) -> None:
    with pytest.raises((ValueError, ValidationError), match=r"tool|plan progress"):
        build_plan_progress(
            attempt=1,
            plan=plan(),
            calls=tool_calls,
            model_call_id="model-1",
            created_at=NOW,
        )


@pytest.mark.parametrize(
    ("status", "started", "completed", "failure", "message"),
    [
        (ToolProgressStatus.PLANNED, NOW, None, None, "planned"),
        (ToolProgressStatus.RUNNING, None, None, None, "running"),
        (ToolProgressStatus.SUCCEEDED, NOW, None, None, "successful"),
        (ToolProgressStatus.FAILED, NOW, NOW, None, "requires a failure"),
        (ToolProgressStatus.CANCELLED, NOW, NOW, None, "requires a failure"),
    ],
)
def test_tool_progress_status_requires_consistent_execution_metadata(
    status: ToolProgressStatus,
    started: datetime | None,
    completed: datetime | None,
    failure: str | None,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        InvestigationStepProgress(
            position=1,
            step_id="step",
            objective="objective",
            expected_source="METRIC",
            parallel_group=0,
            tool_call_id="call",
            tool_name="query_metrics",
            tool_version="1.0.0",
            status=status,
            failure_code=failure,
            started_at=started,
            completed_at=completed,
        )


def test_tool_progress_rejects_naive_or_reversed_times() -> None:
    base = progress_plan().steps[0].model_dump(mode="python")
    with pytest.raises(ValidationError, match="timezone-aware"):
        InvestigationStepProgress.model_validate(
            {**base, "status": ToolProgressStatus.RUNNING, "started_at": NOW.replace(tzinfo=None)}
        )
    with pytest.raises(ValidationError, match="precedes"):
        InvestigationStepProgress.model_validate(
            {
                **base,
                "status": ToolProgressStatus.SUCCEEDED,
                "started_at": NOW,
                "completed_at": NOW - timedelta(seconds=1),
            }
        )


def test_plan_progress_rejects_nonconsecutive_or_duplicate_steps() -> None:
    first, second = progress_plan().steps
    with pytest.raises(ValidationError, match="positions"):
        InvestigationPlanProgress.model_validate(
            {
                **progress_plan().model_dump(mode="python"),
                "steps": (first, second.model_copy(update={"position": 3})),
            }
        )
    with pytest.raises(ValidationError, match="step IDs"):
        InvestigationPlanProgress.model_validate(
            {
                **progress_plan().model_dump(mode="python"),
                "steps": (first, second.model_copy(update={"step_id": first.step_id})),
            }
        )
    with pytest.raises(ValidationError, match="tool calls"):
        InvestigationPlanProgress.model_validate(
            {
                **progress_plan().model_dump(mode="python"),
                "steps": (
                    first,
                    second.model_copy(update={"tool_call_id": first.tool_call_id}),
                ),
            }
        )


def test_replan_and_snapshot_history_are_consecutive_and_bounded() -> None:
    replan = ReplanProgress(
        completed_attempt=1,
        next_attempt=2,
        decision_fingerprint="a" * 64,
        reason_code="MORE_EVIDENCE",
        occurred_at=NOW,
    )
    pending = snapshot(replans=(replan,), phase=GraphPhase.PLANNING)
    assert len(pending.replans) == len(pending.plans)
    complete = snapshot(
        plans=(progress_plan(), progress_plan(attempt=2)),
        replans=(replan,),
    )
    assert complete.plans[-1].attempt == 2
    with pytest.raises(ValidationError, match="consecutive"):
        ReplanProgress(
            completed_attempt=1,
            next_attempt=3,
            decision_fingerprint="a" * 64,
            reason_code="MORE_EVIDENCE",
            occurred_at=NOW,
        )
    with pytest.raises(ValidationError, match="plan attempts"):
        snapshot(plans=(progress_plan(attempt=2),))
    with pytest.raises(ValidationError, match="replan history"):
        snapshot(replans=(replan, replan))
    with pytest.raises(ValidationError, match="does not match"):
        snapshot(
            plans=(progress_plan(), progress_plan(attempt=2)),
            replans=(replan.model_copy(update={"completed_attempt": 2, "next_attempt": 3}),),
        )


def test_snapshot_status_timestamp_and_fingerprint_are_strict() -> None:
    with pytest.raises(ValidationError, match="status"):
        snapshot(phase=GraphPhase.COMPLETE, status=DiagnosisProgressStatus.ACTIVE)
    assert snapshot(status=DiagnosisProgressStatus.FAILED).status is DiagnosisProgressStatus.FAILED
    with pytest.raises(ValidationError, match="timezone-aware"):
        snapshot(updated_at=NOW.replace(tzinfo=None))
    first = snapshot()
    restored = DiagnosisProgressSnapshot.model_validate_json(canonical_progress_bytes(first))
    assert restored == first
    assert progress_fingerprint(first) == progress_fingerprint(restored)
    assert len(progress_fingerprint(first)) == 64


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        (GraphPhase.CONTEXT_LOADING, DiagnosisProgressStatus.ACTIVE),
        (GraphPhase.COMPLETE, DiagnosisProgressStatus.COMPLETE),
        (GraphPhase.HUMAN_HANDOFF, DiagnosisProgressStatus.HUMAN_HANDOFF),
        (GraphPhase.CANCELLED, DiagnosisProgressStatus.CANCELLED),
    ],
)
def test_phase_maps_to_operator_progress_status(
    phase: GraphPhase, expected: DiagnosisProgressStatus
) -> None:
    assert progress_status_for_phase(phase) is expected


def test_failure_code_is_bounded_and_falls_back_for_invalid_class_name() -> None:
    assert valid_failure_code(RuntimeError()) == "RUNTIMEERROR"
    unusual = type("_", (Exception,), {})()
    assert valid_failure_code(unusual) == "TOOL_EXECUTION_FAILED"


def test_tool_progress_transition_helper_is_replay_safe_and_fail_closed() -> None:
    planned = progress_plan().steps[0]
    running = _advance_tool_step(
        planned,
        status=ToolProgressStatus.RUNNING,
        failure_code=None,
        occurred_at=NOW,
    )
    assert running.started_at == NOW
    succeeded = _advance_tool_step(
        running,
        status=ToolProgressStatus.SUCCEEDED,
        failure_code=None,
        occurred_at=NOW + timedelta(seconds=1),
    )
    assert succeeded.completed_at == NOW + timedelta(seconds=1)
    assert (
        _advance_tool_step(
            succeeded,
            status=ToolProgressStatus.RUNNING,
            failure_code=None,
            occurred_at=NOW + timedelta(seconds=2),
        )
        is succeeded
    )
    assert (
        _advance_tool_step(
            succeeded,
            status=ToolProgressStatus.SUCCEEDED,
            failure_code=None,
            occurred_at=NOW + timedelta(seconds=2),
        )
        is succeeded
    )
    with pytest.raises(InvalidDomainValueError, match="cannot change"):
        _advance_tool_step(
            succeeded,
            status=ToolProgressStatus.FAILED,
            failure_code="LATE_FAILURE",
            occurred_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(InvalidDomainValueError, match="transition"):
        _advance_tool_step(
            planned,
            status=ToolProgressStatus.SUCCEEDED,
            failure_code=None,
            occurred_at=NOW,
        )
    with pytest.raises(InvalidDomainValueError, match="transition"):
        _advance_tool_step(
            running,
            status=ToolProgressStatus.RUNNING,
            failure_code=None,
            occurred_at=NOW,
        )
    with pytest.raises(InvalidDomainValueError, match="status"):
        _advance_tool_step(
            planned,
            status=cast(ToolProgressStatus, "UNKNOWN"),
            failure_code=None,
            occurred_at=NOW,
        )

    for status in (ToolProgressStatus.FAILED, ToolProgressStatus.CANCELLED):
        terminal = _advance_tool_step(
            running,
            status=status,
            failure_code="TOOL_TIMEOUT",
            occurred_at=NOW + timedelta(seconds=1),
        )
        assert terminal.status is status
        assert terminal.failure_code == "TOOL_TIMEOUT"


def test_persistence_binding_and_state_transition_helpers_are_strict() -> None:
    stored = snapshot()
    row = DiagnosisProgressRow(workflow_run_id=stored.workflow_run_id)
    _save(row, stored)
    assert _snapshot(row) == stored

    row.status = DiagnosisProgressStatus.COMPLETE.value
    with pytest.raises(InvalidDomainValueError, match="binding"):
        _snapshot(row)
    _save(row, stored)
    row.snapshot = {"unexpected": "shape"}
    with pytest.raises(InvalidDomainValueError, match="invalid"):
        _snapshot(row)

    state = graph_state()
    advanced = graph_state(
        phase=GraphPhase.EVIDENCE_REVIEW,
        checkpoint_sequence=3,
        updated_at=NOW + timedelta(minutes=1),
    )
    updated = _apply_state(stored, advanced)
    assert updated.phase is GraphPhase.EVIDENCE_REVIEW
    assert updated.checkpoint_sequence == 3
    _require_state_scope(stored, state)
    for name, value in (
        ("tenant_id", "tenant-2"),
        ("incident_id", "incident-2"),
        ("workflow_run_id", "run-2"),
        ("graph_version", "2.0.0"),
    ):
        with pytest.raises(InvalidDomainValueError, match="scope"):
            _require_state_scope(stored, graph_state(**{name: value}))

    _require_transition_identity(state, advanced)
    with pytest.raises(InvalidDomainValueError, match="sequence"):
        _require_transition_identity(state, advanced.model_copy(update={"checkpoint_sequence": 4}))
    with pytest.raises(InvalidDomainValueError, match="identity"):
        _require_transition_identity(state, advanced.model_copy(update={"tenant_id": "tenant-2"}))


@pytest.mark.parametrize("value", ["", "a" * 63, "A" * 64, cast(str, object())])
def test_operation_identity_validation_rejects_invalid_values(value: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="operation identity"):
        _validate_operation(value)
    _validate_operation("a" * 64)


@pytest.mark.anyio
async def test_locked_progress_lookup_uses_workflow_identity() -> None:
    row = DiagnosisProgressRow(workflow_run_id="run-1")
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = row
    assert await _locked_row(session, "run-1") is row
    session.scalar.assert_awaited_once()


@pytest.mark.anyio
async def test_recorder_rejects_effects_without_required_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(progress_store, "_locked_row", AsyncMock(return_value=None))
    store = recorder()
    replanned = graph_state(
        phase=GraphPhase.PLANNING,
        checkpoint_sequence=1,
        budgets=budgets(used_replans=1),
    )
    next_state = graph_state(
        checkpoint_sequence=2,
        budgets=budgets(used_replans=1),
    )
    with pytest.raises(InvalidDomainValueError, match="unrecorded replan"):
        await store.record_plan(
            replanned,
            plan=plan(),
            calls=calls(),
            model_call_id="model-1",
            next_state=next_state,
            operation_id="a" * 64,
        )
    with pytest.raises(InvalidDomainValueError, match="no recorded plan"):
        await store.record_tool_status(
            next_state,
            tool_call_id="call-metrics",
            status=ToolProgressStatus.RUNNING,
            failure_code=None,
            occurred_at=NOW,
            operation_id="b" * 64,
        )
    with pytest.raises(InvalidDomainValueError, match="no recorded plan"):
        await store.record_replan(
            replanned,
            decision_fingerprint="b" * 64,
            reason_code="MORE_EVIDENCE",
            next_state=next_state,
            operation_id="c" * 64,
        )
    await store.record_state(next_state, operation_id="d" * 64)


@pytest.mark.anyio
async def test_recorder_rejects_conflicting_plan_and_replan_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = DiagnosisProgressRow(workflow_run_id="run-1")
    monkeypatch.setattr(progress_store, "_locked_row", AsyncMock(return_value=row))
    store = recorder()
    current = snapshot()
    monkeypatch.setattr(progress_store, "_snapshot", lambda _: current)
    state = graph_state()
    next_state = graph_state(checkpoint_sequence=3, updated_at=NOW + timedelta(minutes=1))
    changed_plan = plan().model_copy(update={"plan_id": "changed-plan"})
    with pytest.raises(InvalidDomainValueError, match="no pending replan"):
        await store.record_plan(
            state,
            plan=changed_plan,
            calls=calls(),
            model_call_id="model-changed",
            next_state=next_state,
            operation_id="a" * 64,
        )

    recorded_replan = ReplanProgress(
        completed_attempt=1,
        next_attempt=2,
        decision_fingerprint="a" * 64,
        reason_code="MORE_EVIDENCE",
        occurred_at=NOW,
    )
    pending = snapshot(replans=(recorded_replan,), phase=GraphPhase.PLANNING)
    monkeypatch.setattr(progress_store, "_snapshot", lambda _: pending)
    planning = graph_state(phase=GraphPhase.PLANNING)
    planning_next = graph_state(
        phase=GraphPhase.PLANNING,
        checkpoint_sequence=3,
        updated_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(InvalidDomainValueError, match="conflicts with replay"):
        await store.record_replan(
            planning,
            decision_fingerprint="b" * 64,
            reason_code="CHANGED_REASON",
            next_state=planning_next,
            operation_id="b" * 64,
        )

    inconsistent = cast(
        DiagnosisProgressSnapshot,
        type(
            "InconsistentSnapshot",
            (),
            {
                "tenant_id": "tenant-1",
                "incident_id": "incident-1",
                "workflow_run_id": "run-1",
                "graph_version": "1.0.0",
                "plans": (progress_plan(), progress_plan(attempt=2)),
                "replans": (),
            },
        )(),
    )
    monkeypatch.setattr(progress_store, "_snapshot", lambda _: inconsistent)
    with pytest.raises(InvalidDomainValueError, match="history is inconsistent"):
        await store.record_replan(
            state,
            decision_fingerprint="b" * 64,
            reason_code="MORE_EVIDENCE",
            next_state=next_state,
            operation_id="c" * 64,
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changed",
    [
        {"phase": GraphPhase.EVIDENCE_REVIEW},
        {"budgets": budgets(used_steps=2)},
        {"error_code": "CHANGED"},
    ],
)
async def test_recorder_same_sequence_requires_identical_state(
    monkeypatch: pytest.MonkeyPatch, changed: dict[str, object]
) -> None:
    row = DiagnosisProgressRow(workflow_run_id="run-1")
    monkeypatch.setattr(progress_store, "_locked_row", AsyncMock(return_value=row))
    monkeypatch.setattr(progress_store, "_snapshot", lambda _: snapshot())
    with pytest.raises(InvalidDomainValueError, match="conflicts at one checkpoint"):
        await recorder().record_state(
            graph_state(**changed),
            operation_id="a" * 64,
        )


@pytest.mark.anyio
async def test_recorder_same_sequence_identical_state_is_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = DiagnosisProgressRow(workflow_run_id="run-1")
    monkeypatch.setattr(progress_store, "_locked_row", AsyncMock(return_value=row))
    monkeypatch.setattr(progress_store, "_snapshot", lambda _: snapshot())
    await recorder().record_state(graph_state(), operation_id="a" * 64)
