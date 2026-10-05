"""Crash continuation composition and content-free checkpoint observations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Interrupt, PregelTask, StateSnapshot
from pydantic import ValidationError

from agentops_incident_commander.domain import InvalidDomainValueError
from agentops_incident_commander.infrastructure import (
    CheckpointExecutionStatus,
    DiagnosisCheckpointIdentity,
    DiagnosisCheckpointObservation,
    DiagnosisWorkflowRunner,
    checkpoint_observation,
)
from agentops_incident_commander.infrastructure.diagnosis_runtime import DiagnosisGraphRuntime
from agentops_incident_commander.workflows import (
    DiagnosisGraphState,
    GraphBudgetState,
    GraphPhase,
)

NOW = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)


def state(**overrides: Any) -> DiagnosisGraphState:
    values: dict[str, object] = {
        "state_schema_version": "1.2.0",
        "graph_version": "1.0.0",
        "tenant_id": "tenant-1",
        "incident_id": "incident-1",
        "workflow_run_id": "run-1",
        "correlation_id": "correlation-1",
        "causation_id": "cause-1",
        "phase": GraphPhase.PLANNING,
        "budgets": GraphBudgetState(
            max_steps=1,
            used_steps=0,
            max_replans=0,
            used_replans=0,
            max_tool_calls=1,
            used_tool_calls=0,
            max_model_calls=1,
            used_model_calls=0,
            max_tokens=10,
            used_tokens=0,
            max_cost_nanounits=10,
            used_cost_nanounits=0,
        ),
        "checkpoint_sequence": 1,
        "updated_at": NOW,
    }
    values.update(overrides)
    return DiagnosisGraphState.model_validate(values)


def config(checkpoint_id: str = "checkpoint-1") -> RunnableConfig:
    return {
        "configurable": {
            "thread_id": DiagnosisCheckpointIdentity.from_state(state()).thread_id,
            "checkpoint_ns": "",
            "checkpoint_id": checkpoint_id,
        }
    }


def snapshot(
    *,
    graph_state: DiagnosisGraphState | None = None,
    next_nodes: tuple[str, ...] = ("plan",),
    tasks: tuple[PregelTask, ...] = (),
    interrupts: tuple[Interrupt[Any], ...] = (),
    current_config: RunnableConfig | None = None,
    parent_config: RunnableConfig | None = None,
    created_at: str | None = "2026-10-05T14:00:00+00:00",
) -> StateSnapshot:
    return StateSnapshot(
        values={} if graph_state is None else graph_state.model_dump(),
        next=next_nodes,
        config=config() if current_config is None else current_config,
        metadata={},
        created_at=created_at,
        parent_config=parent_config,
        tasks=tasks,
        interrupts=interrupts,
    )


@pytest.mark.parametrize(
    ("next_nodes", "tasks", "interrupts", "expected"),
    [
        (("plan",), (), (), CheckpointExecutionStatus.READY),
        ((), (), (), CheckpointExecutionStatus.COMPLETE),
        (
            ("plan",),
            (PregelTask("task-1", "plan", (), RuntimeError("sensitive failure")),),
            (),
            CheckpointExecutionStatus.FAILED,
        ),
        (
            ("plan",),
            (),
            (Interrupt({"content": "must not be projected"}, "interrupt-1"),),
            CheckpointExecutionStatus.INTERRUPTED,
        ),
    ],
)
def test_checkpoint_observation_exposes_only_bounded_metadata(
    next_nodes: tuple[str, ...],
    tasks: tuple[PregelTask, ...],
    interrupts: tuple[Interrupt[Any], ...],
    expected: CheckpointExecutionStatus,
) -> None:
    graph_state = state()
    observation = checkpoint_observation(
        snapshot(
            graph_state=graph_state,
            next_nodes=next_nodes,
            tasks=tasks,
            interrupts=interrupts,
            parent_config=config("checkpoint-parent"),
        ),
        DiagnosisCheckpointIdentity.from_state(graph_state),
    )

    assert observation.status is expected
    assert observation.parent_checkpoint_id == "checkpoint-parent"
    assert observation.phase is GraphPhase.PLANNING
    assert observation.checkpoint_sequence == 1
    assert (
        observation.state_fingerprint
        == "1c41d0289fd1a41b1a42547fc69be68e75545d9a044c25ebd46044f750e0c25d"
    )
    encoded = observation.model_dump_json()
    assert "sensitive failure" not in encoded
    assert "must not be projected" not in encoded
    assert "budgets" not in encoded


def test_checkpoint_observation_without_parent_is_utc_normalized() -> None:
    graph_state = state()
    observation = checkpoint_observation(
        snapshot(graph_state=graph_state, created_at="2026-10-05T22:00:00+08:00"),
        DiagnosisCheckpointIdentity.from_state(graph_state),
    )

    assert observation.parent_checkpoint_id is None
    assert observation.created_at == NOW


@pytest.mark.parametrize(
    ("bad_snapshot", "message"),
    [
        (snapshot(), "does not contain"),
        (snapshot(graph_state=state(tenant_id="tenant-2")), "does not match"),
        (snapshot(graph_state=state(), current_config={}), "missing checkpoint_id"),
        (
            snapshot(
                graph_state=state(),
                current_config={"configurable": {"checkpoint_id": 1}},
            ),
            "missing checkpoint_id",
        ),
        (
            snapshot(graph_state=state(), parent_config={}),
            "missing checkpoint_id",
        ),
        (snapshot(graph_state=state(), created_at=None), "timestamp is missing"),
        (snapshot(graph_state=state(), created_at="not-time"), "timestamp is invalid"),
        (
            snapshot(graph_state=state(), created_at="2026-10-05T14:00:00"),
            "timezone-aware",
        ),
    ],
)
def test_checkpoint_observation_fails_closed_on_invalid_snapshots(
    bad_snapshot: StateSnapshot, message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        checkpoint_observation(bad_snapshot, DiagnosisCheckpointIdentity.from_state(state()))


def test_checkpoint_observation_validates_its_bounded_projection() -> None:
    valid = checkpoint_observation(
        snapshot(graph_state=state()), DiagnosisCheckpointIdentity.from_state(state())
    )
    with pytest.raises(ValidationError, match="next-node"):
        DiagnosisCheckpointObservation.model_validate(
            {**valid.model_dump(), "next_nodes": ("Bad Node",)}
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        DiagnosisCheckpointObservation.model_validate(
            {**valid.model_dump(), "created_at": datetime(2026, 10, 5, 14, 0)}
        )


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [0, 513, True])
async def test_checkpoint_history_limit_is_bounded(limit: int) -> None:
    runner = DiagnosisWorkflowRunner(cast(DiagnosisGraphRuntime, object()))
    with pytest.raises(InvalidDomainValueError, match="between 1 and 512"):
        await runner.history(state(), limit=limit)
