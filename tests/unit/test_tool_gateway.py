"""Deterministic Tool Gateway validation, dispatch, retry, limit, and audit tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from itertools import count
from typing import Any, cast

import pytest

from agentops_incident_commander.application.tool_gateway import (
    ToolAdapterContext,
    ToolAdapterFailure,
    ToolCallRequest,
    ToolGateway,
    ToolGatewayError,
    ToolPayloadValidationError,
    ToolResultLimitError,
    ToolSchemaConfigurationError,
    _check_schema,
    _validate_payload,
)
from agentops_incident_commander.domain import (
    ActorId,
    AuditEvent,
    AuthorizationError,
    CausationId,
    CorrelationId,
    IncidentId,
    Permission,
    Principal,
    RetryableToolError,
    Role,
    SemanticVersion,
    TenantId,
    ToolAccessClass,
    ToolAuditPolicy,
    ToolCallId,
    ToolDefinition,
    ToolIdempotency,
    ToolRegistry,
    ToolRetryPolicy,
    ToolRisk,
    ToolSchema,
    ToolVersionDisabledError,
    ToolVersionRange,
    WorkflowRunId,
)

NOW = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
V1 = SemanticVersion("1.0.0")
V2 = SemanticVersion("2.0.0")

INPUT_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "constant": {"const": "fixed", "type": "string"},
        "enabled": {"type": "boolean"},
        "limit": {"maximum": 10, "minimum": 1, "type": "integer"},
        "mode": {"enum": ["errors", "all"], "type": "string"},
        "nested": {
            "additionalProperties": False,
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "type": "object",
        },
        "nothing": {"type": "null"},
        "ratio": {"maximum": 1.0, "minimum": 0.0, "type": "number"},
        "service": {"maxLength": 20, "minLength": 1, "pattern": "[a-z-]+", "type": "string"},
        "tags": {
            "items": {"type": "string"},
            "maxItems": 2,
            "minItems": 1,
            "type": "array",
        },
    },
    "required": ["service"],
    "type": "object",
}
OUTPUT_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {"items": {"items": {"type": "string"}, "maxItems": 3, "type": "array"}},
    "required": ["items"],
    "type": "object",
}


def tool_definition(
    *,
    version: SemanticVersion = V1,
    retry: ToolRetryPolicy | None = None,
    timeout_ms: int = 100,
    max_input_bytes: int = 4096,
    max_result_bytes: int = 4096,
    permission: Permission = Permission.EVIDENCE_READ,
) -> ToolDefinition:
    return ToolDefinition(
        name="query_logs",
        semantic_version=version,
        input_schema=ToolSchema.from_mapping(V1, INPUT_SCHEMA),
        output_schema=ToolSchema.from_mapping(V1, OUTPUT_SCHEMA),
        access_class=ToolAccessClass.READ,
        risk=ToolRisk.LOW,
        required_permission=permission,
        timeout_ms=timeout_ms,
        retry_policy=retry or ToolRetryPolicy(1, 0, 0, frozenset()),
        idempotency=ToolIdempotency.NOT_APPLICABLE,
        audit=ToolAuditPolicy("tool.call", V1),
        max_input_bytes=max_input_bytes,
        max_result_bytes=max_result_bytes,
    )


class FakeAuditWriter:
    def __init__(self, error: Exception | None = None) -> None:
        self.events: list[AuditEvent] = []
        self.error = error

    async def append(self, event: AuditEvent) -> object:
        if self.error is not None:
            raise self.error
        self.events.append(event)
        return None


class SequenceAdapter:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.contexts: list[ToolAdapterContext] = []
        self.arguments: list[dict[str, Any]] = []

    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.contexts.append(context)
        self.arguments.append(dict(arguments))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return cast(Mapping[str, Any], outcome)


class SlowAdapter:
    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        await asyncio.Event().wait()
        return {"items": []}  # pragma: no cover - wait is cancelled by timeout


def request(
    arguments: Mapping[str, Any] | None = None,
    *,
    version: SemanticVersion = V1,
    principal: Principal | None = None,
) -> ToolCallRequest:
    return ToolCallRequest.from_mapping(
        call_id=ToolCallId("call-1"),
        tool_name="query_logs",
        tool_version=version,
        incident_id=IncidentId("incident-1"),
        workflow_run_id=WorkflowRunId("run-1"),
        principal=principal
        or Principal(ActorId("viewer-1"), TenantId("tenant-1"), frozenset({Role.VIEWER})),
        correlation_id=CorrelationId("correlation-1"),
        causation_id=CausationId("cause-1"),
        arguments=arguments or {"service": "orders"},
    )


def gateway(
    definition: ToolDefinition,
    adapter: Any,
    audit: FakeAuditWriter,
    *,
    registry: ToolRegistry | None = None,
    sleeper: Any = asyncio.sleep,
) -> ToolGateway:
    ids = count(1)
    return ToolGateway(
        registry or ToolRegistry((definition,)),
        {definition.identity: adapter},
        audit,
        clock=lambda: NOW,
        audit_id_factory=lambda: f"audit-tool-{next(ids)}",
        sleeper=sleeper,
    )


def test_tool_call_request_is_canonical_detached_and_hashed() -> None:
    arguments = {"service": "orders"}
    call = request(arguments)
    arguments["service"] = "changed"
    assert call.arguments() == {"service": "orders"}
    assert call.request_hash == request().request_hash
    copy = call.arguments()
    copy["service"] = "changed-again"
    assert call.arguments()["service"] == "orders"
    for raw in (cast(str, None), "{", "[]", '{"service": "orders"}'):
        with pytest.raises(ToolPayloadValidationError):
            replace(call, arguments_json=raw)
    with pytest.raises(ToolPayloadValidationError, match="must be JSON"):
        request({"bad": {1}})


@pytest.mark.anyio
async def test_gateway_dispatches_valid_call_and_audits_hashes() -> None:
    definition = tool_definition()
    adapter = SequenceAdapter([{"items": ["one"]}])
    audit = FakeAuditWriter()
    result = await gateway(definition, adapter, audit).invoke(request())
    assert result.result() == {"items": ["one"]}
    assert result.attempts == 1
    assert audit.events[-1].result_hash is not None
    assert result.content_hash.value == audit.events[-1].result_hash.value
    assert [event.type for event in audit.events] == ["tool.call_started", "tool.call_succeeded"]
    assert audit.events[0].request_hash == request().request_hash
    assert audit.events[0].result_hash is None
    assert adapter.contexts[0].incident_id == IncidentId("incident-1")
    assert adapter.arguments == [{"service": "orders"}]


@pytest.mark.anyio
async def test_gateway_audits_unknown_disabled_permission_and_invalid_input() -> None:
    definition = tool_definition()
    adapter = SequenceAdapter([{"items": []}])
    cases: list[tuple[ToolGateway, ToolCallRequest, type[BaseException]]] = []

    unknown_audit = FakeAuditWriter()
    cases.append((gateway(definition, adapter, unknown_audit), request(version=V2), Exception))

    old = tool_definition()
    current = tool_definition(version=V2)
    disabled_registry = ToolRegistry(
        (old, current), enabled_ranges={"query_logs": ToolVersionRange(V2, V2)}
    )
    disabled_audit = FakeAuditWriter()
    cases.append(
        (
            gateway(current, adapter, disabled_audit, registry=disabled_registry),
            request(),
            ToolVersionDisabledError,
        )
    )

    denied_definition = tool_definition(permission=Permission.APPROVED_ACTION_EXECUTE)
    denied_audit = FakeAuditWriter()
    cases.append(
        (
            gateway(denied_definition, adapter, denied_audit),
            request(),
            AuthorizationError,
        )
    )

    invalid_audit = FakeAuditWriter()
    cases.append(
        (
            gateway(definition, adapter, invalid_audit),
            request({"service": "INVALID!"}),
            ToolPayloadValidationError,
        )
    )
    oversized_audit = FakeAuditWriter()
    small = replace(definition, max_input_bytes=2)
    cases.append(
        (
            gateway(small, adapter, oversized_audit),
            request(),
            ToolPayloadValidationError,
        )
    )

    for item, call, error_type in cases:
        with pytest.raises(error_type):
            await item.invoke(call)
        writer = cast(FakeAuditWriter, item._audit_writer)
        assert [event.type for event in writer.events] == ["tool.call_rejected"]
        assert writer.events[0].result_hash is not None
    assert adapter.contexts == []


@pytest.mark.anyio
async def test_gateway_retries_only_classified_allowed_failures_with_bounded_backoff() -> None:
    retry = ToolRetryPolicy(
        3,
        10,
        15,
        frozenset({RetryableToolError.CONNECTION, RetryableToolError.TIMEOUT}),
    )
    definition = tool_definition(retry=retry)
    adapter = SequenceAdapter(
        [
            ToolAdapterFailure(RetryableToolError.CONNECTION, "secret dependency detail"),
            ToolAdapterFailure(RetryableToolError.CONNECTION, "again"),
            {"items": []},
        ]
    )
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    audit = FakeAuditWriter()
    result = await gateway(definition, adapter, audit, sleeper=sleep).invoke(request())
    assert result.attempts == 3
    assert delays == [0.01, 0.015]
    assert [event.type for event in audit.events] == ["tool.call_started", "tool.call_succeeded"]


@pytest.mark.anyio
async def test_gateway_times_out_exhausts_and_does_not_retry_unclassified_failures() -> None:
    retry = ToolRetryPolicy(2, 0, 0, frozenset({RetryableToolError.TIMEOUT}))
    audit = FakeAuditWriter()
    with pytest.raises(ToolGatewayError) as timed_out:
        await gateway(tool_definition(retry=retry, timeout_ms=1), SlowAdapter(), audit).invoke(
            request()
        )
    assert timed_out.value.code == "TOOL_TIMEOUT"
    assert timed_out.value.attempts == 2
    assert [event.type for event in audit.events] == ["tool.call_started", "tool.call_failed"]

    for failure, expected_code in (
        (ToolAdapterFailure(RetryableToolError.RATE_LIMIT, "no retry"), "ADAPTER_RATE_LIMIT"),
        (RuntimeError("sensitive"), "TOOL_ADAPTER_FAILED"),
    ):
        local_audit = FakeAuditWriter()
        adapter = SequenceAdapter([failure])
        with pytest.raises(ToolGatewayError) as raised:
            await gateway(tool_definition(retry=retry), adapter, local_audit).invoke(request())
        assert raised.value.code == expected_code
        assert raised.value.attempts == 1
        assert len(adapter.contexts) == 1
        assert local_audit.events[-1].type == "tool.call_failed"


@pytest.mark.anyio
async def test_gateway_rejects_invalid_or_oversized_results_without_retry() -> None:
    cases: list[tuple[object, ToolDefinition, type[ToolGatewayError], str]] = [
        ({"wrong": []}, tool_definition(), ToolPayloadValidationError, "SCHEMA_VALIDATION_FAILED"),
        (["not-object"], tool_definition(), ToolPayloadValidationError, "OUTPUT_NOT_OBJECT"),
        ({"items": {1}}, tool_definition(), ToolPayloadValidationError, "PAYLOAD_NOT_JSON"),
        (
            {"items": ["long"]},
            tool_definition(max_result_bytes=5),
            ToolResultLimitError,
            "RESULT_LIMIT_EXCEEDED",
        ),
    ]
    for outcome, definition, error_type, code in cases:
        audit = FakeAuditWriter()
        with pytest.raises(error_type) as raised:
            await gateway(definition, SequenceAdapter([outcome]), audit).invoke(request())
        assert raised.value.code == code
        assert raised.value.attempts == 1
        assert audit.events[-1].type == "tool.call_failed"


@pytest.mark.anyio
async def test_gateway_audits_cancellation_and_fails_closed_when_audit_is_unavailable() -> None:
    definition = tool_definition()
    cancelled_audit = FakeAuditWriter()
    with pytest.raises(asyncio.CancelledError):
        await gateway(
            definition, SequenceAdapter([asyncio.CancelledError()]), cancelled_audit
        ).invoke(request())
    assert cancelled_audit.events[-1].type == "tool.call_failed"

    audit_error = RuntimeError("audit unavailable")
    adapter = SequenceAdapter([{"items": []}])
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await gateway(definition, adapter, FakeAuditWriter(audit_error)).invoke(request())
    assert adapter.contexts == []


def test_gateway_requires_exact_adapter_registration() -> None:
    definition = tool_definition()
    audit = FakeAuditWriter()
    with pytest.raises(ToolSchemaConfigurationError, match="match exactly"):
        ToolGateway(
            ToolRegistry((definition,)),
            {},
            audit,
            audit_id_factory=lambda: "audit-1",
        )


@pytest.mark.parametrize(
    "schema",
    [
        "not-object",
        {"type": "string", "unknown": True},
        {"type": "unsupported"},
        {"enum": [], "type": "string"},
        {"enum": "bad", "type": "string"},
        {"type": "object"},
        {"additionalProperties": True, "properties": {}, "type": "object"},
        {
            "additionalProperties": False,
            "properties": {},
            "required": ["missing"],
            "type": "object",
        },
        {
            "additionalProperties": False,
            "properties": {1: {"type": "string"}},
            "type": "object",
        },
        {"type": "array"},
        {"items": {"type": "string"}, "minItems": True, "type": "array"},
        {"items": {"type": "string"}, "minItems": -1, "type": "array"},
        {"items": {"type": "string"}, "maxItems": True, "type": "array"},
        {"items": {"type": "string"}, "minItems": 2, "maxItems": 1, "type": "array"},
        {"minLength": True, "type": "string"},
        {"maxLength": True, "type": "string"},
        {"minLength": 2, "maxLength": 1, "type": "string"},
        {"pattern": 1, "type": "string"},
        {"pattern": "[", "type": "string"},
        {"minimum": True, "type": "integer"},
        {"maximum": float("inf"), "type": "number"},
        {"minimum": 2, "maximum": 1, "type": "number"},
    ],
)
def test_schema_configuration_rejects_unsupported_or_invalid_constraints(schema: object) -> None:
    with pytest.raises(ToolSchemaConfigurationError):
        _check_schema(schema)


def test_schema_configuration_accepts_supported_shapes_and_bounds_depth() -> None:
    _check_schema(INPUT_SCHEMA)
    for kind, value in (
        ("boolean", True),
        ("null", None),
        ("integer", 1),
        ("number", 0.5),
        ("string", "ok"),
        ("array", []),
        ("object", {}),
    ):
        schema: dict[str, Any] = {"type": kind}
        if kind == "array":
            schema["items"] = {"type": "string"}
        if kind == "object":
            schema.update({"additionalProperties": False, "properties": {}})
        _check_schema(schema)
        _validate_payload(schema, value)

    nested: dict[str, Any] = {"type": "string"}
    for _ in range(18):
        nested = {
            "additionalProperties": False,
            "properties": {"child": nested},
            "type": "object",
        }
    with pytest.raises(ToolSchemaConfigurationError, match="depth"):
        _check_schema(nested)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({}, "missing required"),
        ({"service": "orders", "extra": 1}, "unknown fields"),
        ({"service": 1}, "invalid type"),
        ({"service": ""}, "invalid length"),
        ({"service": "INVALID!"}, "invalid format"),
        ({"service": "orders", "mode": "bad"}, "not allowed"),
        ({"service": "orders", "constant": "bad"}, "not constant"),
        ({"service": "orders", "limit": 0}, "outside"),
        ({"service": "orders", "ratio": float("inf")}, "invalid type"),
        ({"service": "orders", "tags": []}, "item count"),
        ({"service": "orders", "tags": ["a", "b", "c"]}, "item count"),
        ({"service": "orders", "tags": [1]}, "invalid type"),
        ({"service": "orders", "nested": {}}, "missing required"),
        ({"service": "orders", "enabled": 1}, "invalid type"),
        ({"service": "orders", "nothing": False}, "invalid type"),
    ],
)
def test_payload_validation_rejects_each_supported_constraint(value: object, message: str) -> None:
    with pytest.raises(ToolPayloadValidationError, match=message):
        _validate_payload(INPUT_SCHEMA, value)


def test_payload_validation_accepts_complete_supported_payload() -> None:
    _validate_payload(
        INPUT_SCHEMA,
        {
            "constant": "fixed",
            "enabled": True,
            "limit": 10,
            "mode": "errors",
            "nested": {"name": "child"},
            "nothing": None,
            "ratio": 0.5,
            "service": "orders",
            "tags": ["api"],
        },
    )
