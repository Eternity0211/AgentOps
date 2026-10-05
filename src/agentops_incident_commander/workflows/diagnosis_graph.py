"""Durable-shape LangGraph orchestration for bounded Diagnosis workflows."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from agentops_incident_commander.domain import InvalidDomainValueError, utc_now

from .state import DiagnosisGraphState, GraphBudgetState, GraphPhase

DIAGNOSIS_NODE_NAMES = frozenset(
    {
        "load_context",
        "plan",
        "execute_read_tools",
        "persist_evidence",
        "hypothesis",
        "evidence_gate",
        "human_handoff",
    }
)


class GateRoute(StrEnum):
    """Deterministic Evidence Gate route; never supplied by a model."""

    PASS = "PASS"
    REPLAN = "REPLAN"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"


class WorkflowControl(StrEnum):
    CONTINUE = "CONTINUE"
    PAUSE = "PAUSE"
    CANCEL = "CANCEL"


class DiagnosisControlPort(Protocol):
    async def decision(
        self, state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> WorkflowControl: ...


class DiagnosisPromptAuthorizationPort(Protocol):
    async def require_approved(
        self, state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> None: ...


class ContinueDiagnosisControl:
    async def decision(
        self, state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> WorkflowControl:
        return WorkflowControl.CONTINUE


@dataclass(frozen=True, slots=True)
class ContextLoadResult:
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identifiers(self.evidence_ids, field_name="context evidence")


@dataclass(frozen=True, slots=True)
class PlanNodeResult:
    """References produced after a model plan is compiled and stored."""

    model_call_id: str
    tool_call_ids: tuple[str, ...]
    query_fingerprints: tuple[str, ...]
    used_steps: int
    model_tokens: int
    cost_nanounits: int

    def __post_init__(self) -> None:
        _validate_identifiers((self.model_call_id,), field_name="planning model call")
        _validate_identifiers(self.tool_call_ids, field_name="planned tool call", allow_empty=False)
        _validate_fingerprints(self.query_fingerprints, field_name="planned query")
        _validate_non_negative(
            (self.used_steps, self.model_tokens, self.cost_nanounits), field_name="planning usage"
        )
        if self.used_steps == 0 or self.used_steps != len(self.tool_call_ids):
            raise InvalidDomainValueError("planning steps must match planned tool calls")
        if len(self.query_fingerprints) != len(self.tool_call_ids):
            raise InvalidDomainValueError(
                "planning query fingerprints must match planned tool calls"
            )


@dataclass(frozen=True, slots=True)
class EvidencePersistenceResult:
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_identifiers(self.evidence_ids, field_name="persisted evidence", allow_empty=False)


@dataclass(frozen=True, slots=True)
class HypothesisNodeResult:
    model_call_id: str
    model_tokens: int
    cost_nanounits: int

    def __post_init__(self) -> None:
        _validate_identifiers((self.model_call_id,), field_name="hypothesis model call")
        _validate_non_negative(
            (self.model_tokens, self.cost_nanounits), field_name="hypothesis usage"
        )


@dataclass(frozen=True, slots=True)
class GateNodeResult:
    decision_fingerprint: str
    route: GateRoute
    error_code: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.decision_fingerprint, str)
            or len(self.decision_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in self.decision_fingerprint)
        ):
            raise InvalidDomainValueError("gate decision fingerprint must be lowercase SHA-256")
        if not isinstance(self.route, GateRoute):
            raise InvalidDomainValueError("gate route must be deterministic and typed")
        if self.error_code is not None:
            _validate_identifiers((self.error_code,), field_name="gate error code")


class DiagnosisWorkflowServices(Protocol):
    """Ports used by graph nodes; implementations retain persistence and gateway authority."""

    async def load_context(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> ContextLoadResult: ...

    async def plan(self, state: DiagnosisGraphState, *, operation_id: str) -> PlanNodeResult:
        """Return only after compiling and durably storing exact read-tool calls."""
        ...

    async def load_tool_batches(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> tuple[tuple[str, ...], ...]:
        """Load deterministic parallel waves for all selected tool-call IDs."""
        ...

    async def execute_read_tool(
        self, state: DiagnosisGraphState, tool_call_id: str, *, operation_id: str
    ) -> None:
        """Invoke one stored compiled call through the diagnosis-only Tool Gateway."""
        ...

    async def persist_evidence(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> EvidencePersistenceResult: ...

    async def hypothesize(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> HypothesisNodeResult: ...

    async def evaluate_evidence_gate(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> GateNodeResult:
        """Return a route derived by the deterministic Evidence Gate, never the model."""
        ...

    async def record_handoff(self, state: DiagnosisGraphState, *, operation_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class DiagnosisRuntimeContext:
    services: DiagnosisWorkflowServices
    prompts: DiagnosisPromptAuthorizationPort
    clock: Callable[[], datetime] = field(default=utc_now)
    control: DiagnosisControlPort = field(default_factory=ContinueDiagnosisControl)


async def load_context_node(
    state: DiagnosisGraphState, runtime: Runtime[DiagnosisRuntimeContext]
) -> dict[str, object]:
    _require_phase(state, GraphPhase.CONTEXT_LOADING)
    operation_id, control = await _before_effect(state, runtime, "load_context")
    if control is not None:
        return control
    result = await runtime.context.services.load_context(state, operation_id=operation_id)
    return _transition(
        state,
        runtime,
        phase=GraphPhase.PLANNING,
        evidence_ids=_append_unique(state.evidence_ids, result.evidence_ids, "evidence"),
    )


async def plan_node(
    state: DiagnosisGraphState, runtime: Runtime[DiagnosisRuntimeContext]
) -> dict[str, object]:
    _require_phase(state, GraphPhase.PLANNING)
    operation_id, control = await _before_effect(state, runtime, "plan")
    if control is not None:
        return control
    result = await runtime.context.services.plan(state, operation_id=operation_id)
    budgets = _consume_budget(
        state.budgets,
        used_steps=result.used_steps,
        used_model_calls=1,
        used_tokens=result.model_tokens,
        used_cost_nanounits=result.cost_nanounits,
    )
    common_updates: dict[str, object] = {
        "budgets": budgets,
        "model_call_ids": _append_unique(
            state.model_call_ids, (result.model_call_id,), "model call"
        ),
    }
    repeated = set(result.query_fingerprints) & set(state.tool_query_fingerprints)
    repeated_within_plan = len(set(result.query_fingerprints)) != len(result.query_fingerprints)
    if repeated or repeated_within_plan:
        return _transition(
            state,
            runtime,
            phase=GraphPhase.HUMAN_HANDOFF,
            error_code="REPEATED_EQUIVALENT_QUERY",
            **common_updates,
        )
    return _transition(
        state,
        runtime,
        phase=GraphPhase.INVESTIGATING,
        tool_call_ids=_append_unique(state.tool_call_ids, result.tool_call_ids, "tool call"),
        tool_query_fingerprints=_append_unique(
            state.tool_query_fingerprints, result.query_fingerprints, "tool query"
        ),
        error_code=None,
        **common_updates,
    )


async def execute_read_tools_node(
    state: DiagnosisGraphState, runtime: Runtime[DiagnosisRuntimeContext]
) -> dict[str, object]:
    _require_phase(state, GraphPhase.INVESTIGATING)
    operation_id, control = await _before_effect(state, runtime, "execute_read_tools")
    if control is not None:
        return control
    batches = await runtime.context.services.load_tool_batches(state, operation_id=operation_id)
    _validate_tool_batches(batches, state.tool_call_ids, state.budgets.used_tool_calls)
    pending_ids = state.tool_call_ids[state.budgets.used_tool_calls :]
    for batch in batches:
        async with asyncio.TaskGroup() as tasks:
            for tool_call_id in batch:
                tasks.create_task(
                    runtime.context.services.execute_read_tool(
                        state,
                        tool_call_id,
                        operation_id=node_operation_id(state, f"execute_read_tools:{tool_call_id}"),
                    ),
                    name=f"diagnosis-tool:{tool_call_id}",
                )
    budgets = _consume_budget(state.budgets, used_tool_calls=len(pending_ids))
    return _transition(state, runtime, budgets=budgets)


async def persist_evidence_node(
    state: DiagnosisGraphState, runtime: Runtime[DiagnosisRuntimeContext]
) -> dict[str, object]:
    _require_phase(state, GraphPhase.INVESTIGATING)
    if state.budgets.used_tool_calls != len(state.tool_call_ids):
        raise InvalidDomainValueError("evidence cannot persist before all selected tools complete")
    operation_id, control = await _before_effect(state, runtime, "persist_evidence")
    if control is not None:
        return control
    result = await runtime.context.services.persist_evidence(state, operation_id=operation_id)
    return _transition(
        state,
        runtime,
        phase=GraphPhase.HYPOTHESIS,
        evidence_ids=_append_unique(state.evidence_ids, result.evidence_ids, "evidence"),
    )


async def hypothesis_node(
    state: DiagnosisGraphState, runtime: Runtime[DiagnosisRuntimeContext]
) -> dict[str, object]:
    _require_phase(state, GraphPhase.HYPOTHESIS)
    operation_id, control = await _before_effect(state, runtime, "hypothesis")
    if control is not None:
        return control
    result = await runtime.context.services.hypothesize(state, operation_id=operation_id)
    budgets = _consume_budget(
        state.budgets,
        used_model_calls=1,
        used_tokens=result.model_tokens,
        used_cost_nanounits=result.cost_nanounits,
    )
    return _transition(
        state,
        runtime,
        phase=GraphPhase.EVIDENCE_REVIEW,
        budgets=budgets,
        model_call_ids=_append_unique(state.model_call_ids, (result.model_call_id,), "model call"),
    )


async def evidence_gate_node(
    state: DiagnosisGraphState, runtime: Runtime[DiagnosisRuntimeContext]
) -> dict[str, object]:
    _require_phase(state, GraphPhase.EVIDENCE_REVIEW)
    operation_id, control = await _before_effect(state, runtime, "evidence_gate")
    if control is not None:
        return control
    result = await runtime.context.services.evaluate_evidence_gate(state, operation_id=operation_id)
    budgets = state.budgets
    error_code = result.error_code
    if result.route is GateRoute.PASS:
        phase = GraphPhase.COMPLETE
    elif result.route is GateRoute.REPLAN and budgets.used_replans < budgets.max_replans:
        phase = GraphPhase.PLANNING
        budgets = _consume_budget(budgets, used_replans=1)
    else:
        phase = GraphPhase.HUMAN_HANDOFF
        if result.route is GateRoute.REPLAN:
            error_code = error_code or "REPLAN_BUDGET_EXHAUSTED"
    return _transition(
        state,
        runtime,
        phase=phase,
        budgets=budgets,
        gate_decision_fingerprint=result.decision_fingerprint,
        error_code=error_code,
    )


async def human_handoff_node(
    state: DiagnosisGraphState, runtime: Runtime[DiagnosisRuntimeContext]
) -> dict[str, object]:
    _require_phase(state, GraphPhase.HUMAN_HANDOFF)
    operation_id, control = await _before_effect(state, runtime, "human_handoff")
    if control is not None:
        return control
    await runtime.context.services.record_handoff(state, operation_id=operation_id)
    return _transition(state, runtime)


def route_after_gate(state: DiagnosisGraphState) -> str:
    if state.phase is GraphPhase.CANCELLED:
        return "cancelled"
    if state.phase is GraphPhase.COMPLETE:
        return "complete"
    if state.phase is GraphPhase.PLANNING:
        return "replan"
    if state.phase is GraphPhase.HUMAN_HANDOFF:
        return "handoff"
    raise InvalidDomainValueError("evidence gate produced an unsupported graph phase")


def route_after_plan(state: DiagnosisGraphState) -> str:
    if state.phase is GraphPhase.CANCELLED:
        return "cancelled"
    if state.phase is GraphPhase.INVESTIGATING:
        return "investigate"
    if state.phase is GraphPhase.HUMAN_HANDOFF:
        return "handoff"
    raise InvalidDomainValueError("planning produced an unsupported graph phase")


def route_after_context(state: DiagnosisGraphState) -> str:
    return _route_or_cancel(state, GraphPhase.PLANNING, "plan", "context loading")


def route_after_tools(state: DiagnosisGraphState) -> str:
    return _route_or_cancel(state, GraphPhase.INVESTIGATING, "persist", "tool execution")


def route_after_persistence(state: DiagnosisGraphState) -> str:
    return _route_or_cancel(state, GraphPhase.HYPOTHESIS, "hypothesis", "evidence persistence")


def route_after_hypothesis(state: DiagnosisGraphState) -> str:
    return _route_or_cancel(state, GraphPhase.EVIDENCE_REVIEW, "gate", "hypothesis generation")


def build_diagnosis_graph(
    *, checkpointer: BaseCheckpointSaver[str] | None = None
) -> CompiledStateGraph[
    DiagnosisGraphState,
    DiagnosisRuntimeContext,
    DiagnosisGraphState,
    DiagnosisGraphState,
]:
    """Compile the bounded Diagnosis graph without a checkpointer."""
    builder = StateGraph(DiagnosisGraphState, context_schema=DiagnosisRuntimeContext)
    builder.add_node("load_context", load_context_node)
    builder.add_node("plan", plan_node)
    builder.add_node("execute_read_tools", execute_read_tools_node)
    builder.add_node("persist_evidence", persist_evidence_node)
    builder.add_node("hypothesis", hypothesis_node)
    builder.add_node("evidence_gate", evidence_gate_node)
    builder.add_node("human_handoff", human_handoff_node)
    builder.add_edge(START, "load_context")
    builder.add_conditional_edges(
        "load_context", route_after_context, {"plan": "plan", "cancelled": END}
    )
    builder.add_conditional_edges(
        "plan",
        route_after_plan,
        {
            "investigate": "execute_read_tools",
            "handoff": "human_handoff",
            "cancelled": END,
        },
    )
    builder.add_conditional_edges(
        "execute_read_tools",
        route_after_tools,
        {"persist": "persist_evidence", "cancelled": END},
    )
    builder.add_conditional_edges(
        "persist_evidence",
        route_after_persistence,
        {"hypothesis": "hypothesis", "cancelled": END},
    )
    builder.add_conditional_edges(
        "hypothesis",
        route_after_hypothesis,
        {"gate": "evidence_gate", "cancelled": END},
    )
    builder.add_conditional_edges(
        "evidence_gate",
        route_after_gate,
        {
            "complete": END,
            "replan": "plan",
            "handoff": "human_handoff",
            "cancelled": END,
        },
    )
    builder.add_edge("human_handoff", END)
    return builder.compile(checkpointer=checkpointer)


def node_operation_id(state: DiagnosisGraphState, node_name: str) -> str:
    """Derive a stable idempotency identity for one node attempt boundary."""
    if (
        not isinstance(state, DiagnosisGraphState)
        or not isinstance(node_name, str)
        or not node_name
    ):
        raise InvalidDomainValueError("node operation identity inputs are invalid")
    canonical = json.dumps(
        {
            "checkpoint_sequence": state.checkpoint_sequence,
            "graph_version": state.graph_version,
            "node_name": node_name,
            "tenant_id": state.tenant_id,
            "workflow_run_id": state.workflow_run_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


async def _before_effect(
    state: DiagnosisGraphState,
    runtime: Runtime[DiagnosisRuntimeContext],
    node_name: str,
) -> tuple[str, dict[str, object] | None]:
    operation_id = node_operation_id(state, node_name)
    await runtime.context.prompts.require_approved(
        state, node_name=node_name, operation_id=operation_id
    )
    decision = await runtime.context.control.decision(
        state, node_name=node_name, operation_id=operation_id
    )
    if not isinstance(decision, WorkflowControl):
        raise InvalidDomainValueError("workflow control decision is invalid")
    if decision is WorkflowControl.PAUSE:
        response: Any = interrupt(
            {
                "kind": "DIAGNOSIS_PAUSED",
                "node_name": node_name,
                "operation_id": operation_id,
            },
            response_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"action": {"enum": ["RESUME", "CANCEL"], "type": "string"}},
                "required": ["action"],
            },
        )
        if not isinstance(response, dict) or response.get("action") not in {"RESUME", "CANCEL"}:
            raise InvalidDomainValueError("workflow resume directive is invalid")
        if response["action"] == "CANCEL":
            decision = WorkflowControl.CANCEL
    if decision is WorkflowControl.CANCEL:
        update = _transition(
            state,
            runtime,
            phase=GraphPhase.CANCELLED,
            error_code="CANCELLED_AT_SAFE_BOUNDARY",
        )
        return operation_id, update
    return operation_id, None


def _route_or_cancel(
    state: DiagnosisGraphState,
    expected_phase: GraphPhase,
    continuation: str,
    node_description: str,
) -> str:
    if state.phase is GraphPhase.CANCELLED:
        return "cancelled"
    if state.phase is expected_phase:
        return continuation
    raise InvalidDomainValueError(f"{node_description} produced an unsupported graph phase")


def _transition(
    state: DiagnosisGraphState,
    runtime: Runtime[DiagnosisRuntimeContext],
    **updates: object,
) -> dict[str, object]:
    values = state.model_dump()
    values.update(updates)
    values["checkpoint_sequence"] = state.checkpoint_sequence + 1
    values["updated_at"] = runtime.context.clock()
    validated = DiagnosisGraphState.model_validate(values)
    changed_fields = set(updates) | {"checkpoint_sequence", "updated_at"}
    return {field: getattr(validated, field) for field in changed_fields}


def _consume_budget(budgets: GraphBudgetState, **increments: int) -> GraphBudgetState:
    values = budgets.model_dump()
    for field_name, increment in increments.items():
        if field_name not in values:
            raise InvalidDomainValueError("unknown graph budget field")
        if not isinstance(increment, int) or isinstance(increment, bool) or increment < 0:
            raise InvalidDomainValueError("graph budget increments must be non-negative integers")
        values[field_name] += increment
    return GraphBudgetState.model_validate(values)


def _append_unique(
    existing: tuple[str, ...], additions: tuple[str, ...], field_name: str
) -> tuple[str, ...]:
    combined = existing + additions
    if len(set(combined)) != len(combined):
        raise InvalidDomainValueError(f"{field_name} references cannot be replayed or duplicated")
    return combined


def _validate_identifiers(
    values: tuple[str, ...], *, field_name: str, allow_empty: bool = True
) -> None:
    if not isinstance(values, tuple) or (not allow_empty and not values):
        raise InvalidDomainValueError(f"{field_name} identifiers are invalid")
    if any(not isinstance(value, str) or not value for value in values) or len(set(values)) != len(
        values
    ):
        raise InvalidDomainValueError(f"{field_name} identifiers are invalid")


def _validate_non_negative(values: tuple[int, ...], *, field_name: str) -> None:
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
        raise InvalidDomainValueError(f"{field_name} must contain non-negative integers")


def _validate_fingerprints(values: tuple[str, ...], *, field_name: str) -> None:
    if (
        not isinstance(values, tuple)
        or not values
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in values
        )
    ):
        raise InvalidDomainValueError(f"{field_name} fingerprints are invalid")


def _validate_tool_batches(
    batches: tuple[tuple[str, ...], ...], all_ids: tuple[str, ...], completed_count: int
) -> None:
    pending = all_ids[completed_count:]
    if (
        not isinstance(batches, tuple)
        or not batches
        or any(not isinstance(batch, tuple) or not batch for batch in batches)
    ):
        raise InvalidDomainValueError("tool batches must contain non-empty deterministic waves")
    flattened = tuple(tool_call_id for batch in batches for tool_call_id in batch)
    if set(flattened) != set(pending) or len(flattened) != len(pending):
        raise InvalidDomainValueError("tool batches must exactly match pending compiled calls")


def _require_phase(state: DiagnosisGraphState, expected: GraphPhase) -> None:
    if state.phase is not expected:
        raise InvalidDomainValueError(
            f"diagnosis node requires {expected.value}, received {state.phase.value}"
        )
