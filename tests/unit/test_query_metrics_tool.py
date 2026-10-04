"""Versioned query_metrics definition and read-only adapter tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agentops_incident_commander.application import ToolAdapterContext
from agentops_incident_commander.domain import (
    ActorId,
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    Permission,
    ToolAccessClass,
    ToolCallId,
    ToolIdempotency,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.collectors import (
    MAX_COLLECTOR_RECORDS,
    MetricSample,
)
from agentops_incident_commander.infrastructure.tool_adapters import (
    MAX_METRIC_QUERY_WINDOW,
    QUERY_METRICS_VERSION,
    MetricBackendResult,
    MetricName,
    MetricQuery,
    QueryMetricsAdapter,
    query_metrics_definition,
)

NOW = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
CONTEXT = ToolAdapterContext(
    call_id=ToolCallId("call-metrics"),
    incident_id=IncidentId("incident-metrics"),
    workflow_run_id=WorkflowRunId("workflow-metrics"),
    actor_id=ActorId("viewer-metrics"),
    correlation_id=CorrelationId("correlation-metrics"),
    causation_id=CausationId("cause-metrics"),
)


def arguments(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "end": (NOW + timedelta(minutes=5)).isoformat(),
        "environment": "production",
        "metric": MetricName.HTTP_ERROR_RATE.value,
        "service": "orders",
        "start": NOW.isoformat(),
        "step_seconds": 30,
    }
    value.update(overrides)
    return value


def sample(
    *,
    metric: str = MetricName.HTTP_ERROR_RATE.value,
    observed_at: datetime = NOW + timedelta(minutes=1),
    labels: tuple[tuple[str, str], ...] = (
        ("environment", "production"),
        ("service", "orders"),
    ),
) -> MetricSample:
    return MetricSample(metric, observed_at, 0.25, labels)


class Backend:
    def __init__(self, result: MetricBackendResult) -> None:
        self.result = result
        self.queries: list[MetricQuery] = []

    async def query_range(self, query: MetricQuery) -> MetricBackendResult:
        self.queries.append(query)
        return self.result


def test_query_metrics_definition_is_strict_read_only_and_bounded() -> None:
    definition = query_metrics_definition()
    assert definition.name == "query_metrics"
    assert definition.semantic_version == QUERY_METRICS_VERSION
    assert definition.access_class is ToolAccessClass.READ
    assert definition.required_permission is Permission.EVIDENCE_READ
    assert definition.idempotency is ToolIdempotency.NOT_APPLICABLE
    assert definition.retry_policy.max_attempts == 3
    assert definition.input_schema.as_dict()["additionalProperties"] is False
    assert definition.output_schema.as_dict()["properties"]["samples"]["maxItems"] == 1000


def test_metric_backend_result_enforces_bounds_and_types() -> None:
    assert MetricBackendResult((sample(),), True).records_dropped == 0
    with pytest.raises(InvalidDomainValueError, match="record limit"):
        MetricBackendResult((sample(),) * (MAX_COLLECTOR_RECORDS + 1), True)
    with pytest.raises(InvalidDomainValueError, match="completeness"):
        MetricBackendResult((), 1)  # type: ignore[arg-type]
    for dropped in (-1, True, 1.5):
        with pytest.raises(InvalidDomainValueError, match="dropped count"):
            MetricBackendResult((), True, dropped)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_query_metrics_adapter_returns_versioned_scoped_result() -> None:
    backend = Backend(MetricBackendResult((sample(),), True, 2))
    result = await QueryMetricsAdapter(backend).invoke(CONTEXT, arguments())
    assert result == {
        "complete_window": True,
        "query": {
            "end": (NOW + timedelta(minutes=5)).isoformat(),
            "environment": "production",
            "metric": "http_request_error_rate",
            "service": "orders",
            "start": NOW.isoformat(),
            "step_seconds": 30,
        },
        "records_dropped": 2,
        "samples": [
            {
                "labels": {"environment": "production", "service": "orders"},
                "observed_at": (NOW + timedelta(minutes=1)).isoformat(),
                "value": 0.25,
            }
        ],
        "schema_version": "1.0.0",
        "source": "prometheus",
    }
    assert backend.queries[0].metric is MetricName.HTTP_ERROR_RATE


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"start": "invalid"}, "timestamps"),
        ({"end": NOW.isoformat()}, "window"),
        (
            {"end": (NOW + MAX_METRIC_QUERY_WINDOW + timedelta(seconds=1)).isoformat()},
            "window",
        ),
    ],
)
async def test_query_metrics_adapter_rejects_invalid_windows(
    overrides: Mapping[str, Any], message: str
) -> None:
    backend = Backend(MetricBackendResult((), True))
    with pytest.raises(InvalidDomainValueError, match=message):
        await QueryMetricsAdapter(backend).invoke(CONTEXT, arguments(**overrides))
    assert backend.queries == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("backend_sample", "message"),
    [
        (sample(metric=MetricName.DB_POOL_WAITERS.value), "different metric"),
        (sample(observed_at=NOW - timedelta(seconds=1)), "out-of-window"),
        (sample(labels=(("environment", "staging"), ("service", "orders"))), "scope labels"),
        (
            sample(
                labels=(
                    ("environment", "production"),
                    ("region", "east"),
                    ("service", "orders"),
                )
            ),
            "scope labels",
        ),
    ],
)
async def test_query_metrics_adapter_rejects_backend_scope_substitution(
    backend_sample: MetricSample, message: str
) -> None:
    backend = Backend(MetricBackendResult((backend_sample,), True))
    with pytest.raises(InvalidDomainValueError, match=message):
        await QueryMetricsAdapter(backend).invoke(CONTEXT, arguments())
    assert len(backend.queries) == 1
