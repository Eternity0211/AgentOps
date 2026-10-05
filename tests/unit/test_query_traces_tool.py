"""Versioned query_traces definition and read-only adapter tests."""

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
    MAX_TRACE_QUERY_SPANS,
    MAX_TRACE_QUERY_TRACES,
    MAX_TRACE_QUERY_WINDOW,
    QUERY_TRACES_VERSION,
    QueryTracesAdapter,
    TraceBackendResult,
    TraceBackendSpan,
    TraceQuery,
    TraceStatus,
    TraceStatusFilter,
    query_traces_definition,
)

NOW = datetime(2026, 10, 4, 10, 0, tzinfo=UTC)
CONTEXT = ToolAdapterContext(
    ToolCallId("call-traces"),
    IncidentId("incident-traces"),
    WorkflowRunId("workflow-traces"),
    ActorId("viewer-traces"),
    TenantId("tenant-1"),
    CorrelationId("correlation-traces"),
    CausationId("cause-traces"),
)


def arguments(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "end": (NOW + timedelta(minutes=10)).isoformat(),
        "environment": "production",
        "max_traces": 20,
        "service": "orders",
        "start": NOW.isoformat(),
        "status": "ERROR",
    }
    value.update(overrides)
    return value


def span(
    *,
    trace_id: str = "trace-1",
    span_id: str = "span-1",
    parent_span_id: str | None = None,
    service: str = "orders",
    environment: str = "production",
    operation: str = "POST /orders",
    started_at: datetime = NOW + timedelta(minutes=1),
    ended_at: datetime = NOW + timedelta(minutes=4),
    status: TraceStatus = TraceStatus.ERROR,
) -> TraceBackendSpan:
    return TraceBackendSpan(
        trace_id,
        span_id,
        parent_span_id,
        service,
        environment,
        operation,
        started_at,
        ended_at,
        status,
    )


class Backend:
    def __init__(self, result: TraceBackendResult) -> None:
        self.result = result
        self.queries: list[TraceQuery] = []

    async def query_range(self, query: TraceQuery) -> TraceBackendResult:
        self.queries.append(query)
        return self.result


def test_query_traces_definition_is_strict_read_only_and_bounded() -> None:
    definition = query_traces_definition()
    schema = definition.input_schema.as_dict()
    assert definition.name == "query_traces"
    assert definition.semantic_version == QUERY_TRACES_VERSION
    assert definition.access_class is ToolAccessClass.READ
    assert definition.required_permission is Permission.EVIDENCE_READ
    assert definition.idempotency is ToolIdempotency.NOT_APPLICABLE
    assert definition.retry_policy.max_attempts == 3
    assert schema["additionalProperties"] is False
    assert not {"query", "url", "path", "attributes"} & set(schema["properties"])
    assert definition.output_schema.as_dict()["properties"]["spans"]["maxItems"] == 1_000


@pytest.mark.parametrize(
    "payload",
    [
        arguments(query="{ span.http.status_code >= 500 }"),
        arguments(service="https://tempo.example/api/search"),
        arguments(attributes="resource.service.name=payments"),
    ],
)
def test_query_traces_schema_rejects_raw_queries_and_targets(payload: dict[str, Any]) -> None:
    with pytest.raises(ToolPayloadValidationError):
        _validate_payload(query_traces_definition().input_schema.as_dict(), payload)


def test_trace_backend_types_enforce_bounds() -> None:
    assert TraceBackendResult((span(),), True).records_dropped == 0
    with pytest.raises(InvalidDomainValueError, match="span limit"):
        TraceBackendResult((span(),) * (MAX_TRACE_QUERY_SPANS + 1), True)
    with pytest.raises(InvalidDomainValueError, match="completeness"):
        TraceBackendResult((), 1)  # type: ignore[arg-type]
    for dropped in (-1, True, 1.5):
        with pytest.raises(InvalidDomainValueError, match="dropped count"):
            TraceBackendResult((), True, dropped)  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="trace_id"):
        span(trace_id="")
    with pytest.raises(InvalidDomainValueError, match="parent span"):
        span(parent_span_id="x" * 129)
    with pytest.raises(InvalidDomainValueError, match="reversed"):
        span(started_at=NOW + timedelta(minutes=2), ended_at=NOW + timedelta(minutes=1))
    with pytest.raises(InvalidDomainValueError, match="status"):
        span(status=cast(TraceStatus, "ERROR"))


@pytest.mark.anyio
async def test_query_traces_adapter_returns_versioned_scoped_result() -> None:
    child = span(
        span_id="span-2",
        parent_span_id="span-1",
        service="payments",
        operation="charge",
        started_at=NOW + timedelta(minutes=2),
        ended_at=NOW + timedelta(minutes=3),
        status=TraceStatus.OK,
    )
    backend = Backend(TraceBackendResult((span(), child), True, 2))
    result = await QueryTracesAdapter(backend).invoke(CONTEXT, arguments())
    assert result["query"] == arguments()
    assert result["trace_count"] == 1
    assert result["source"] == "tempo"
    assert result["schema_version"] == "1.0.0"
    assert result["records_dropped"] == 2
    assert result["complete_window"] is True
    assert result["spans"][0]["trace_id"] == "trace-1"
    assert result["spans"][1]["parent_span_id"] == "span-1"
    assert backend.queries[0].status is TraceStatusFilter.ERROR


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"start": "invalid"}, "versioned contract"),
        ({"status": "FAILED"}, "versioned contract"),
        ({"end": NOW.isoformat()}, "window"),
        ({"end": (NOW + MAX_TRACE_QUERY_WINDOW + timedelta(seconds=1)).isoformat()}, "window"),
        ({"max_traces": 0}, "count"),
        ({"max_traces": MAX_TRACE_QUERY_TRACES + 1}, "count"),
    ],
)
async def test_query_traces_adapter_rejects_invalid_queries(
    overrides: Mapping[str, Any], message: str
) -> None:
    backend = Backend(TraceBackendResult((), True))
    with pytest.raises(InvalidDomainValueError, match=message):
        await QueryTracesAdapter(backend).invoke(CONTEXT, arguments(**overrides))
    assert backend.queries == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("spans", "overrides", "message"),
    [
        ((span(started_at=NOW - timedelta(seconds=1)),), {}, "out-of-window"),
        ((span(environment="staging"),), {}, "mismatched environment"),
        ((span(), span()), {}, "duplicate span"),
        (
            (span(trace_id="trace-2"), span(trace_id="trace-1", span_id="span-2")),
            {},
            "ordered",
        ),
        (
            (span(trace_id="trace-1"), span(trace_id="trace-2", span_id="span-2")),
            {"max_traces": 1},
            "trace count",
        ),
        ((), {}, ""),
        ((span(service="payments"),), {}, "service scope"),
        ((span(status=TraceStatus.OK),), {}, "status filter"),
        (
            (
                span(),
                span(span_id="span-2", started_at=NOW + timedelta(minutes=2)),
            ),
            {},
            "one root",
        ),
        (
            (span(parent_span_id="missing"),),
            {},
            "one root",
        ),
        (
            (
                span(),
                span(
                    span_id="span-2",
                    parent_span_id="missing",
                    started_at=NOW + timedelta(minutes=2),
                ),
            ),
            {},
            "parent span",
        ),
        (
            (
                span(),
                span(
                    span_id="span-2",
                    parent_span_id="span-1",
                    started_at=NOW + timedelta(minutes=2),
                    ended_at=NOW + timedelta(minutes=5),
                ),
            ),
            {},
            "outside its parent",
        ),
    ],
)
async def test_query_traces_adapter_rejects_backend_contract_violations(
    spans: tuple[TraceBackendSpan, ...], overrides: Mapping[str, Any], message: str
) -> None:
    backend = Backend(TraceBackendResult(spans, True))
    if message:
        with pytest.raises(InvalidDomainValueError, match=message):
            await QueryTracesAdapter(backend).invoke(CONTEXT, arguments(**overrides))
    else:
        result = await QueryTracesAdapter(backend).invoke(CONTEXT, arguments(**overrides))
        assert result["trace_count"] == 0
    assert len(backend.queries) == 1
