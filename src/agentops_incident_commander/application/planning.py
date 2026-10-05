"""Deterministic compilation of model-proposed Diagnosis tool plans."""

from __future__ import annotations

import json
from dataclasses import dataclass

from agentops_incident_commander.domain import (
    InvalidDomainValueError,
    SemanticVersion,
    ToolRegistry,
    ToolRisk,
)
from agentops_incident_commander.workflows import InvestigationPlan

from .tool_gateway import validate_diagnosis_tool_proposal


@dataclass(frozen=True, slots=True)
class PlanningBudgets:
    max_steps: int
    max_parallelism: int
    max_wall_time_ms: int
    max_model_tokens: int
    max_cost_nanounits: int

    def __post_init__(self) -> None:
        for value, maximum, field in (
            (self.max_steps, 128, "steps"),
            (self.max_parallelism, 32, "parallelism"),
            (self.max_wall_time_ms, 86_400_000, "wall time"),
            (self.max_model_tokens, 100_000_000, "model tokens"),
            (self.max_cost_nanounits, 10**18, "cost"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
                raise InvalidDomainValueError(f"planning {field} budget is outside bounds")


@dataclass(frozen=True, slots=True)
class PlanningUsage:
    model_tokens: int
    cost_nanounits: int

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (self.model_tokens, self.cost_nanounits)
        ):
            raise InvalidDomainValueError("planning usage must contain non-negative integers")


@dataclass(frozen=True, slots=True)
class ProposedToolCall:
    step_id: str
    tool_name: str
    tool_version: SemanticVersion
    arguments_json: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.step_id, self.tool_name)):
            raise InvalidDomainValueError("proposed tool call identity is invalid")
        if not isinstance(self.tool_version, SemanticVersion):
            raise InvalidDomainValueError("proposed tool version is invalid")
        try:
            arguments = json.loads(self.arguments_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise InvalidDomainValueError("proposed tool arguments must be JSON") from error
        if not isinstance(arguments, dict) or _canonical(arguments) != self.arguments_json:
            raise InvalidDomainValueError("proposed tool arguments must be a canonical JSON object")

    def arguments(self) -> dict[str, object]:
        value: dict[str, object] = json.loads(self.arguments_json)
        return value


@dataclass(frozen=True, slots=True)
class CompiledToolCall:
    step_id: str
    parallel_group: int
    tool_name: str
    tool_version: SemanticVersion
    arguments_json: str
    worst_case_duration_ms: int


@dataclass(frozen=True, slots=True)
class CompiledInvestigationPlan:
    plan: InvestigationPlan
    calls: tuple[CompiledToolCall, ...]
    maximum_parallelism: int
    worst_case_wall_time_ms: int
    model_tokens: int
    cost_nanounits: int


def compile_investigation_plan(
    plan: InvestigationPlan,
    proposals: tuple[ProposedToolCall, ...],
    *,
    registry: ToolRegistry,
    budgets: PlanningBudgets,
    usage: PlanningUsage,
) -> CompiledInvestigationPlan:
    """Compile all-or-nothing against server-owned tools and aggregate budgets."""
    if len(plan.steps) > budgets.max_steps:
        raise InvalidDomainValueError("investigation plan exceeds the step budget")
    if len(proposals) != len(plan.steps):
        raise InvalidDomainValueError("every investigation step requires exactly one tool call")
    by_step: dict[str, ProposedToolCall] = {}
    for proposal in proposals:
        if proposal.step_id in by_step:
            raise InvalidDomainValueError("investigation tool proposals contain a duplicate step")
        by_step[proposal.step_id] = proposal
    expected = {step.step_id for step in plan.steps}
    if set(by_step) != expected:
        raise InvalidDomainValueError("investigation tool proposals do not match plan steps")
    if usage.model_tokens > budgets.max_model_tokens:
        raise InvalidDomainValueError("investigation plan exceeds the model token budget")
    if usage.cost_nanounits > budgets.max_cost_nanounits:
        raise InvalidDomainValueError("investigation plan exceeds the cost budget")

    compiled: list[CompiledToolCall] = []
    durations: dict[int, list[int]] = {}
    counts: dict[int, int] = {}
    for step in plan.steps:
        proposal = by_step[step.step_id]
        definition = validate_diagnosis_tool_proposal(
            registry,
            tool_name=proposal.tool_name,
            tool_version=proposal.tool_version,
            arguments=proposal.arguments(),
        )
        if definition.risk is not ToolRisk.LOW:
            raise InvalidDomainValueError("diagnosis planning permits low-risk tools only")
        retry = definition.retry_policy
        worst_case = definition.timeout_ms * retry.max_attempts
        if retry.max_attempts > 1:
            worst_case += retry.max_backoff_ms * (retry.max_attempts - 1)
        counts[step.parallel_group] = counts.get(step.parallel_group, 0) + 1
        durations.setdefault(step.parallel_group, []).append(worst_case)
        compiled.append(
            CompiledToolCall(
                step.step_id,
                step.parallel_group,
                definition.name,
                definition.semantic_version,
                proposal.arguments_json,
                worst_case,
            )
        )
    maximum_parallelism = max(counts.values())
    if maximum_parallelism > budgets.max_parallelism:
        raise InvalidDomainValueError("investigation plan exceeds the parallelism budget")
    wall_time = sum(max(group) for group in durations.values())
    if wall_time > budgets.max_wall_time_ms:
        raise InvalidDomainValueError("investigation plan exceeds the wall-time budget")
    return CompiledInvestigationPlan(
        plan,
        tuple(compiled),
        maximum_parallelism,
        wall_time,
        usage.model_tokens,
        usage.cost_nanounits,
    )


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise InvalidDomainValueError("proposed tool arguments must be JSON") from error
