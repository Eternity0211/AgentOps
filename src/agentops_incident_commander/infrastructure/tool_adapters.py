"""Read-only Tool Gateway adapters over server-owned observability ports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from agentops_incident_commander.application import ToolAdapterContext
from agentops_incident_commander.domain import (
    Permission,
    RetryableToolError,
    SemanticVersion,
    ToolAccessClass,
    ToolAuditPolicy,
    ToolDefinition,
    ToolIdempotency,
    ToolRetryPolicy,
    ToolRisk,
    ToolSchema,
    as_utc,
)
from agentops_incident_commander.domain.errors import InvalidDomainValueError

from .collectors import MAX_COLLECTOR_RECORDS, MetricSample

QUERY_METRICS_VERSION = SemanticVersion("1.0.0")
MAX_METRIC_QUERY_WINDOW = timedelta(hours=6)


class MetricName(StrEnum):
    HTTP_ERROR_RATE = "http_request_error_rate"
    HTTP_DURATION_P95 = "http_request_duration_p95"
    DB_POOL_WAITERS = "db_pool_waiters"
    PROCESS_RESIDENT_MEMORY = "process_resident_memory_bytes"


@dataclass(frozen=True, slots=True)
class MetricQuery:
    metric: MetricName
    service: str
    environment: str
    start: str
    end: str
    step_seconds: int


@dataclass(frozen=True, slots=True)
class MetricBackendResult:
    samples: tuple[MetricSample, ...]
    complete_window: bool
    records_dropped: int = 0

    def __post_init__(self) -> None:
        if len(self.samples) > MAX_COLLECTOR_RECORDS:
            raise InvalidDomainValueError("metric backend result exceeds the record limit")
        if not isinstance(self.complete_window, bool):
            raise InvalidDomainValueError("metric backend completeness must be boolean")
        if (
            not isinstance(self.records_dropped, int)
            or isinstance(self.records_dropped, bool)
            or self.records_dropped < 0
        ):
            raise InvalidDomainValueError("metric backend dropped count is invalid")


class MetricsBackend(Protocol):
    async def query_range(self, query: MetricQuery) -> MetricBackendResult: ...


def query_metrics_definition() -> ToolDefinition:
    input_schema = ToolSchema.from_mapping(
        QUERY_METRICS_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "end": {"maxLength": 40, "minLength": 20, "type": "string"},
                "environment": {
                    "enum": ["production", "staging"],
                    "type": "string",
                },
                "metric": {"enum": [item.value for item in MetricName], "type": "string"},
                "service": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "[a-z][a-z0-9-]*",
                    "type": "string",
                },
                "start": {"maxLength": 40, "minLength": 20, "type": "string"},
                "step_seconds": {"maximum": 300, "minimum": 1, "type": "integer"},
            },
            "required": [
                "end",
                "environment",
                "metric",
                "service",
                "start",
                "step_seconds",
            ],
            "type": "object",
        },
    )
    output_schema = ToolSchema.from_mapping(
        QUERY_METRICS_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "complete_window": {"type": "boolean"},
                "query": {
                    "additionalProperties": False,
                    "properties": input_schema.as_dict()["properties"],
                    "required": input_schema.as_dict()["required"],
                    "type": "object",
                },
                "records_dropped": {"minimum": 0, "type": "integer"},
                "samples": {
                    "items": {
                        "additionalProperties": False,
                        "properties": {
                            "labels": {
                                "additionalProperties": False,
                                "properties": {
                                    "environment": {"type": "string"},
                                    "service": {"type": "string"},
                                },
                                "required": ["environment", "service"],
                                "type": "object",
                            },
                            "observed_at": {"type": "string"},
                            "value": {"type": "number"},
                        },
                        "required": ["labels", "observed_at", "value"],
                        "type": "object",
                    },
                    "maxItems": MAX_COLLECTOR_RECORDS,
                    "type": "array",
                },
                "schema_version": {"const": "1.0.0", "type": "string"},
                "source": {"const": "prometheus", "type": "string"},
            },
            "required": [
                "complete_window",
                "query",
                "records_dropped",
                "samples",
                "schema_version",
                "source",
            ],
            "type": "object",
        },
    )
    return ToolDefinition(
        name="query_metrics",
        semantic_version=QUERY_METRICS_VERSION,
        input_schema=input_schema,
        output_schema=output_schema,
        access_class=ToolAccessClass.READ,
        risk=ToolRisk.LOW,
        required_permission=Permission.EVIDENCE_READ,
        timeout_ms=10_000,
        retry_policy=ToolRetryPolicy(
            3,
            100,
            1_000,
            frozenset(
                {
                    RetryableToolError.CONNECTION,
                    RetryableToolError.RATE_LIMIT,
                    RetryableToolError.TIMEOUT,
                }
            ),
        ),
        idempotency=ToolIdempotency.NOT_APPLICABLE,
        audit=ToolAuditPolicy("tool.call", QUERY_METRICS_VERSION),
        max_input_bytes=2_048,
        max_result_bytes=4 * 1024 * 1024,
    )


class QueryMetricsAdapter:
    def __init__(self, backend: MetricsBackend) -> None:
        self._backend = backend

    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        del context
        try:
            start = as_utc(datetime.fromisoformat(str(arguments["start"])))
            end = as_utc(datetime.fromisoformat(str(arguments["end"])))
        except (KeyError, ValueError) as exc:
            raise InvalidDomainValueError("metric query timestamps must be ISO-8601 UTC") from exc
        if end <= start or end - start > MAX_METRIC_QUERY_WINDOW:
            raise InvalidDomainValueError("metric query window is invalid or too large")
        query = MetricQuery(
            metric=MetricName(arguments["metric"]),
            service=str(arguments["service"]),
            environment=str(arguments["environment"]),
            start=start.isoformat(),
            end=end.isoformat(),
            step_seconds=int(arguments["step_seconds"]),
        )
        result = await self._backend.query_range(query)
        samples: list[dict[str, Any]] = []
        for sample in result.samples:
            if sample.metric != query.metric.value:
                raise InvalidDomainValueError("metric backend returned a different metric")
            if not start <= sample.observed_at <= end:
                raise InvalidDomainValueError("metric backend returned an out-of-window sample")
            labels = dict(sample.labels)
            if labels != {"environment": query.environment, "service": query.service}:
                raise InvalidDomainValueError("metric backend returned mismatched scope labels")
            samples.append(
                {
                    "labels": labels,
                    "observed_at": sample.observed_at.isoformat(),
                    "value": sample.value,
                }
            )
        return {
            "complete_window": result.complete_window,
            "query": {
                "end": query.end,
                "environment": query.environment,
                "metric": query.metric.value,
                "service": query.service,
                "start": query.start,
                "step_seconds": query.step_seconds,
            },
            "records_dropped": result.records_dropped,
            "samples": samples,
            "schema_version": QUERY_METRICS_VERSION.value,
            "source": "prometheus",
        }
