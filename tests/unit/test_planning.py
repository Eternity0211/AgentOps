"""Diagnosis planning compiles model proposals into bounded server-owned calls."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from agentops_incident_commander.application import (
    PlanningBudgets,
    PlanningUsage,
    ProposedToolCall,
    compile_investigation_plan,
    tool_query_fingerprint,
    validate_diagnosis_tool_proposal,
)
from agentops_incident_commander.application.tool_gateway import ToolPayloadValidationError
from agentops_incident_commander.domain import (
    EvidenceSourceType,
    InvalidDomainValueError,
    Permission,
    RetryableToolError,
    SemanticVersion,
    ToolAccessClass,
    ToolAuditPolicy,
    ToolDefinition,
    ToolIdempotency,
    ToolNotFoundError,
    ToolRegistry,
    ToolRetryPolicy,
    ToolRisk,
    ToolSchema,
    ToolVersionDisabledError,
    ToolVersionRange,
)
from agentops_incident_commander.workflows import InvestigationPlan, InvestigationStep

V1 = SemanticVersion("1.0.0")
V2 = SemanticVersion("2.0.0")
SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {"service": {"maxLength": 200, "minLength": 1, "type": "string"}},
    "required": ["service"],
    "type": "object",
}


def definition(
    *,
    name: str = "query_logs",
    version: SemanticVersion = V1,
    access: ToolAccessClass = ToolAccessClass.READ,
    risk: ToolRisk = ToolRisk.LOW,
    timeout_ms: int = 100,
    attempts: int = 1,
    max_input_bytes: int = 4096,
) -> ToolDefinition:
    retry = (
        ToolRetryPolicy(1, 0, 0, frozenset())
        if attempts == 1
        else ToolRetryPolicy(attempts, 10, 20, frozenset({RetryableToolError.TIMEOUT}))
    )
    return ToolDefinition(
        name=name,
        semantic_version=version,
        input_schema=ToolSchema.from_mapping(V1, SCHEMA),
        output_schema=ToolSchema.from_mapping(
            V1,
            {
                "additionalProperties": False,
                "properties": {"items": {"items": {"type": "string"}, "type": "array"}},
                "required": ["items"],
                "type": "object",
            },
        ),
        access_class=access,
        risk=risk,
        required_permission=(
            Permission.EVIDENCE_READ
            if access is ToolAccessClass.READ
            else Permission.APPROVED_ACTION_EXECUTE
        ),
        timeout_ms=timeout_ms,
        retry_policy=retry,
        idempotency=(
            ToolIdempotency.NOT_APPLICABLE
            if access is ToolAccessClass.READ
            else ToolIdempotency.REQUIRED_RESULT_REPLAY
        ),
        audit=ToolAuditPolicy("tool.call", V1),
        max_input_bytes=max_input_bytes,
        max_result_bytes=4096,
    )


def plan(*groups: int) -> InvestigationPlan:
    steps = tuple(
        InvestigationStep(
            step_id=f"step-{index}",
            objective=f"Collect evidence {index}",
            expected_source=EvidenceSourceType.LOG,
            depends_on=(() if index == 1 else (f"step-{index - 1}",)),
            parallel_group=group,
        )
        for index, group in enumerate(groups, 1)
    )
    return InvestigationPlan(
        schema_version="1.0.0", plan_id="plan-1", summary="Bounded investigation", steps=steps
    )


def proposal(
    step_id: str, *, name: str = "query_logs", value: object = "orders"
) -> ProposedToolCall:
    return ProposedToolCall(
        step_id,
        name,
        V1,
        json.dumps({"service": value}, sort_keys=True, separators=(",", ":")),
    )


def budgets(**overrides: int) -> PlanningBudgets:
    values = {
        "max_steps": 4,
        "max_parallelism": 2,
        "max_wall_time_ms": 1_000,
        "max_model_tokens": 1_000,
        "max_cost_nanounits": 1_000,
    }
    values.update(overrides)
    return PlanningBudgets(**values)


def test_compiles_in_plan_order_and_calculates_parallel_worst_case() -> None:
    registry = ToolRegistry(
        (
            definition(timeout_ms=100, attempts=2),
            definition(name="query_metrics", timeout_ms=70),
        )
    )
    value = compile_investigation_plan(
        plan(0, 0, 1),
        (
            proposal("step-3", value="payments"),
            proposal("step-1"),
            proposal("step-2", name="query_metrics"),
        ),
        registry=registry,
        budgets=budgets(max_steps=3),
        usage=PlanningUsage(250, 30),
    )

    assert tuple(call.step_id for call in value.calls) == ("step-1", "step-2", "step-3")
    assert tuple(call.worst_case_duration_ms for call in value.calls) == (220, 70, 220)
    assert value.maximum_parallelism == 2
    assert value.worst_case_wall_time_ms == 440
    assert (value.model_tokens, value.cost_nanounits) == (250, 30)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_steps", 0),
        ("max_parallelism", True),
        ("max_wall_time_ms", 86_400_001),
        ("max_model_tokens", 100_000_001),
        ("max_cost_nanounits", 10**18 + 1),
    ],
)
def test_planning_budgets_reject_invalid_bounds(field: str, value: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="budget is outside bounds"):
        budgets(**{field: value})


@pytest.mark.parametrize(("tokens", "cost"), [(-1, 0), (0, -1), (True, 0)])
def test_planning_usage_rejects_invalid_values(tokens: Any, cost: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="non-negative integers"):
        PlanningUsage(tokens, cost)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (("", "query_logs", V1, "{}"), "identity"),
        (("step-1", "query_logs", "1.0.0", "{}"), "version"),
        (("step-1", "query_logs", V1, "{"), "must be JSON"),
        (("step-1", "query_logs", V1, "[]"), "canonical JSON object"),
        (("step-1", "query_logs", V1, '{"service": "orders"}'), "canonical JSON object"),
    ],
)
def test_proposal_rejects_invalid_or_noncanonical_content(
    values: tuple[Any, Any, Any, Any], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        ProposedToolCall(*values)


def test_proposal_rejects_non_json_numeric_value() -> None:
    with pytest.raises(InvalidDomainValueError, match="must be JSON"):
        ProposedToolCall("step-1", "query_logs", V1, '{"service":NaN}')


@pytest.mark.parametrize(
    ("planned", "proposals", "limit", "message"),
    [
        (plan(0, 1), (proposal("step-1"), proposal("step-2")), {"max_steps": 1}, "step"),
        (plan(0), (), {}, "exactly one"),
        (plan(0, 1), (proposal("step-1"), proposal("step-1")), {}, "duplicate"),
        (plan(0), (proposal("other"),), {}, "do not match"),
    ],
)
def test_compile_rejects_plan_and_proposal_mismatches(
    planned: InvestigationPlan,
    proposals: tuple[ProposedToolCall, ...],
    limit: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        compile_investigation_plan(
            planned,
            proposals,
            registry=ToolRegistry((definition(),)),
            budgets=budgets(**limit),
            usage=PlanningUsage(0, 0),
        )


@pytest.mark.parametrize(
    ("usage", "message"),
    [(PlanningUsage(1_001, 0), "token"), (PlanningUsage(0, 1_001), "cost")],
)
def test_compile_rejects_model_usage_budgets(usage: PlanningUsage, message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        compile_investigation_plan(
            plan(0),
            (proposal("step-1"),),
            registry=ToolRegistry((definition(),)),
            budgets=budgets(),
            usage=usage,
        )


def test_compile_rejects_parallelism_and_wall_time_budgets() -> None:
    registry = ToolRegistry((definition(timeout_ms=100),))
    with pytest.raises(InvalidDomainValueError, match="parallelism"):
        compile_investigation_plan(
            plan(0, 0),
            (proposal("step-1"), proposal("step-2", value="payments")),
            registry=registry,
            budgets=budgets(max_parallelism=1),
            usage=PlanningUsage(0, 0),
        )
    with pytest.raises(InvalidDomainValueError, match="wall-time"):
        compile_investigation_plan(
            plan(0, 1),
            (proposal("step-1"), proposal("step-2", value="payments")),
            registry=registry,
            budgets=budgets(max_wall_time_ms=199),
            usage=PlanningUsage(0, 0),
        )


def test_validation_rejects_unknown_disabled_write_and_non_low_risk_tools() -> None:
    base = definition()
    with pytest.raises(ToolNotFoundError):
        validate_diagnosis_tool_proposal(
            ToolRegistry((base,)), tool_name="missing", tool_version=V1, arguments={}
        )
    disabled = ToolRegistry(
        (base, definition(version=V2)),
        enabled_ranges={"query_logs": ToolVersionRange(V2, V2)},
    )
    with pytest.raises(ToolVersionDisabledError):
        validate_diagnosis_tool_proposal(
            disabled, tool_name="query_logs", tool_version=V1, arguments={"service": "orders"}
        )
    write = definition(access=ToolAccessClass.WRITE)
    with pytest.raises(ToolPayloadValidationError) as raised:
        validate_diagnosis_tool_proposal(
            ToolRegistry((write,)),
            tool_name="query_logs",
            tool_version=V1,
            arguments={"service": "orders"},
        )
    assert raised.value.code == "DIAGNOSIS_WRITE_TOOL_FORBIDDEN"
    medium = definition(risk=ToolRisk.MEDIUM)
    with pytest.raises(InvalidDomainValueError, match="low-risk"):
        compile_investigation_plan(
            plan(0),
            (proposal("step-1"),),
            registry=ToolRegistry((medium,)),
            budgets=budgets(),
            usage=PlanningUsage(0, 0),
        )


@pytest.mark.parametrize(
    ("tool", "arguments", "code"),
    [
        (definition(max_input_bytes=20), {"service": "orders-service"}, "INPUT_LIMIT_EXCEEDED"),
        (definition(), {}, "SCHEMA_VALIDATION_FAILED"),
        (definition(), {"service": "https://unsafe.example"}, "DIAGNOSIS_UNSAFE_ARGUMENT"),
    ],
)
def test_validation_rejects_input_limit_schema_and_injection(
    tool: ToolDefinition, arguments: dict[str, object], code: str
) -> None:
    with pytest.raises(ToolPayloadValidationError) as raised:
        validate_diagnosis_tool_proposal(
            ToolRegistry((tool,)),
            tool_name=tool.name,
            tool_version=tool.semantic_version,
            arguments=arguments,
        )
    assert raised.value.code == code


def test_compiled_plan_is_frozen() -> None:
    result = compile_investigation_plan(
        plan(0),
        (proposal("step-1"),),
        registry=ToolRegistry((definition(),)),
        budgets=budgets(),
        usage=PlanningUsage(0, 0),
    )
    with pytest.raises(AttributeError):
        result.calls = ()  # type: ignore[misc]
    assert replace(result.calls[0], step_id="copy").step_id == "copy"


def test_query_fingerprint_is_step_independent_but_binds_tool_version_and_arguments() -> None:
    first = proposal("step-1")
    equivalent = proposal("different-step")
    different_arguments = proposal("step-2", value="payments")
    different_version = ProposedToolCall("step-3", "query_logs", V2, first.arguments_json)

    assert tool_query_fingerprint(first) == tool_query_fingerprint(equivalent)
    assert tool_query_fingerprint(first) != tool_query_fingerprint(different_arguments)
    assert tool_query_fingerprint(first) != tool_query_fingerprint(different_version)
    with pytest.raises(InvalidDomainValueError, match="structured proposal"):
        tool_query_fingerprint(object())  # type: ignore[arg-type]


def test_compile_rejects_repeated_queries_within_plan_and_across_replans() -> None:
    registry = ToolRegistry((definition(),))
    repeated = (proposal("step-1"), proposal("step-2"))
    with pytest.raises(InvalidDomainValueError, match="equivalent"):
        compile_investigation_plan(
            plan(0, 0),
            repeated,
            registry=registry,
            budgets=budgets(),
            usage=PlanningUsage(0, 0),
        )

    prior = frozenset({tool_query_fingerprint(repeated[0])})
    with pytest.raises(InvalidDomainValueError, match="equivalent"):
        compile_investigation_plan(
            plan(0),
            (repeated[0],),
            registry=registry,
            budgets=budgets(),
            usage=PlanningUsage(0, 0),
            prior_query_fingerprints=prior,
        )


@pytest.mark.parametrize("history", [set(), frozenset({"invalid"})])
def test_compile_rejects_invalid_query_history(history: object) -> None:
    with pytest.raises(InvalidDomainValueError, match="fingerprints are invalid"):
        compile_investigation_plan(
            plan(0),
            (proposal("step-1"),),
            registry=ToolRegistry((definition(),)),
            budgets=budgets(),
            usage=PlanningUsage(0, 0),
            prior_query_fingerprints=history,  # type: ignore[arg-type]
        )
