"""PostgreSQL-backed LangGraph checkpoint setup, restore, history, and isolation."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from langgraph.types import Command
from testcontainers.community.postgres import PostgresContainer

from agentops_incident_commander.infrastructure import (
    DiagnosisCheckpointIdentity,
    diagnosis_checkpoint_config,
    postgres_diagnosis_checkpointer,
)
from agentops_incident_commander.workflows import (
    ContextLoadResult,
    DiagnosisGraphState,
    DiagnosisRuntimeContext,
    EvidencePersistenceResult,
    GateNodeResult,
    GateRoute,
    GraphBudgetState,
    GraphPhase,
    HypothesisNodeResult,
    PlanNodeResult,
    WorkflowControl,
    build_diagnosis_graph,
)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def checkpoint_postgres_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:0.8.6-pg18") as postgres:
        raw = postgres.get_connection_url()
        yield f"postgresql://{raw.split('://', 1)[1]}"


def initial_state(*, run: str = "run-1") -> DiagnosisGraphState:
    return DiagnosisGraphState(
        state_schema_version="1.2.0",
        graph_version="1.0.0",
        tenant_id="tenant-1",
        incident_id="incident-1",
        workflow_run_id=run,
        correlation_id=f"correlation-{run}",
        causation_id="cause-1",
        phase=GraphPhase.CONTEXT_LOADING,
        budgets=GraphBudgetState(
            max_steps=2,
            used_steps=0,
            max_replans=0,
            used_replans=0,
            max_tool_calls=2,
            used_tool_calls=0,
            max_model_calls=2,
            used_model_calls=0,
            max_tokens=100,
            used_tokens=0,
            max_cost_nanounits=100,
            used_cost_nanounits=0,
        ),
        checkpoint_sequence=0,
        updated_at=NOW,
    )


class CheckpointServices:
    def __init__(self) -> None:
        self.plan_calls = 0
        self.load_operations: list[str] = []

    async def load_context(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> ContextLoadResult:
        self.load_operations.append(operation_id)
        return ContextLoadResult()

    async def plan(self, state: DiagnosisGraphState, *, operation_id: str) -> PlanNodeResult:
        self.plan_calls += 1
        return PlanNodeResult("model-plan", ("tool-1",), ("1" * 64,), 1, 10, 1)

    async def load_tool_batches(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> tuple[tuple[str, ...], ...]:
        return (("tool-1",),)

    async def execute_read_tool(
        self, state: DiagnosisGraphState, tool_call_id: str, *, operation_id: str
    ) -> None:
        assert tool_call_id == "tool-1"

    async def persist_evidence(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> EvidencePersistenceResult:
        return EvidencePersistenceResult(("evidence-1",))

    async def hypothesize(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> HypothesisNodeResult:
        return HypothesisNodeResult("model-hypothesis", 10, 1)

    async def evaluate_evidence_gate(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> GateNodeResult:
        return GateNodeResult("2" * 64, GateRoute.PASS)

    async def record_handoff(self, state: DiagnosisGraphState, *, operation_id: str) -> None:
        raise AssertionError("passing workflow must not hand off")


class PauseContextControl:
    def __init__(self) -> None:
        self.operations: list[str] = []

    async def decision(
        self, state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> WorkflowControl:
        if node_name == "load_context":
            self.operations.append(operation_id)
            return WorkflowControl.PAUSE
        return WorkflowControl.CONTINUE


@pytest.mark.anyio
async def test_postgres_checkpoint_restores_latest_history_and_isolates_threads(
    checkpoint_postgres_url: str,
) -> None:
    first = initial_state()
    config = diagnosis_checkpoint_config(first)
    services = CheckpointServices()
    async with postgres_diagnosis_checkpointer(checkpoint_postgres_url) as saver:
        graph = build_diagnosis_graph(checkpointer=saver)
        result = await graph.ainvoke(first, config, context=DiagnosisRuntimeContext(services))
        snapshot = await graph.aget_state(config)
        history = [entry async for entry in saver.alist(config)]

        assert result["phase"] is GraphPhase.COMPLETE
        assert snapshot.values["phase"] == GraphPhase.COMPLETE.value
        assert len(history) >= 7
        latest_metadata = cast(dict[str, Any], history[0].metadata)
        assert latest_metadata["tenant_id"] == "tenant-1"
        assert latest_metadata["workflow_run_id"] == "run-1"
        assert (
            await saver.aget_tuple(diagnosis_checkpoint_config(initial_state(run="run-2"))) is None
        )

        resumed = await graph.ainvoke(None, config, context=DiagnosisRuntimeContext(services))
        assert resumed["phase"] == GraphPhase.COMPLETE.value
        assert services.plan_calls == 1
        DiagnosisCheckpointIdentity.from_state(first).require_matches(first)


@pytest.mark.anyio
async def test_postgres_checkpoint_persists_interrupt_and_resumes_same_operation(
    checkpoint_postgres_url: str,
) -> None:
    first = initial_state(run="pause-run")
    config = diagnosis_checkpoint_config(first)
    services = CheckpointServices()
    control = PauseContextControl()
    runtime = DiagnosisRuntimeContext(services, control=control)
    async with postgres_diagnosis_checkpointer(checkpoint_postgres_url) as saver:
        graph = build_diagnosis_graph(checkpointer=saver)

        paused = await graph.ainvoke(first, config, context=runtime)
        assert paused["__interrupt__"][0].value["kind"] == "DIAGNOSIS_PAUSED"
        assert services.load_operations == []

        resumed = await graph.ainvoke(
            Command[Any](resume={"action": "RESUME"}), config, context=runtime
        )
        assert resumed["phase"] is GraphPhase.COMPLETE
        assert len(services.load_operations) == 1
        assert control.operations[0] == control.operations[1] == services.load_operations[0]
