"""Bounded Diagnosis LangGraph nodes, parallel reads, and deterministic routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from langgraph.runtime import Runtime
from pydantic import ValidationError

from agentops_incident_commander.domain import InvalidDomainValueError
from agentops_incident_commander.workflows import (
    ContextLoadResult,
    DiagnosisGraphState,
    DiagnosisRuntimeContext,
    EvidencePersistenceResult,
    GateNodeResult,
    GateRoute,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
    HypothesisNodeResult,
    PlanNodeResult,
    build_diagnosis_graph,
    execute_read_tools_node,
    persist_evidence_node,
    route_after_gate,
)
from agentops_incident_commander.workflows.diagnosis_graph import (
    _consume_budget,
    _validate_tool_batches,
)

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


def state(**overrides: object) -> DiagnosisGraphState:
    values: dict[str, object] = {
        "state_schema_version": "1.0.0",
        "graph_version": "1.0.0",
        "tenant_id": "tenant-1",
        "incident_id": "incident-1",
        "workflow_run_id": "run-1",
        "correlation_id": "correlation-1",
        "causation_id": "cause-1",
        "phase": GraphPhase.CONTEXT_LOADING,
        "budgets": GraphBudgetState(
            max_steps=8,
            used_steps=0,
            max_replans=1,
            used_replans=0,
            max_tool_calls=8,
            used_tool_calls=0,
            max_model_calls=8,
            used_model_calls=0,
            max_tokens=1_000,
            used_tokens=0,
            max_cost_nanounits=1_000,
            used_cost_nanounits=0,
        ),
        "prompt": GraphPromptReference(
            prompt_id="diagnosis", version="1.0.0", content_fingerprint="a" * 64
        ),
        "tool_call_ids": (),
        "model_call_ids": (),
        "evidence_ids": (),
        "gate_decision_fingerprint": None,
        "error_code": None,
        "checkpoint_sequence": 0,
        "updated_at": NOW,
    }
    values.update(overrides)
    return DiagnosisGraphState.model_validate(values)


class Clock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return NOW + timedelta(seconds=self.calls)


class FakeServices:
    def __init__(
        self,
        *,
        plans: list[PlanNodeResult] | None = None,
        gates: list[GateNodeResult] | None = None,
        batches: list[tuple[tuple[str, ...], ...]] | None = None,
    ) -> None:
        self.plans = plans or [PlanNodeResult("model-plan-1", ("tool-1", "tool-2"), 2, 10, 2)]
        self.gates = gates or [GateNodeResult("b" * 64, GateRoute.PASS)]
        self.batches = batches or []
        self.executed: list[str] = []
        self.max_active = 0
        self.active = 0
        self.persist_calls = 0
        self.hypothesis_calls = 0
        self.handoffs = 0

    async def load_context(self, graph_state: DiagnosisGraphState) -> ContextLoadResult:
        assert graph_state.phase is GraphPhase.CONTEXT_LOADING
        return ContextLoadResult(("evidence-context",))

    async def plan(self, graph_state: DiagnosisGraphState) -> PlanNodeResult:
        assert graph_state.phase is GraphPhase.PLANNING
        return self.plans.pop(0)

    async def load_tool_batches(
        self, graph_state: DiagnosisGraphState
    ) -> tuple[tuple[str, ...], ...]:
        if self.batches:
            return self.batches.pop(0)
        return (graph_state.tool_call_ids[graph_state.budgets.used_tool_calls :],)

    async def execute_read_tool(self, graph_state: DiagnosisGraphState, tool_call_id: str) -> None:
        assert graph_state.phase is GraphPhase.INVESTIGATING
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.executed.append(tool_call_id)
        self.active -= 1

    async def persist_evidence(self, graph_state: DiagnosisGraphState) -> EvidencePersistenceResult:
        self.persist_calls += 1
        return EvidencePersistenceResult((f"evidence-tools-{self.persist_calls}",))

    async def hypothesize(self, graph_state: DiagnosisGraphState) -> HypothesisNodeResult:
        self.hypothesis_calls += 1
        return HypothesisNodeResult(f"model-hypothesis-{self.hypothesis_calls}", 20, 3)

    async def evaluate_evidence_gate(self, graph_state: DiagnosisGraphState) -> GateNodeResult:
        assert graph_state.phase is GraphPhase.EVIDENCE_REVIEW
        return self.gates.pop(0)

    async def record_handoff(self, graph_state: DiagnosisGraphState) -> None:
        assert graph_state.phase is GraphPhase.HUMAN_HANDOFF
        self.handoffs += 1


def context(services: FakeServices) -> DiagnosisRuntimeContext:
    return DiagnosisRuntimeContext(services, Clock())


@pytest.mark.anyio
async def test_graph_pass_path_parallelizes_reads_and_returns_only_references() -> None:
    services = FakeServices()
    result = await build_diagnosis_graph().ainvoke(state(), context=context(services))

    assert result["phase"] is GraphPhase.COMPLETE
    assert result["tool_call_ids"] == ("tool-1", "tool-2")
    assert set(services.executed) == {"tool-1", "tool-2"}
    assert services.max_active == 2
    assert result["evidence_ids"] == ("evidence-context", "evidence-tools-1")
    assert result["model_call_ids"] == ("model-plan-1", "model-hypothesis-1")
    assert result["gate_decision_fingerprint"] == "b" * 64
    assert result["checkpoint_sequence"] == 6
    assert result["budgets"].used_steps == 2
    assert result["budgets"].used_tool_calls == 2
    assert result["budgets"].used_model_calls == 2
    assert result["budgets"].used_tokens == 30
    assert result["budgets"].used_cost_nanounits == 5
    assert "arguments" not in result and "model_response" not in result


@pytest.mark.anyio
async def test_graph_replans_once_then_passes_with_cumulative_budgets() -> None:
    services = FakeServices(
        plans=[
            PlanNodeResult("model-plan-1", ("tool-1",), 1, 10, 1),
            PlanNodeResult("model-plan-2", ("tool-2",), 1, 12, 2),
        ],
        gates=[
            GateNodeResult("c" * 64, GateRoute.REPLAN, "MORE_EVIDENCE_REQUIRED"),
            GateNodeResult("d" * 64, GateRoute.PASS),
        ],
    )
    result = await build_diagnosis_graph().ainvoke(state(), context=context(services))

    assert result["phase"] is GraphPhase.COMPLETE
    assert result["tool_call_ids"] == ("tool-1", "tool-2")
    assert result["budgets"].used_replans == 1
    assert result["budgets"].used_steps == 2
    assert result["budgets"].used_tool_calls == 2
    assert result["budgets"].used_model_calls == 4
    assert result["error_code"] is None
    assert services.persist_calls == services.hypothesis_calls == 2
    assert result["checkpoint_sequence"] == 11


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("gate", "expected_error"),
    [
        (
            GateNodeResult("e" * 64, GateRoute.HUMAN_HANDOFF, "INSUFFICIENT_EVIDENCE"),
            "INSUFFICIENT_EVIDENCE",
        ),
        (GateNodeResult("f" * 64, GateRoute.REPLAN), "REPLAN_BUDGET_EXHAUSTED"),
    ],
)
async def test_graph_handoff_routes_are_terminal_and_recorded(
    gate: GateNodeResult, expected_error: str
) -> None:
    services = FakeServices(gates=[gate])
    initial = state(budgets=state().budgets.model_copy(update={"max_replans": 0}))
    result = await build_diagnosis_graph().ainvoke(initial, context=context(services))

    assert result["phase"] is GraphPhase.HUMAN_HANDOFF
    assert result["error_code"] == expected_error
    assert services.handoffs == 1
    assert result["checkpoint_sequence"] == 7


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: ContextLoadResult(("same", "same")), "context evidence"),
        (lambda: PlanNodeResult("model", (), 0, 0, 0), "planned tool"),
        (lambda: PlanNodeResult("model", ("tool",), 2, 0, 0), "steps"),
        (lambda: PlanNodeResult("model", ("tool",), 1, -1, 0), "usage"),
        (lambda: EvidencePersistenceResult(()), "persisted evidence"),
        (lambda: HypothesisNodeResult("", 0, 0), "hypothesis model"),
        (lambda: HypothesisNodeResult("model", True, 0), "usage"),
        (lambda: GateNodeResult("A" * 64, GateRoute.PASS), "fingerprint"),
        (lambda: GateNodeResult("a" * 64, cast(Any, "PASS")), "route"),
        (lambda: GateNodeResult("a" * 64, GateRoute.PASS, ""), "error code"),
    ],
)
def test_node_results_fail_closed_on_invalid_content(factory: Any, message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        factory()


def test_budget_helper_rejects_unknown_invalid_and_exhausted_consumption() -> None:
    graph_budgets = state().budgets
    with pytest.raises(InvalidDomainValueError, match="unknown"):
        _consume_budget(graph_budgets, missing=1)
    with pytest.raises(InvalidDomainValueError, match="non-negative"):
        _consume_budget(graph_budgets, used_steps=True)
    with pytest.raises(ValidationError, match="cannot exceed"):
        _consume_budget(graph_budgets, used_steps=9)


@pytest.mark.parametrize(
    "batches",
    [(), ((),), (("tool-2",),), (("tool-1", "tool-1"),)],
)
def test_tool_batches_must_be_nonempty_exact_pending_order(
    batches: tuple[tuple[str, ...], ...],
) -> None:
    with pytest.raises(InvalidDomainValueError, match="tool batches"):
        _validate_tool_batches(batches, ("tool-1",), 0)


def test_tool_batches_may_group_pending_calls_in_parallel_wave_order() -> None:
    _validate_tool_batches((("tool-1", "tool-3"), ("tool-2",)), ("tool-1", "tool-2", "tool-3"), 0)


@pytest.mark.anyio
async def test_nodes_reject_wrong_phase_and_evidence_before_tools_complete() -> None:
    services = FakeServices()
    runtime = Runtime(context=context(services))
    wrong = state(phase=GraphPhase.PLANNING)
    with pytest.raises(InvalidDomainValueError, match="requires INVESTIGATING"):
        await execute_read_tools_node(wrong, runtime)
    incomplete = state(
        phase=GraphPhase.INVESTIGATING,
        tool_call_ids=("tool-1",),
    )
    with pytest.raises(InvalidDomainValueError, match="before all selected tools"):
        await persist_evidence_node(incomplete, runtime)


@pytest.mark.anyio
async def test_graph_rejects_duplicate_persisted_references() -> None:
    services = FakeServices()
    with pytest.raises(InvalidDomainValueError, match="replayed or duplicated"):
        await build_diagnosis_graph().ainvoke(
            state(evidence_ids=("evidence-context",)), context=context(services)
        )


def test_gate_router_rejects_nonterminal_phase() -> None:
    assert route_after_gate(state(phase=GraphPhase.COMPLETE)) == "complete"
    assert route_after_gate(state(phase=GraphPhase.PLANNING)) == "replan"
    assert route_after_gate(state(phase=GraphPhase.HUMAN_HANDOFF)) == "handoff"
    with pytest.raises(InvalidDomainValueError, match="unsupported"):
        route_after_gate(state(phase=GraphPhase.EVIDENCE_REVIEW))
