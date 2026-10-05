"""Versioned query_logs definition and read-only adapter tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.application import ToolAdapterContext
from agentops_incident_commander.application.tool_gateway import (
    ToolPayloadValidationError,
    _validate_payload,
)
from agentops_incident_commander.domain import (
    ActorId,
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    Permission,
    TenantId,
    ToolAccessClass,
    ToolCallId,
    ToolIdempotency,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.tool_adapters import (
    MAX_LOG_QUERY_RECORDS,
    MAX_LOG_QUERY_WINDOW,
    QUERY_LOGS_VERSION,
    LogBackendRecord,
    LogBackendResult,
    LogQuery,
    LogSeverity,
    QueryLogsAdapter,
    query_logs_definition,
)

NOW = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
CONTEXT = ToolAdapterContext(
    call_id=ToolCallId("call-logs"),
    incident_id=IncidentId("incident-logs"),
    workflow_run_id=WorkflowRunId("workflow-logs"),
    actor_id=ActorId("viewer-logs"),
    tenant_id=TenantId("tenant-1"),
    correlation_id=CorrelationId("correlation-logs"),
    causation_id=CausationId("cause-logs"),
)


def arguments(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "contains": "connection refused",
        "end": (NOW + timedelta(minutes=10)).isoformat(),
        "environment": "production",
        "limit": 100,
        "minimum_severity": "WARN",
        "service": "orders",
        "start": NOW.isoformat(),
    }
    value.update(overrides)
    return value


def record(
    *,
    observed_at: datetime = NOW + timedelta(minutes=1),
    severity: LogSeverity = LogSeverity.ERROR,
    labels: tuple[tuple[str, str], ...] = (
        ("environment", "production"),
        ("service", "orders"),
    ),
    message: str = "database connection refused",
    trace_id: str | None = "trace-1",
) -> LogBackendRecord:
    return LogBackendRecord(observed_at, severity, message, labels, trace_id)


class Backend:
    def __init__(self, result: LogBackendResult) -> None:
        self.result = result
        self.queries: list[LogQuery] = []

    async def query_range(self, query: LogQuery) -> LogBackendResult:
        self.queries.append(query)
        return self.result


def test_query_logs_definition_is_strict_read_only_and_bounded() -> None:
    definition = query_logs_definition()
    schema = definition.input_schema.as_dict()
    assert definition.name == "query_logs"
    assert definition.semantic_version == QUERY_LOGS_VERSION
    assert definition.access_class is ToolAccessClass.READ
    assert definition.required_permission is Permission.EVIDENCE_READ
    assert definition.idempotency is ToolIdempotency.NOT_APPLICABLE
    assert definition.retry_policy.max_attempts == 3
    assert schema["additionalProperties"] is False
    assert "query" not in schema["properties"]
    assert "url" not in schema["properties"]
    assert definition.output_schema.as_dict()["properties"]["records"]["maxItems"] == 500


@pytest.mark.parametrize(
    "payload",
    [
        arguments(query='{service=~".*"}'),
        arguments(service="https://loki.example/query"),
        arguments(contains='line one\n{service="payments"}'),
    ],
)
def test_query_logs_schema_rejects_raw_query_target_and_control_injection(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ToolPayloadValidationError):
        _validate_payload(query_logs_definition().input_schema.as_dict(), payload)


def test_log_backend_types_enforce_bounds_and_untrusted_data_limits() -> None:
    assert LogBackendResult((record(),), True).records_dropped == 0
    with pytest.raises(InvalidDomainValueError, match="record limit"):
        LogBackendResult((record(),) * (MAX_LOG_QUERY_RECORDS + 1), True)
    with pytest.raises(InvalidDomainValueError, match="completeness"):
        LogBackendResult((), 1)  # type: ignore[arg-type]
    for dropped in (-1, True, 1.5):
        with pytest.raises(InvalidDomainValueError, match="dropped count"):
            LogBackendResult((), True, dropped)  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="message"):
        record(message="x" * 4_097)
    with pytest.raises(InvalidDomainValueError, match="trace ID"):
        record(trace_id="x" * 129)
    with pytest.raises(InvalidDomainValueError, match="unique"):
        record(labels=(("service", "orders"), ("service", "payments")))
    with pytest.raises(InvalidDomainValueError, match="severity"):
        record(severity=cast(LogSeverity, "ERROR"))
    with pytest.raises(InvalidDomainValueError, match="labels"):
        record(labels=cast(tuple[tuple[str, str], ...], [("service", "orders")]))


@pytest.mark.anyio
async def test_query_logs_adapter_returns_versioned_scoped_result() -> None:
    backend = Backend(LogBackendResult((record(), record(trace_id=None)), True, 2))
    result = await QueryLogsAdapter(backend).invoke(CONTEXT, arguments())
    assert result == {
        "complete_window": True,
        "query": arguments(),
        "records": [
            {
                "labels": {"environment": "production", "service": "orders"},
                "message": "database connection refused",
                "observed_at": (NOW + timedelta(minutes=1)).isoformat(),
                "severity": "ERROR",
                "trace_id": "trace-1",
            },
            {
                "labels": {"environment": "production", "service": "orders"},
                "message": "database connection refused",
                "observed_at": (NOW + timedelta(minutes=1)).isoformat(),
                "severity": "ERROR",
            },
        ],
        "records_dropped": 2,
        "schema_version": "1.0.0",
        "source": "loki",
    }
    assert backend.queries[0].minimum_severity is LogSeverity.WARN


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"start": "invalid"}, "versioned contract"),
        ({"end": NOW.isoformat()}, "window"),
        (
            {"end": (NOW + MAX_LOG_QUERY_WINDOW + timedelta(seconds=1)).isoformat()},
            "window",
        ),
        ({"contains": "bad\nselector"}, "match text"),
        ({"limit": MAX_LOG_QUERY_RECORDS + 1}, "limit"),
    ],
)
async def test_query_logs_adapter_rejects_invalid_queries(
    overrides: Mapping[str, Any], message: str
) -> None:
    backend = Backend(LogBackendResult((), True))
    with pytest.raises(InvalidDomainValueError, match=message):
        await QueryLogsAdapter(backend).invoke(CONTEXT, arguments(**overrides))
    assert backend.queries == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("records", "overrides", "message"),
    [
        ((record(observed_at=NOW - timedelta(seconds=1)),), {}, "out-of-window"),
        (
            (
                record(observed_at=NOW + timedelta(minutes=2)),
                record(observed_at=NOW + timedelta(minutes=1)),
            ),
            {},
            "time ordered",
        ),
        ((record(severity=LogSeverity.INFO),), {}, "severity threshold"),
        (
            (record(labels=(("environment", "staging"), ("service", "orders"))),),
            {},
            "scope labels",
        ),
        (
            (
                record(
                    labels=(
                        ("environment", "production"),
                        ("region", "east"),
                        ("service", "orders"),
                    )
                ),
            ),
            {},
            "scope labels",
        ),
        ((record(), record()), {"limit": 1}, "requested limit"),
    ],
)
async def test_query_logs_adapter_rejects_backend_scope_or_bound_violations(
    records: tuple[LogBackendRecord, ...], overrides: Mapping[str, Any], message: str
) -> None:
    backend = Backend(LogBackendResult(records, True))
    with pytest.raises(InvalidDomainValueError, match=message):
        await QueryLogsAdapter(backend).invoke(CONTEXT, arguments(**overrides))
    assert len(backend.queries) == 1
