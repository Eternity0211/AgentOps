"""Versioned ToolDefinition and fail-closed registry contract tests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest

from agentops_incident_commander.domain import (
    MAX_TOOL_ATTEMPTS,
    MAX_TOOL_RESULT_BYTES,
    MAX_TOOL_SCHEMA_BYTES,
    MAX_TOOL_TIMEOUT_MS,
    InvalidDomainValueError,
    Permission,
    RetryableToolError,
    SemanticVersion,
    ToolAccessClass,
    ToolAuditMode,
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

V1 = SemanticVersion("1.0.0")
STRICT_OBJECT = {
    "additionalProperties": False,
    "properties": {"incident_id": {"type": "string"}},
    "required": ["incident_id"],
    "type": "object",
}


def schema(version: SemanticVersion = V1) -> ToolSchema:
    return ToolSchema.from_mapping(version, STRICT_OBJECT)


def no_retry() -> ToolRetryPolicy:
    return ToolRetryPolicy(1, 0, 0, frozenset())


def definition(
    name: str = "query_logs",
    version: SemanticVersion = V1,
    *,
    access_class: ToolAccessClass = ToolAccessClass.READ,
) -> ToolDefinition:
    write = access_class is ToolAccessClass.WRITE
    return ToolDefinition(
        name=name,
        semantic_version=version,
        input_schema=schema(),
        output_schema=schema(),
        access_class=access_class,
        risk=ToolRisk.HIGH if write else ToolRisk.LOW,
        required_permission=(
            Permission.APPROVED_ACTION_EXECUTE if write else Permission.EVIDENCE_READ
        ),
        timeout_ms=10_000,
        retry_policy=no_retry(),
        idempotency=(
            ToolIdempotency.REQUIRED_RESULT_REPLAY if write else ToolIdempotency.NOT_APPLICABLE
        ),
        audit=ToolAuditPolicy("tool.call_completed", V1),
        max_result_bytes=4096,
    )


def test_semantic_versions_are_strict_and_numerically_ordered() -> None:
    assert SemanticVersion("1.10.0") > SemanticVersion("1.2.9")
    assert str(V1) == "1.0.0"
    assert V1.parts == (1, 0, 0)
    assert not (V1 < V1)
    with pytest.raises(TypeError):
        _ = cast(Any, "1.0.0") > V1
    for value in ("1", "1.0", "01.0.0", "1.0.0-beta", "v1.0.0", 1):
        with pytest.raises(InvalidDomainValueError, match=r"MAJOR\.MINOR\.PATCH"):
            SemanticVersion(cast(str, value))


def test_tool_schema_is_canonical_strict_bounded_and_copy_safe() -> None:
    value = schema()
    assert value.as_dict() == STRICT_OBJECT
    assert len(value.content_hash) == 64
    mutable = value.as_dict()
    mutable["type"] = "array"
    assert value.as_dict()["type"] == "object"

    invalid_documents: list[tuple[Any, str]] = [
        (cast(str, 1), "canonical JSON text"),
        ("{", "valid JSON"),
        (
            '{"additionalProperties":false,"properties":{"x":{"const":NaN}},"type":"object"}',
            "JSON values",
        ),
        ("[]", "root must be an object"),
        ('{"type": "object"}', "must be canonical"),
        ('{"additionalProperties":false,"properties":{},"type":"array"}', "strict object"),
        ('{"additionalProperties":true,"properties":{},"type":"object"}', "strict object"),
        ('{"additionalProperties":false,"type":"object"}', "declare object properties"),
        (
            '{"additionalProperties":false,"properties":[],"type":"object"}',
            "declare object properties",
        ),
        (
            '{"additionalProperties":false,"properties":{},"required":"id","type":"object"}',
            "required fields",
        ),
        (
            '{"additionalProperties":false,"properties":{},"required":[1],"type":"object"}',
            "required fields",
        ),
        (
            '{"additionalProperties":false,"properties":{},"required":["id"],"type":"object"}',
            "required fields",
        ),
    ]
    for document, message in invalid_documents:
        with pytest.raises(InvalidDomainValueError, match=message):
            ToolSchema(V1, document)
    with pytest.raises(InvalidDomainValueError, match="byte limit"):
        ToolSchema(V1, " " * (MAX_TOOL_SCHEMA_BYTES + 1))
    with pytest.raises(InvalidDomainValueError, match="version must be semantic"):
        ToolSchema(cast(Any, "1.0.0"), schema().canonical_json)
    for unsupported in ({"value": {1}}, {"value": float("nan")}):
        with pytest.raises(InvalidDomainValueError, match="JSON values"):
            ToolSchema.from_mapping(V1, unsupported)


def test_retry_policy_is_finite_typed_and_classified() -> None:
    policy = ToolRetryPolicy(
        3,
        100,
        1000,
        frozenset({RetryableToolError.TIMEOUT, RetryableToolError.CONNECTION}),
    )
    assert policy.max_attempts == 3
    for values in (
        (True, 0, 0),
        (1, True, 0),
        (1, 0, True),
    ):
        with pytest.raises(InvalidDomainValueError, match="must be an integer"):
            ToolRetryPolicy(
                values[0],
                values[1],
                values[2],
                frozenset(),
            )
    for attempts in (0, MAX_TOOL_ATTEMPTS + 1):
        with pytest.raises(InvalidDomainValueError, match="bounded range"):
            ToolRetryPolicy(attempts, 0, 0, frozenset())
    for initial, maximum in ((-1, 0), (2, 1)):
        with pytest.raises(InvalidDomainValueError, match="backoff range"):
            ToolRetryPolicy(2, initial, maximum, frozenset({RetryableToolError.TIMEOUT}))
    for initial, maximum, errors in (
        (1, 1, frozenset()),
        (0, 1, frozenset()),
        (0, 0, frozenset({RetryableToolError.TIMEOUT})),
    ):
        with pytest.raises(InvalidDomainValueError, match="single-attempt"):
            ToolRetryPolicy(1, initial, maximum, errors)
    with pytest.raises(InvalidDomainValueError, match="classify"):
        ToolRetryPolicy(2, 0, 0, frozenset())
    for invalid_errors in (
        {RetryableToolError.TIMEOUT},
        frozenset({cast(RetryableToolError, "TIMEOUT")}),
    ):
        with pytest.raises(InvalidDomainValueError, match="error classes"):
            ToolRetryPolicy(2, 0, 0, cast(Any, invalid_errors))
    with pytest.raises(InvalidDomainValueError, match="backoff range"):
        ToolRetryPolicy(
            2,
            0,
            MAX_TOOL_TIMEOUT_MS + 1,
            frozenset({RetryableToolError.TIMEOUT}),
        )


def test_audit_and_tool_definition_enforce_safe_metadata() -> None:
    assert ToolAuditPolicy("tool.call_completed", V1).schema_version == V1
    for event_type in ("tool", "Tool.called", cast(str, 1)):
        with pytest.raises(InvalidDomainValueError, match="audit event"):
            ToolAuditPolicy(event_type, V1)
    with pytest.raises(InvalidDomainValueError, match="schema version"):
        ToolAuditPolicy("tool.call", cast(Any, "1.0.0"))
    with pytest.raises(InvalidDomainValueError, match="request and result hashes"):
        ToolAuditPolicy("tool.call", V1, cast(ToolAuditMode, "UNSAFE"))

    read = definition()
    write = definition("rollback_service", access_class=ToolAccessClass.WRITE)
    assert read.identity == ("query_logs", V1)
    assert write.idempotency is ToolIdempotency.REQUIRED_RESULT_REPLAY
    for name in ("QueryLogs", "query-logs", "_query", cast(str, 1)):
        with pytest.raises(InvalidDomainValueError, match="lower snake case"):
            replace(read, name=name)
    for field, value in (
        ("timeout_ms", True),
        ("max_result_bytes", True),
        ("timeout_ms", 0),
        ("timeout_ms", MAX_TOOL_TIMEOUT_MS + 1),
        ("max_result_bytes", 0),
        ("max_result_bytes", MAX_TOOL_RESULT_BYTES + 1),
    ):
        with pytest.raises(InvalidDomainValueError, match=r"tool (timeout|result byte limit)"):
            replace(read, **cast(Any, {field: value}))
    with pytest.raises(InvalidDomainValueError, match="read tools"):
        replace(read, idempotency=ToolIdempotency.REQUIRED_RESULT_REPLAY)
    with pytest.raises(InvalidDomainValueError, match="write tools"):
        replace(write, idempotency=ToolIdempotency.NOT_APPLICABLE)
    with pytest.raises(InvalidDomainValueError, match="typed metadata"):
        replace(read, risk=cast(Any, "LOW"))
    retrying = ToolRetryPolicy(2, 100, 100, frozenset({RetryableToolError.DEPENDENCY_UNAVAILABLE}))
    with pytest.raises(InvalidDomainValueError, match="exceed its timeout"):
        replace(read, timeout_ms=50, retry_policy=retrying)


def test_version_ranges_and_registry_resolve_only_enabled_exact_contracts() -> None:
    v110 = SemanticVersion("1.1.0")
    v200 = SemanticVersion("2.0.0")
    enabled = ToolVersionRange(V1, v110)
    assert enabled.includes(V1)
    assert enabled.includes(v110)
    assert not enabled.includes(v200)
    with pytest.raises(InvalidDomainValueError, match="reversed"):
        ToolVersionRange(v200, V1)
    with pytest.raises(InvalidDomainValueError, match="bounds must be semantic"):
        ToolVersionRange(cast(Any, "1.0.0"), V1)

    old = definition(version=V1)
    current = definition(version=v110)
    metrics = definition("query_metrics", version=v200)
    registry = ToolRegistry((metrics, current, old))
    assert registry.resolve("query_logs", V1) is old
    assert [item.name for item in registry.catalog()] == [
        "query_logs",
        "query_logs",
        "query_metrics",
    ]
    assert registry.catalog(access_class=ToolAccessClass.WRITE) == ()
    with pytest.raises(ToolNotFoundError, match="not registered"):
        registry.resolve("query_logs", SemanticVersion("9.0.0"))

    restricted = ToolRegistry(
        (old, current, metrics), enabled_ranges={"query_logs": ToolVersionRange(v110, v110)}
    )
    assert restricted.resolve("query_logs", v110) is current
    with pytest.raises(ToolVersionDisabledError, match="disabled"):
        restricted.resolve("query_logs", V1)
    with pytest.raises(ToolVersionDisabledError, match="disabled"):
        restricted.resolve("query_metrics", v200)
    assert restricted.catalog() == (current,)


def test_registry_rejects_empty_duplicate_and_mistyped_enablement() -> None:
    value = definition()
    with pytest.raises(InvalidDomainValueError, match="at least one"):
        ToolRegistry(())
    with pytest.raises(InvalidDomainValueError, match="at least one"):
        ToolRegistry(cast(Any, [value]))
    with pytest.raises(InvalidDomainValueError, match="entries must be definitions"):
        ToolRegistry((cast(Any, "query_logs"),))
    with pytest.raises(InvalidDomainValueError, match="duplicate"):
        ToolRegistry((value, value))
    with pytest.raises(InvalidDomainValueError, match="registered tools"):
        ToolRegistry((value,), enabled_ranges={"query_typo": ToolVersionRange(V1, V1)})
    with pytest.raises(InvalidDomainValueError, match="include a registered"):
        ToolRegistry(
            (value,),
            enabled_ranges={
                "query_logs": ToolVersionRange(SemanticVersion("2.0.0"), SemanticVersion("3.0.0"))
            },
        )
    with pytest.raises(InvalidDomainValueError, match="ranges are invalid"):
        ToolRegistry((value,), enabled_ranges={"query_logs": cast(Any, V1)})
