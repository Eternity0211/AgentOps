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
QUERY_LOGS_VERSION = SemanticVersion("1.0.0")
MAX_LOG_QUERY_WINDOW = timedelta(hours=1)
MAX_LOG_QUERY_RECORDS = 500
QUERY_TRACES_VERSION = SemanticVersion("1.0.0")
MAX_TRACE_QUERY_WINDOW = timedelta(hours=1)
MAX_TRACE_QUERY_TRACES = 100
MAX_TRACE_QUERY_SPANS = 1_000


class MetricName(StrEnum):
    HTTP_ERROR_RATE = "http_request_error_rate"
    HTTP_DURATION_P95 = "http_request_duration_p95"
    DB_POOL_WAITERS = "db_pool_waiters"
    PROCESS_RESIDENT_MEMORY = "process_resident_memory_bytes"


class LogSeverity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TraceStatus(StrEnum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


class TraceStatusFilter(StrEnum):
    ANY = "ANY"
    OK = "OK"
    ERROR = "ERROR"


_LOG_SEVERITY_ORDER = {severity: index for index, severity in enumerate(LogSeverity)}


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


@dataclass(frozen=True, slots=True)
class LogQuery:
    service: str
    environment: str
    start: str
    end: str
    minimum_severity: LogSeverity
    contains: str
    limit: int


@dataclass(frozen=True, slots=True)
class LogBackendRecord:
    observed_at: datetime
    severity: LogSeverity
    message: str
    labels: tuple[tuple[str, str], ...]
    trace_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))
        if not isinstance(self.severity, LogSeverity):
            raise InvalidDomainValueError("log backend severity is invalid")
        if (
            not isinstance(self.message, str)
            or not self.message.strip()
            or len(self.message) > 4_096
            or "\x00" in self.message
        ):
            raise InvalidDomainValueError("log backend message must be bounded non-null text")
        if self.trace_id is not None and (
            not isinstance(self.trace_id, str)
            or not self.trace_id.strip()
            or len(self.trace_id) > 128
            or "\x00" in self.trace_id
        ):
            raise InvalidDomainValueError("log backend trace ID must be bounded non-null text")
        if not isinstance(self.labels, tuple) or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or any(not isinstance(value, str) or not value for value in item)
            for item in self.labels
        ):
            raise InvalidDomainValueError("log backend labels are invalid")
        normalized = tuple(sorted(self.labels))
        if len({key for key, _ in normalized}) != len(normalized):
            raise InvalidDomainValueError("log backend labels must be unique")
        object.__setattr__(self, "labels", normalized)


@dataclass(frozen=True, slots=True)
class LogBackendResult:
    records: tuple[LogBackendRecord, ...]
    complete_window: bool
    records_dropped: int = 0

    def __post_init__(self) -> None:
        if len(self.records) > MAX_LOG_QUERY_RECORDS:
            raise InvalidDomainValueError("log backend result exceeds the record limit")
        if not isinstance(self.complete_window, bool):
            raise InvalidDomainValueError("log backend completeness must be boolean")
        if (
            not isinstance(self.records_dropped, int)
            or isinstance(self.records_dropped, bool)
            or self.records_dropped < 0
        ):
            raise InvalidDomainValueError("log backend dropped count is invalid")


class LogsBackend(Protocol):
    async def query_range(self, query: LogQuery) -> LogBackendResult: ...


@dataclass(frozen=True, slots=True)
class TraceQuery:
    service: str
    environment: str
    start: str
    end: str
    status: TraceStatusFilter
    max_traces: int


@dataclass(frozen=True, slots=True)
class TraceBackendSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    environment: str
    operation: str
    started_at: datetime
    ended_at: datetime
    status: TraceStatus

    def __post_init__(self) -> None:
        for field, maximum in (
            ("trace_id", 128),
            ("span_id", 128),
            ("service", 128),
            ("environment", 32),
            ("operation", 256),
        ):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > maximum
                or "\x00" in value
            ):
                raise InvalidDomainValueError(f"trace backend {field} is invalid")
        if self.parent_span_id is not None and (
            not isinstance(self.parent_span_id, str)
            or not self.parent_span_id.strip()
            or len(self.parent_span_id) > 128
            or "\x00" in self.parent_span_id
        ):
            raise InvalidDomainValueError("trace backend parent span ID is invalid")
        started_at = as_utc(self.started_at)
        ended_at = as_utc(self.ended_at)
        if ended_at < started_at:
            raise InvalidDomainValueError("trace backend span time range is reversed")
        if not isinstance(self.status, TraceStatus):
            raise InvalidDomainValueError("trace backend status is invalid")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "ended_at", ended_at)


@dataclass(frozen=True, slots=True)
class TraceBackendResult:
    spans: tuple[TraceBackendSpan, ...]
    complete_window: bool
    records_dropped: int = 0

    def __post_init__(self) -> None:
        if len(self.spans) > MAX_TRACE_QUERY_SPANS:
            raise InvalidDomainValueError("trace backend result exceeds the span limit")
        if not isinstance(self.complete_window, bool):
            raise InvalidDomainValueError("trace backend completeness must be boolean")
        if (
            not isinstance(self.records_dropped, int)
            or isinstance(self.records_dropped, bool)
            or self.records_dropped < 0
        ):
            raise InvalidDomainValueError("trace backend dropped count is invalid")


class TracesBackend(Protocol):
    async def query_range(self, query: TraceQuery) -> TraceBackendResult: ...


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


def query_logs_definition() -> ToolDefinition:
    input_schema = ToolSchema.from_mapping(
        QUERY_LOGS_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "contains": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": r"[^\x00-\x1f\x7f]+",
                    "type": "string",
                },
                "end": {"maxLength": 40, "minLength": 20, "type": "string"},
                "environment": {
                    "enum": ["production", "staging"],
                    "type": "string",
                },
                "limit": {
                    "maximum": MAX_LOG_QUERY_RECORDS,
                    "minimum": 1,
                    "type": "integer",
                },
                "minimum_severity": {
                    "enum": [item.value for item in LogSeverity],
                    "type": "string",
                },
                "service": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "[a-z][a-z0-9-]*",
                    "type": "string",
                },
                "start": {"maxLength": 40, "minLength": 20, "type": "string"},
            },
            "required": [
                "contains",
                "end",
                "environment",
                "limit",
                "minimum_severity",
                "service",
                "start",
            ],
            "type": "object",
        },
    )
    output_schema = ToolSchema.from_mapping(
        QUERY_LOGS_VERSION,
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
                "records": {
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
                            "message": {"maxLength": 4_096, "minLength": 1, "type": "string"},
                            "observed_at": {"type": "string"},
                            "severity": {
                                "enum": [item.value for item in LogSeverity],
                                "type": "string",
                            },
                            "trace_id": {"maxLength": 128, "minLength": 1, "type": "string"},
                        },
                        "required": ["labels", "message", "observed_at", "severity"],
                        "type": "object",
                    },
                    "maxItems": MAX_LOG_QUERY_RECORDS,
                    "type": "array",
                },
                "records_dropped": {"minimum": 0, "type": "integer"},
                "schema_version": {"const": "1.0.0", "type": "string"},
                "source": {"const": "loki", "type": "string"},
            },
            "required": [
                "complete_window",
                "query",
                "records",
                "records_dropped",
                "schema_version",
                "source",
            ],
            "type": "object",
        },
    )
    return ToolDefinition(
        name="query_logs",
        semantic_version=QUERY_LOGS_VERSION,
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
        audit=ToolAuditPolicy("tool.call", QUERY_LOGS_VERSION),
        max_input_bytes=2_048,
        max_result_bytes=4 * 1024 * 1024,
    )


class QueryLogsAdapter:
    def __init__(self, backend: LogsBackend) -> None:
        self._backend = backend

    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        del context
        try:
            start = as_utc(datetime.fromisoformat(str(arguments["start"])))
            end = as_utc(datetime.fromisoformat(str(arguments["end"])))
            minimum_severity = LogSeverity(arguments["minimum_severity"])
        except (KeyError, ValueError) as exc:
            raise InvalidDomainValueError(
                "log query values must use the versioned contract"
            ) from exc
        if end <= start or end - start > MAX_LOG_QUERY_WINDOW:
            raise InvalidDomainValueError("log query window is invalid or too large")
        contains = str(arguments["contains"])
        if (
            not contains.strip()
            or len(contains) > 128
            or any(ord(character) < 32 or ord(character) == 127 for character in contains)
        ):
            raise InvalidDomainValueError("log query match text is invalid")
        limit = int(arguments["limit"])
        if not 1 <= limit <= MAX_LOG_QUERY_RECORDS:
            raise InvalidDomainValueError("log query limit is outside the bounded range")
        query = LogQuery(
            service=str(arguments["service"]),
            environment=str(arguments["environment"]),
            start=start.isoformat(),
            end=end.isoformat(),
            minimum_severity=minimum_severity,
            contains=contains,
            limit=limit,
        )
        result = await self._backend.query_range(query)
        if len(result.records) > limit:
            raise InvalidDomainValueError("log backend exceeded the requested limit")
        records: list[dict[str, Any]] = []
        previous_observed_at: datetime | None = None
        for record in result.records:
            if not start <= record.observed_at <= end:
                raise InvalidDomainValueError("log backend returned an out-of-window record")
            if previous_observed_at is not None and record.observed_at < previous_observed_at:
                raise InvalidDomainValueError("log backend records are not time ordered")
            previous_observed_at = record.observed_at
            if _LOG_SEVERITY_ORDER[record.severity] < _LOG_SEVERITY_ORDER[minimum_severity]:
                raise InvalidDomainValueError(
                    "log backend returned a record below severity threshold"
                )
            labels = dict(record.labels)
            if labels != {"environment": query.environment, "service": query.service}:
                raise InvalidDomainValueError("log backend returned mismatched scope labels")
            item: dict[str, Any] = {
                "labels": labels,
                "message": record.message,
                "observed_at": record.observed_at.isoformat(),
                "severity": record.severity.value,
            }
            if record.trace_id is not None:
                item["trace_id"] = record.trace_id
            records.append(item)
        return {
            "complete_window": result.complete_window,
            "query": {
                "contains": query.contains,
                "end": query.end,
                "environment": query.environment,
                "limit": query.limit,
                "minimum_severity": query.minimum_severity.value,
                "service": query.service,
                "start": query.start,
            },
            "records": records,
            "records_dropped": result.records_dropped,
            "schema_version": QUERY_LOGS_VERSION.value,
            "source": "loki",
        }


def query_traces_definition() -> ToolDefinition:
    input_schema = ToolSchema.from_mapping(
        QUERY_TRACES_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "end": {"maxLength": 40, "minLength": 20, "type": "string"},
                "environment": {"enum": ["production", "staging"], "type": "string"},
                "max_traces": {
                    "maximum": MAX_TRACE_QUERY_TRACES,
                    "minimum": 1,
                    "type": "integer",
                },
                "service": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "[a-z][a-z0-9-]*",
                    "type": "string",
                },
                "start": {"maxLength": 40, "minLength": 20, "type": "string"},
                "status": {
                    "enum": [item.value for item in TraceStatusFilter],
                    "type": "string",
                },
            },
            "required": ["end", "environment", "max_traces", "service", "start", "status"],
            "type": "object",
        },
    )
    output_schema = ToolSchema.from_mapping(
        QUERY_TRACES_VERSION,
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
                "schema_version": {"const": "1.0.0", "type": "string"},
                "source": {"const": "tempo", "type": "string"},
                "spans": {
                    "items": {
                        "additionalProperties": False,
                        "properties": {
                            "ended_at": {"type": "string"},
                            "environment": {"type": "string"},
                            "operation": {"maxLength": 256, "minLength": 1, "type": "string"},
                            "parent_span_id": {
                                "maxLength": 128,
                                "minLength": 1,
                                "type": "string",
                            },
                            "service": {"type": "string"},
                            "span_id": {"maxLength": 128, "minLength": 1, "type": "string"},
                            "started_at": {"type": "string"},
                            "status": {
                                "enum": [item.value for item in TraceStatus],
                                "type": "string",
                            },
                            "trace_id": {"maxLength": 128, "minLength": 1, "type": "string"},
                        },
                        "required": [
                            "ended_at",
                            "environment",
                            "operation",
                            "service",
                            "span_id",
                            "started_at",
                            "status",
                            "trace_id",
                        ],
                        "type": "object",
                    },
                    "maxItems": MAX_TRACE_QUERY_SPANS,
                    "type": "array",
                },
                "trace_count": {
                    "maximum": MAX_TRACE_QUERY_TRACES,
                    "minimum": 0,
                    "type": "integer",
                },
            },
            "required": [
                "complete_window",
                "query",
                "records_dropped",
                "schema_version",
                "source",
                "spans",
                "trace_count",
            ],
            "type": "object",
        },
    )
    return ToolDefinition(
        name="query_traces",
        semantic_version=QUERY_TRACES_VERSION,
        input_schema=input_schema,
        output_schema=output_schema,
        access_class=ToolAccessClass.READ,
        risk=ToolRisk.LOW,
        required_permission=Permission.EVIDENCE_READ,
        timeout_ms=15_000,
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
        audit=ToolAuditPolicy("tool.call", QUERY_TRACES_VERSION),
        max_input_bytes=2_048,
        max_result_bytes=8 * 1024 * 1024,
    )


class QueryTracesAdapter:
    def __init__(self, backend: TracesBackend) -> None:
        self._backend = backend

    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        del context
        try:
            start = as_utc(datetime.fromisoformat(str(arguments["start"])))
            end = as_utc(datetime.fromisoformat(str(arguments["end"])))
            status = TraceStatusFilter(arguments["status"])
        except (KeyError, ValueError) as exc:
            raise InvalidDomainValueError(
                "trace query values must use the versioned contract"
            ) from exc
        if end <= start or end - start > MAX_TRACE_QUERY_WINDOW:
            raise InvalidDomainValueError("trace query window is invalid or too large")
        max_traces = int(arguments["max_traces"])
        if not 1 <= max_traces <= MAX_TRACE_QUERY_TRACES:
            raise InvalidDomainValueError("trace query count is outside the bounded range")
        query = TraceQuery(
            service=str(arguments["service"]),
            environment=str(arguments["environment"]),
            start=start.isoformat(),
            end=end.isoformat(),
            status=status,
            max_traces=max_traces,
        )
        result = await self._backend.query_range(query)
        by_trace: dict[str, dict[str, TraceBackendSpan]] = {}
        previous_key: tuple[str, datetime, str] | None = None
        for span in result.spans:
            if not start <= span.started_at <= span.ended_at <= end:
                raise InvalidDomainValueError("trace backend returned an out-of-window span")
            if span.environment != query.environment:
                raise InvalidDomainValueError("trace backend returned a mismatched environment")
            key = (span.trace_id, span.started_at, span.span_id)
            if previous_key is not None and key < previous_key:
                raise InvalidDomainValueError(
                    "trace backend spans are not deterministically ordered"
                )
            previous_key = key
            trace = by_trace.setdefault(span.trace_id, {})
            if span.span_id in trace:
                raise InvalidDomainValueError("trace backend returned a duplicate span ID")
            trace[span.span_id] = span
        if len(by_trace) > max_traces:
            raise InvalidDomainValueError("trace backend exceeded the requested trace count")
        for spans in by_trace.values():
            roots = [span for span in spans.values() if span.parent_span_id is None]
            if len(roots) != 1:
                raise InvalidDomainValueError("trace backend must return one root per trace")
            if query.service not in {span.service for span in spans.values()}:
                raise InvalidDomainValueError("trace backend omitted the requested service scope")
            if query.status is not TraceStatusFilter.ANY and not any(
                span.status.value == query.status.value for span in spans.values()
            ):
                raise InvalidDomainValueError(
                    "trace backend returned a trace outside status filter"
                )
            for span in spans.values():
                if span.parent_span_id is None:
                    continue
                parent = spans.get(span.parent_span_id)
                if parent is None:
                    raise InvalidDomainValueError("trace backend parent span is missing")
                if span.started_at < parent.started_at or span.ended_at > parent.ended_at:
                    raise InvalidDomainValueError("trace backend child is outside its parent")
        output_spans: list[dict[str, Any]] = []
        for span in result.spans:
            item: dict[str, Any] = {
                "ended_at": span.ended_at.isoformat(),
                "environment": span.environment,
                "operation": span.operation,
                "service": span.service,
                "span_id": span.span_id,
                "started_at": span.started_at.isoformat(),
                "status": span.status.value,
                "trace_id": span.trace_id,
            }
            if span.parent_span_id is not None:
                item["parent_span_id"] = span.parent_span_id
            output_spans.append(item)
        return {
            "complete_window": result.complete_window,
            "query": {
                "end": query.end,
                "environment": query.environment,
                "max_traces": query.max_traces,
                "service": query.service,
                "start": query.start,
                "status": query.status.value,
            },
            "records_dropped": result.records_dropped,
            "schema_version": QUERY_TRACES_VERSION.value,
            "source": "tempo",
            "spans": output_spans,
            "trace_count": len(by_trace),
        }
