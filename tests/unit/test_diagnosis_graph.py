"""Bounded Diagnosis LangGraph nodes, parallel reads, and deterministic routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import ValidationError

from agentops_incident_commander.domain import InvalidDomainValueError
from agentops_incident_commander.infrastructure import diagnosis_checkpoint_serializer
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
    WorkflowControl,
    build_diagnosis_graph,
    execute_read_tools_node,
    load_context_node,
    node_operation_id,
    persist_evidence_node,
    route_after_gate,
    route_after_plan,
)
from agentops_incident_commander.workflows.diagnosis_graph import (
    _before_effect,
    _consume_budget,
    _route_or_cancel,
    _validate_tool_batches,
)

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
Q1 = "1" * 64
Q2 = "2" * 64
Q3 = "3" * 64


def state(**overrides: object) -> DiagnosisGraphState:
    values: dict[str, object] = {
        "state_schema_version": "1.3.0",
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
        "tool_query_fingerprints": (),
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
        self.plans = plans or [
            PlanNodeResult("model-plan-1", ("tool-1", "tool-2"), (Q1, Q2), 2, 10, 2)
        ]
        self.gates = gates or [GateNodeResult("b" * 64, GateRoute.PASS)]
        self.batches = batches or []
        self.executed: list[str] = []
        self.max_active = 0
        self.active = 0
        self.persist_calls = 0
        self.hypothesis_calls = 0
        self.handoffs = 0
        self.operations: list[tuple[str, str]] = []

    def record(self, name: str, operation_id: str) -> None:
        self.operations.append((name, operation_id))

    async def load_context(
        self, graph_state: DiagnosisGraphState, *, operation_id: str
    ) -> ContextLoadResult:
        assert graph_state.phase is GraphPhase.CONTEXT_LOADING
        self.record("load_context", operation_id)
        return ContextLoadResult(("evidence-context",))

    async def plan(self, graph_state: DiagnosisGraphState, *, operation_id: str) -> PlanNodeResult:
        assert graph_state.phase is GraphPhase.PLANNING
        self.record("plan", operation_id)
        return self.plans.pop(0)

    async def load_tool_batches(
        self, graph_state: DiagnosisGraphState, *, operation_id: str
    ) -> tuple[tuple[str, ...], ...]:
        self.record("load_tool_batches", operation_id)
        if self.batches:
            return self.batches.pop(0)
        return (graph_state.tool_call_ids[graph_state.budgets.used_tool_calls :],)

    async def execute_read_tool(
        self, graph_state: DiagnosisGraphState, tool_call_id: str, *, operation_id: str
    ) -> None:
        assert graph_state.phase is GraphPhase.INVESTIGATING
        self.record(f"execute_read_tool:{tool_call_id}", operation_id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.executed.append(tool_call_id)
        self.active -= 1

    async def persist_evidence(
        self, graph_state: DiagnosisGraphState, *, operation_id: str
    ) -> EvidencePersistenceResult:
        self.record("persist_evidence", operation_id)
        self.persist_calls += 1
        return EvidencePersistenceResult((f"evidence-tools-{self.persist_calls}",))

    async def hypothesize(
        self, graph_state: DiagnosisGraphState, *, operation_id: str
    ) -> HypothesisNodeResult:
        self.record("hypothesis", operation_id)
        self.hypothesis_calls += 1
        return HypothesisNodeResult(f"model-hypothesis-{self.hypothesis_calls}", 20, 3)

    async def evaluate_evidence_gate(
        self, graph_state: DiagnosisGraphState, *, operation_id: str
    ) -> GateNodeResult:
        assert graph_state.phase is GraphPhase.EVIDENCE_REVIEW
        self.record("evidence_gate", operation_id)
        return self.gates.pop(0)

    async def record_handoff(self, graph_state: DiagnosisGraphState, *, operation_id: str) -> None:
        assert graph_state.phase is GraphPhase.HUMAN_HANDOFF
        self.record("human_handoff", operation_id)
        self.handoffs += 1


class ApprovedPrompts:
    def __init__(self) -> None:
        self.operations: list[tuple[str, str]] = []

    async def require_approved(
        self, graph_state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> None:
        assert graph_state.prompt.prompt_id == "diagnosis"
        self.operations.append((node_name, operation_id))


class RejectingPrompts:
    async def require_approved(
        self, graph_state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> None:
        raise InvalidDomainValueError("Prompt is not approved")


def context(services: FakeServices, control: Any = None) -> DiagnosisRuntimeContext:
    if control is None:
        return DiagnosisRuntimeContext(services, ApprovedPrompts(), Clock())
    return DiagnosisRuntimeContext(services, ApprovedPrompts(), Clock(), control)


class StaticControl:
    def __init__(self, decision: WorkflowControl) -> None:
        self.choice = decision
        self.operations: list[tuple[str, str]] = []

    async def decision(
        self, graph_state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> WorkflowControl:
        self.operations.append((node_name, operation_id))
        return self.choice


class SelectiveControl:
    def __init__(self, cancel_at: str) -> None:
        self.cancel_at = cancel_at
        self.operations: list[tuple[str, str]] = []

    async def decision(
        self, graph_state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> WorkflowControl:
        self.operations.append((node_name, operation_id))
        if node_name == self.cancel_at:
            return WorkflowControl.CANCEL
        return WorkflowControl.CONTINUE


class PauseAtControl:
    def __init__(self, pause_at: str = "load_context") -> None:
        self.pause_at = pause_at
        self.operations: list[tuple[str, str]] = []

    async def decision(
        self, graph_state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> WorkflowControl:
        self.operations.append((node_name, operation_id))
        if node_name == self.pause_at:
            return WorkflowControl.PAUSE
        return WorkflowControl.CONTINUE


@pytest.mark.anyio
async def test_graph_pass_path_parallelizes_reads_and_returns_only_references() -> None:
    services = FakeServices()
    prompt_checks = ApprovedPrompts()
    graph_context = DiagnosisRuntimeContext(services, prompt_checks, Clock())
    result = await build_diagnosis_graph().ainvoke(state(), context=graph_context)

    assert result["phase"] is GraphPhase.COMPLETE
    assert result["tool_call_ids"] == ("tool-1", "tool-2")
    assert result["tool_query_fingerprints"] == (Q1, Q2)
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
    assert [name for name, _ in prompt_checks.operations] == [
        "load_context",
        "plan",
        "execute_read_tools",
        "persist_evidence",
        "hypothesis",
        "evidence_gate",
    ]


@pytest.mark.anyio
async def test_graph_replans_once_then_passes_with_cumulative_budgets() -> None:
    services = FakeServices(
        plans=[
            PlanNodeResult("model-plan-1", ("tool-1",), (Q1,), 1, 10, 1),
            PlanNodeResult("model-plan-2", ("tool-2",), (Q3,), 1, 12, 2),
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
    "initial_fingerprints",
    [(), (Q1,)],
)
async def test_graph_hands_off_before_dispatch_for_equivalent_queries(
    initial_fingerprints: tuple[str, ...],
) -> None:
    plans = [
        PlanNodeResult(
            "model-plan-repeat",
            ("tool-new-1", "tool-new-2"),
            (Q1, Q1) if not initial_fingerprints else (Q1, Q2),
            2,
            10,
            1,
        )
    ]
    services = FakeServices(plans=plans)
    result = await build_diagnosis_graph().ainvoke(
        state(tool_query_fingerprints=initial_fingerprints), context=context(services)
    )

    assert result["phase"] is GraphPhase.HUMAN_HANDOFF
    assert result["error_code"] == "REPEATED_EQUIVALENT_QUERY"
    assert result["tool_call_ids"] == ()
    assert result["budgets"].used_steps == 2
    assert result["budgets"].used_model_calls == 1
    assert services.executed == []
    assert services.handoffs == 1


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
        (lambda: PlanNodeResult("model", (), (), 0, 0, 0), "planned tool"),
        (lambda: PlanNodeResult("model", ("tool",), (), 1, 0, 0), "fingerprints"),
        (lambda: PlanNodeResult("model", ("tool",), (Q1,), 2, 0, 0), "steps"),
        (lambda: PlanNodeResult("model", ("tool",), (Q1,), 1, -1, 0), "usage"),
        (lambda: PlanNodeResult("model", ("tool",), (Q1, Q2), 1, 0, 0), "must match"),
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


def test_plan_router_accepts_only_investigation_or_handoff() -> None:
    assert route_after_plan(state(phase=GraphPhase.INVESTIGATING)) == "investigate"
    assert route_after_plan(state(phase=GraphPhase.HUMAN_HANDOFF)) == "handoff"
    with pytest.raises(InvalidDomainValueError, match="unsupported"):
        route_after_plan(state(phase=GraphPhase.PLANNING))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "cancel_at",
    [
        "load_context",
        "plan",
        "execute_read_tools",
        "persist_evidence",
        "hypothesis",
        "evidence_gate",
        "human_handoff",
    ],
)
async def test_cancel_stops_at_each_safe_boundary_before_its_effect(cancel_at: str) -> None:
    gates = (
        [GateNodeResult("f" * 64, GateRoute.HUMAN_HANDOFF, "REVIEW_REQUIRED")]
        if cancel_at == "human_handoff"
        else None
    )
    services = FakeServices(gates=gates)
    control = SelectiveControl(cancel_at)

    result = await build_diagnosis_graph().ainvoke(state(), context=context(services, control))

    assert result["phase"] is GraphPhase.CANCELLED
    assert result["error_code"] == "CANCELLED_AT_SAFE_BOUNDARY"
    assert all(name != cancel_at for name, _ in services.operations)
    assert control.operations[-1][0] == cancel_at


@pytest.mark.anyio
async def test_pause_interrupt_resumes_same_checkpoint_without_duplicate_effect() -> None:
    services = FakeServices()
    control = PauseAtControl()
    graph = build_diagnosis_graph(
        checkpointer=InMemorySaver(serde=diagnosis_checkpoint_serializer())
    )
    config: RunnableConfig = {"configurable": {"thread_id": "diagnosis-pause-resume"}}

    paused = await graph.ainvoke(state(), config, context=context(services, control))

    assert services.operations == []
    assert paused["__interrupt__"][0].value["kind"] == "DIAGNOSIS_PAUSED"
    resumed = await graph.ainvoke(
        Command[Any](resume={"action": "RESUME"}), config, context=context(services, control)
    )
    assert resumed["phase"] is GraphPhase.COMPLETE
    assert len(services.operations) == 8
    assert control.operations[0] == control.operations[1]


@pytest.mark.anyio
async def test_pause_can_resume_as_cancel_without_running_the_node_effect() -> None:
    services = FakeServices()
    control = PauseAtControl()
    graph = build_diagnosis_graph(
        checkpointer=InMemorySaver(serde=diagnosis_checkpoint_serializer())
    )
    config: RunnableConfig = {"configurable": {"thread_id": "diagnosis-pause-cancel"}}

    await graph.ainvoke(state(), config, context=context(services, control))
    cancelled = await graph.ainvoke(
        Command[Any](resume={"action": "CANCEL"}), config, context=context(services, control)
    )

    assert cancelled["phase"] is GraphPhase.CANCELLED
    assert cancelled["checkpoint_sequence"] == 1
    assert services.operations == []


@pytest.mark.anyio
async def test_pause_rejects_invalid_resume_and_control_directives() -> None:
    services = FakeServices()
    graph = build_diagnosis_graph(
        checkpointer=InMemorySaver(serde=diagnosis_checkpoint_serializer())
    )
    config: RunnableConfig = {"configurable": {"thread_id": "diagnosis-invalid-resume"}}
    await graph.ainvoke(state(), config, context=context(services, PauseAtControl()))
    with pytest.raises(InvalidDomainValueError, match="resume directive"):
        await graph.ainvoke(
            Command[Any](resume={"action": "INVALID"}),
            config,
            context=context(services, PauseAtControl()),
        )

    invalid_control = StaticControl(cast(WorkflowControl, "INVALID"))
    with pytest.raises(InvalidDomainValueError, match="control decision"):
        await _before_effect(
            state(), Runtime(context=context(services, invalid_control)), "load_context"
        )


@pytest.mark.anyio
async def test_prompt_authorization_precedes_control_and_node_effects() -> None:
    services = FakeServices()
    control = StaticControl(WorkflowControl.CONTINUE)
    runtime = Runtime(
        context=DiagnosisRuntimeContext(services, RejectingPrompts(), Clock(), control)
    )

    with pytest.raises(InvalidDomainValueError, match="not approved"):
        await load_context_node(state(), runtime)

    assert control.operations == []
    assert services.operations == []


@pytest.mark.anyio
async def test_operation_identity_is_stable_for_exact_node_replay() -> None:
    services = FakeServices()
    runtime = Runtime(context=context(services))
    initial = state()

    await load_context_node(initial, runtime)
    await load_context_node(initial, runtime)

    assert services.operations[0][1] == services.operations[1][1]
    assert node_operation_id(initial, "load_context") != node_operation_id(initial, "plan")
    assert node_operation_id(initial, "load_context") != node_operation_id(
        state(checkpoint_sequence=1), "load_context"
    )
    with pytest.raises(InvalidDomainValueError, match="identity inputs"):
        node_operation_id(initial, "")
    with pytest.raises(InvalidDomainValueError, match="identity inputs"):
        node_operation_id(cast(DiagnosisGraphState, {}), "load_context")


def test_control_routes_accept_cancellation_and_reject_unexpected_phase() -> None:
    cancelled = state(phase=GraphPhase.CANCELLED)
    assert route_after_plan(cancelled) == "cancelled"
    assert route_after_gate(cancelled) == "cancelled"
    assert _route_or_cancel(cancelled, GraphPhase.PLANNING, "next", "node") == "cancelled"
    assert (
        _route_or_cancel(state(phase=GraphPhase.PLANNING), GraphPhase.PLANNING, "next", "node")
        == "next"
    )
    with pytest.raises(InvalidDomainValueError, match="unsupported"):
        _route_or_cancel(state(), GraphPhase.PLANNING, "next", "node")
