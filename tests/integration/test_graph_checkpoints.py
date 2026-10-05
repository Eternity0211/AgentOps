"""PostgreSQL-backed LangGraph checkpoint setup, restore, history, and isolation."""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from langgraph.types import Command
from testcontainers.community.postgres import PostgresContainer

from agentops_incident_commander.infrastructure import (
    CheckpointExecutionStatus,
    DiagnosisCheckpointIdentity,
    DiagnosisWorkflowRunner,
    compiled_diagnosis_runner,
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
    def __init__(self, *, gate_route: GateRoute = GateRoute.PASS) -> None:
        self.plan_calls = 0
        self.load_operations: list[str] = []
        self.operations: list[str] = []
        self.gate_route = gate_route

    async def load_context(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> ContextLoadResult:
        self.load_operations.append(operation_id)
        self.operations.append("load_context")
        return ContextLoadResult()

    async def plan(self, state: DiagnosisGraphState, *, operation_id: str) -> PlanNodeResult:
        self.plan_calls += 1
        self.operations.append("plan")
        return PlanNodeResult("model-plan", ("tool-1",), ("1" * 64,), 1, 10, 1)

    async def load_tool_batches(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> tuple[tuple[str, ...], ...]:
        self.operations.append("load_tool_batches")
        return (("tool-1",),)

    async def execute_read_tool(
        self, state: DiagnosisGraphState, tool_call_id: str, *, operation_id: str
    ) -> None:
        assert tool_call_id == "tool-1"
        self.operations.append("execute_read_tool")

    async def persist_evidence(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> EvidencePersistenceResult:
        self.operations.append("persist_evidence")
        return EvidencePersistenceResult(("evidence-1",))

    async def hypothesize(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> HypothesisNodeResult:
        self.operations.append("hypothesize")
        return HypothesisNodeResult("model-hypothesis", 10, 1)

    async def evaluate_evidence_gate(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> GateNodeResult:
        self.operations.append("evaluate_evidence_gate")
        error_code = "REVIEW_REQUIRED" if self.gate_route is GateRoute.HUMAN_HANDOFF else None
        return GateNodeResult("2" * 64, self.gate_route, error_code)

    async def record_handoff(self, state: DiagnosisGraphState, *, operation_id: str) -> None:
        if self.gate_route is GateRoute.PASS:
            raise AssertionError("passing workflow must not hand off")
        self.operations.append("record_handoff")


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
        runner = compiled_diagnosis_runner(graph)
        outcome = await runner.run_or_resume(first, DiagnosisRuntimeContext(services))
        snapshot = await graph.aget_state(config)
        history = [entry async for entry in saver.alist(config)]
        observations = await runner.history(first)
        latest_only = await runner.history(first, limit=1)

        assert outcome.state.phase is GraphPhase.COMPLETE
        assert not outcome.resumed
        assert outcome.checkpoint.status is CheckpointExecutionStatus.COMPLETE
        assert snapshot.values["phase"] == GraphPhase.COMPLETE.value
        assert len(history) >= 7
        assert len(observations) == len(history) - 1
        assert latest_only == (observations[0],)
        assert observations[0].status is CheckpointExecutionStatus.COMPLETE
        latest_metadata = cast(dict[str, Any], history[0].metadata)
        assert latest_metadata["tenant_id"] == "tenant-1"
        assert latest_metadata["workflow_run_id"] == "run-1"
        assert (
            await saver.aget_tuple(diagnosis_checkpoint_config(initial_state(run="run-2"))) is None
        )

        resumed = await runner.run_or_resume(first, DiagnosisRuntimeContext(services))
        assert resumed.state.phase is GraphPhase.COMPLETE
        assert resumed.resumed
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


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("boundary", "gate_route"),
    [
        ("load_context", GateRoute.PASS),
        ("plan", GateRoute.PASS),
        ("execute_read_tools", GateRoute.PASS),
        ("persist_evidence", GateRoute.PASS),
        ("hypothesis", GateRoute.PASS),
        ("evidence_gate", GateRoute.PASS),
        ("human_handoff", GateRoute.HUMAN_HANDOFF),
    ],
)
async def test_new_worker_continues_from_every_durable_boundary_without_duplicate_effects(
    checkpoint_postgres_url: str,
    boundary: str,
    gate_route: GateRoute,
) -> None:
    first = initial_state(run=f"crash-{boundary}")
    config = diagnosis_checkpoint_config(first)
    services = CheckpointServices(gate_route=gate_route)
    runtime = DiagnosisRuntimeContext(services)
    async with postgres_diagnosis_checkpointer(checkpoint_postgres_url) as saver:
        graph = build_diagnosis_graph(checkpointer=saver)
        await graph.ainvoke(first, config, context=runtime, interrupt_after=[boundary])

    async with postgres_diagnosis_checkpointer(checkpoint_postgres_url) as recovered_saver:
        recovered_graph = build_diagnosis_graph(checkpointer=recovered_saver)
        outcome = await DiagnosisWorkflowRunner(recovered_graph).run_or_resume(first, runtime)

    assert outcome.resumed
    expected_phase = (
        GraphPhase.HUMAN_HANDOFF if gate_route is GateRoute.HUMAN_HANDOFF else GraphPhase.COMPLETE
    )
    assert outcome.state.phase is expected_phase
    expected_operations = {
        "load_context",
        "plan",
        "load_tool_batches",
        "execute_read_tool",
        "persist_evidence",
        "hypothesize",
        "evaluate_evidence_gate",
    }
    if gate_route is GateRoute.HUMAN_HANDOFF:
        expected_operations.add("record_handoff")
    assert Counter(services.operations) == Counter({name: 1 for name in expected_operations})


class CrashAfterCommittedPlan(CheckpointServices):
    def __init__(
        self,
        durable_results: dict[str, PlanNodeResult],
        committed_effects: list[str],
        *,
        crash: bool,
    ) -> None:
        super().__init__()
        self._durable_results = durable_results
        self._committed_effects = committed_effects
        self._crash = crash

    async def plan(self, state: DiagnosisGraphState, *, operation_id: str) -> PlanNodeResult:
        result = self._durable_results.get(operation_id)
        if result is None:
            result = PlanNodeResult("model-plan", ("tool-1",), ("1" * 64,), 1, 10, 1)
            self._durable_results[operation_id] = result
            self._committed_effects.append(operation_id)
        if self._crash:
            raise RuntimeError("simulated worker exit after durable plan commit")
        self.operations.append("plan")
        return result


@pytest.mark.anyio
async def test_retried_failed_node_replays_committed_operation_instead_of_effect(
    checkpoint_postgres_url: str,
) -> None:
    first = initial_state(run="crash-after-effect")
    config = diagnosis_checkpoint_config(first)
    durable_results: dict[str, PlanNodeResult] = {}
    committed_effects: list[str] = []
    async with postgres_diagnosis_checkpointer(checkpoint_postgres_url) as saver:
        graph = build_diagnosis_graph(checkpointer=saver)
        with pytest.raises(RuntimeError, match="after durable plan commit"):
            await graph.ainvoke(
                first,
                config,
                context=DiagnosisRuntimeContext(
                    CrashAfterCommittedPlan(durable_results, committed_effects, crash=True)
                ),
            )
        failed_history = await DiagnosisWorkflowRunner(graph).history(first)
        assert failed_history[0].status is CheckpointExecutionStatus.FAILED

    recovered_services = CrashAfterCommittedPlan(durable_results, committed_effects, crash=False)
    async with postgres_diagnosis_checkpointer(checkpoint_postgres_url) as recovered_saver:
        recovered_graph = build_diagnosis_graph(checkpointer=recovered_saver)
        outcome = await DiagnosisWorkflowRunner(recovered_graph).run_or_resume(
            first, DiagnosisRuntimeContext(recovered_services)
        )

    assert outcome.resumed
    assert outcome.state.phase is GraphPhase.COMPLETE
    assert len(committed_effects) == 1
