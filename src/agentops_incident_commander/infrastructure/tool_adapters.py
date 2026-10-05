"""Read-only Tool Gateway adapters over server-owned observability ports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from agentops_incident_commander.application import IncidentMemorySearchStore, ToolAdapterContext
from agentops_incident_commander.domain import (
    MAX_MEMORY_LOOKBACK,
    MAX_SIMILAR_INCIDENT_RESULTS,
    IncidentId,
    IncidentMemorySearchQuery,
    Permission,
    RetryableToolError,
    SemanticVersion,
    SimilarIncidentReference,
    TenantId,
    ToolAccessClass,
    ToolAuditPolicy,
    ToolDefinition,
    ToolIdempotency,
    ToolRetryPolicy,
    ToolRisk,
    ToolSchema,
    as_utc,
    utc_now,
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
QUERY_DEPLOYMENTS_VERSION = SemanticVersion("1.0.0")
MAX_DEPLOYMENT_QUERY_WINDOW = timedelta(days=30)
MAX_DEPLOYMENT_QUERY_RECORDS = 500
GET_SERVICE_TOPOLOGY_VERSION = SemanticVersion("1.0.0")
MAX_TOPOLOGY_NODES = 100
MAX_TOPOLOGY_EDGES = 500
MAX_TOPOLOGY_DEPTH = 5
SEARCH_SIMILAR_INCIDENTS_DISABLED_VERSION = SemanticVersion("1.0.0")
SEARCH_SIMILAR_INCIDENTS_VERSION = SemanticVersion("2.0.0")


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


class TopologyNodeKind(StrEnum):
    SERVICE = "SERVICE"
    GATEWAY = "GATEWAY"
    DATABASE = "DATABASE"
    CACHE = "CACHE"
    EXTERNAL = "EXTERNAL"


class TopologyRelation(StrEnum):
    ROUTES = "ROUTES"
    CALLS = "CALLS"
    READS = "READS"
    WRITES = "WRITES"
    DEPENDS_ON = "DEPENDS_ON"


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


@dataclass(frozen=True, slots=True)
class DeploymentQuery:
    service: str
    environment: str
    start: str
    end: str
    limit: int


@dataclass(frozen=True, slots=True)
class DeploymentBackendRecord:
    deployment_id: str
    service: str
    environment: str
    version: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        for field, maximum in (
            ("deployment_id", 128),
            ("service", 128),
            ("environment", 32),
            ("version", 256),
        ):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > maximum
                or "\x00" in value
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise InvalidDomainValueError(f"deployment backend {field} is invalid")
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))


@dataclass(frozen=True, slots=True)
class DeploymentBackendResult:
    records: tuple[DeploymentBackendRecord, ...]
    complete_window: bool
    records_dropped: int = 0

    def __post_init__(self) -> None:
        if len(self.records) > MAX_DEPLOYMENT_QUERY_RECORDS:
            raise InvalidDomainValueError("deployment backend result exceeds the record limit")
        if not isinstance(self.complete_window, bool):
            raise InvalidDomainValueError("deployment backend completeness must be boolean")
        if (
            not isinstance(self.records_dropped, int)
            or isinstance(self.records_dropped, bool)
            or self.records_dropped < 0
        ):
            raise InvalidDomainValueError("deployment backend dropped count is invalid")


class DeploymentsBackend(Protocol):
    async def query_range(self, query: DeploymentQuery) -> DeploymentBackendResult: ...


@dataclass(frozen=True, slots=True)
class TopologyQuery:
    root_service: str
    environment: str
    max_depth: int


@dataclass(frozen=True, slots=True, order=True)
class TopologyBackendNode:
    service: str
    environment: str
    kind: TopologyNodeKind

    def __post_init__(self) -> None:
        for field, maximum in (("service", 128), ("environment", 32)):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > maximum
                or "\x00" in value
            ):
                raise InvalidDomainValueError(f"topology backend {field} is invalid")
        if not isinstance(self.kind, TopologyNodeKind):
            raise InvalidDomainValueError("topology backend node kind is invalid")


@dataclass(frozen=True, slots=True, order=True)
class TopologyBackendEdge:
    source: str
    target: str
    relation: TopologyRelation

    def __post_init__(self) -> None:
        for field in ("source", "target"):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 128
                or "\x00" in value
            ):
                raise InvalidDomainValueError(f"topology backend edge {field} is invalid")
        if self.source == self.target:
            raise InvalidDomainValueError("topology backend self edges are not allowed")
        if not isinstance(self.relation, TopologyRelation):
            raise InvalidDomainValueError("topology backend relation is invalid")


@dataclass(frozen=True, slots=True)
class TopologyBackendResult:
    nodes: tuple[TopologyBackendNode, ...]
    edges: tuple[TopologyBackendEdge, ...]

    def __post_init__(self) -> None:
        if len(self.nodes) > MAX_TOPOLOGY_NODES:
            raise InvalidDomainValueError("topology backend node limit exceeded")
        if len(self.edges) > MAX_TOPOLOGY_EDGES:
            raise InvalidDomainValueError("topology backend edge limit exceeded")


class TopologyBackend(Protocol):
    async def get_topology(self, query: TopologyQuery) -> TopologyBackendResult: ...


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


def query_deployments_definition() -> ToolDefinition:
    input_schema = ToolSchema.from_mapping(
        QUERY_DEPLOYMENTS_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "end": {"maxLength": 40, "minLength": 20, "type": "string"},
                "environment": {"enum": ["production", "staging"], "type": "string"},
                "limit": {
                    "maximum": MAX_DEPLOYMENT_QUERY_RECORDS,
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
            },
            "required": ["end", "environment", "limit", "service", "start"],
            "type": "object",
        },
    )
    output_schema = ToolSchema.from_mapping(
        QUERY_DEPLOYMENTS_VERSION,
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
                            "deployment_id": {
                                "maxLength": 128,
                                "minLength": 1,
                                "type": "string",
                            },
                            "environment": {"type": "string"},
                            "occurred_at": {"type": "string"},
                            "service": {"type": "string"},
                            "version": {"maxLength": 256, "minLength": 1, "type": "string"},
                        },
                        "required": [
                            "deployment_id",
                            "environment",
                            "occurred_at",
                            "service",
                            "version",
                        ],
                        "type": "object",
                    },
                    "maxItems": MAX_DEPLOYMENT_QUERY_RECORDS,
                    "type": "array",
                },
                "records_dropped": {"minimum": 0, "type": "integer"},
                "schema_version": {"const": "1.0.0", "type": "string"},
                "source": {"const": "deployment-registry", "type": "string"},
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
        name="query_deployments",
        semantic_version=QUERY_DEPLOYMENTS_VERSION,
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
        audit=ToolAuditPolicy("tool.call", QUERY_DEPLOYMENTS_VERSION),
        max_input_bytes=2_048,
        max_result_bytes=2 * 1024 * 1024,
    )


class QueryDeploymentsAdapter:
    def __init__(self, backend: DeploymentsBackend) -> None:
        self._backend = backend

    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        del context
        try:
            start = as_utc(datetime.fromisoformat(str(arguments["start"])))
            end = as_utc(datetime.fromisoformat(str(arguments["end"])))
        except (KeyError, ValueError) as exc:
            raise InvalidDomainValueError(
                "deployment query timestamps must be ISO-8601 UTC"
            ) from exc
        if end <= start or end - start > MAX_DEPLOYMENT_QUERY_WINDOW:
            raise InvalidDomainValueError("deployment query window is invalid or too large")
        limit = int(arguments["limit"])
        if not 1 <= limit <= MAX_DEPLOYMENT_QUERY_RECORDS:
            raise InvalidDomainValueError("deployment query limit is outside the bounded range")
        query = DeploymentQuery(
            service=str(arguments["service"]),
            environment=str(arguments["environment"]),
            start=start.isoformat(),
            end=end.isoformat(),
            limit=limit,
        )
        result = await self._backend.query_range(query)
        if len(result.records) > limit:
            raise InvalidDomainValueError("deployment backend exceeded the requested limit")
        seen_ids: set[str] = set()
        seen_times: set[datetime] = set()
        previous_time: datetime | None = None
        records: list[dict[str, Any]] = []
        for record in result.records:
            if record.service != query.service or record.environment != query.environment:
                raise InvalidDomainValueError("deployment backend returned mismatched scope")
            if not start <= record.occurred_at <= end:
                raise InvalidDomainValueError("deployment backend returned an out-of-window record")
            if previous_time is not None and record.occurred_at < previous_time:
                raise InvalidDomainValueError("deployment backend records are not time ordered")
            previous_time = record.occurred_at
            if record.deployment_id in seen_ids:
                raise InvalidDomainValueError(
                    "deployment backend returned a duplicate deployment ID"
                )
            if record.occurred_at in seen_times:
                raise InvalidDomainValueError("deployment backend returned a duplicate timestamp")
            seen_ids.add(record.deployment_id)
            seen_times.add(record.occurred_at)
            records.append(
                {
                    "deployment_id": record.deployment_id,
                    "environment": record.environment,
                    "occurred_at": record.occurred_at.isoformat(),
                    "service": record.service,
                    "version": record.version,
                }
            )
        return {
            "complete_window": result.complete_window,
            "query": {
                "end": query.end,
                "environment": query.environment,
                "limit": query.limit,
                "service": query.service,
                "start": query.start,
            },
            "records": records,
            "records_dropped": result.records_dropped,
            "schema_version": QUERY_DEPLOYMENTS_VERSION.value,
            "source": "deployment-registry",
        }


def get_service_topology_definition() -> ToolDefinition:
    input_schema = ToolSchema.from_mapping(
        GET_SERVICE_TOPOLOGY_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "environment": {"enum": ["production", "staging"], "type": "string"},
                "max_depth": {
                    "maximum": MAX_TOPOLOGY_DEPTH,
                    "minimum": 1,
                    "type": "integer",
                },
                "root_service": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "[a-z][a-z0-9-]*",
                    "type": "string",
                },
            },
            "required": ["environment", "max_depth", "root_service"],
            "type": "object",
        },
    )
    output_schema = ToolSchema.from_mapping(
        GET_SERVICE_TOPOLOGY_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "edges": {
                    "items": {
                        "additionalProperties": False,
                        "properties": {
                            "relation": {
                                "enum": [item.value for item in TopologyRelation],
                                "type": "string",
                            },
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                        },
                        "required": ["relation", "source", "target"],
                        "type": "object",
                    },
                    "maxItems": MAX_TOPOLOGY_EDGES,
                    "type": "array",
                },
                "nodes": {
                    "items": {
                        "additionalProperties": False,
                        "properties": {
                            "environment": {"type": "string"},
                            "kind": {
                                "enum": [item.value for item in TopologyNodeKind],
                                "type": "string",
                            },
                            "service": {"type": "string"},
                        },
                        "required": ["environment", "kind", "service"],
                        "type": "object",
                    },
                    "maxItems": MAX_TOPOLOGY_NODES,
                    "type": "array",
                },
                "query": {
                    "additionalProperties": False,
                    "properties": input_schema.as_dict()["properties"],
                    "required": input_schema.as_dict()["required"],
                    "type": "object",
                },
                "schema_version": {"const": "1.0.0", "type": "string"},
                "source": {"const": "service-catalog", "type": "string"},
            },
            "required": ["edges", "nodes", "query", "schema_version", "source"],
            "type": "object",
        },
    )
    return ToolDefinition(
        name="get_service_topology",
        semantic_version=GET_SERVICE_TOPOLOGY_VERSION,
        input_schema=input_schema,
        output_schema=output_schema,
        access_class=ToolAccessClass.READ,
        risk=ToolRisk.LOW,
        required_permission=Permission.EVIDENCE_READ,
        timeout_ms=5_000,
        retry_policy=ToolRetryPolicy(
            3,
            100,
            1_000,
            frozenset({RetryableToolError.CONNECTION, RetryableToolError.TIMEOUT}),
        ),
        idempotency=ToolIdempotency.NOT_APPLICABLE,
        audit=ToolAuditPolicy("tool.call", GET_SERVICE_TOPOLOGY_VERSION),
        max_input_bytes=1_024,
        max_result_bytes=2 * 1024 * 1024,
    )


class GetServiceTopologyAdapter:
    def __init__(self, backend: TopologyBackend) -> None:
        self._backend = backend

    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        del context
        max_depth = int(arguments["max_depth"])
        if not 1 <= max_depth <= MAX_TOPOLOGY_DEPTH:
            raise InvalidDomainValueError("topology query depth is outside the bounded range")
        query = TopologyQuery(
            root_service=str(arguments["root_service"]),
            environment=str(arguments["environment"]),
            max_depth=max_depth,
        )
        result = await self._backend.get_topology(query)
        if tuple(sorted(result.nodes)) != result.nodes:
            raise InvalidDomainValueError("topology backend nodes are not ordered")
        if tuple(sorted(result.edges)) != result.edges:
            raise InvalidDomainValueError("topology backend edges are not ordered")
        if len(set(result.nodes)) != len(result.nodes):
            raise InvalidDomainValueError("topology backend returned duplicate nodes")
        if len(set(result.edges)) != len(result.edges):
            raise InvalidDomainValueError("topology backend returned duplicate edges")
        by_service = {node.service: node for node in result.nodes}
        if len(by_service) != len(result.nodes):
            raise InvalidDomainValueError("topology backend service names must be unique")
        root = by_service.get(query.root_service)
        if root is None:
            raise InvalidDomainValueError("topology backend omitted the root service")
        if any(node.environment != query.environment for node in result.nodes):
            raise InvalidDomainValueError("topology backend returned a mismatched environment")
        adjacency: dict[str, set[str]] = {service: set() for service in by_service}
        for edge in result.edges:
            if edge.source not in by_service or edge.target not in by_service:
                raise InvalidDomainValueError("topology backend edge references an unknown node")
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)
        distances = {root.service: 0}
        frontier = [root.service]
        while frontier:
            service = frontier.pop(0)
            for neighbour in sorted(adjacency[service]):
                if neighbour not in distances:
                    distances[neighbour] = distances[service] + 1
                    frontier.append(neighbour)
        if set(distances) != set(by_service):
            raise InvalidDomainValueError("topology backend returned a disconnected graph")
        if any(distance > max_depth for distance in distances.values()):
            raise InvalidDomainValueError("topology backend exceeded the requested depth")
        return {
            "edges": [
                {
                    "relation": edge.relation.value,
                    "source": edge.source,
                    "target": edge.target,
                }
                for edge in result.edges
            ],
            "nodes": [
                {
                    "environment": node.environment,
                    "kind": node.kind.value,
                    "service": node.service,
                }
                for node in result.nodes
            ],
            "query": {
                "environment": query.environment,
                "max_depth": query.max_depth,
                "root_service": query.root_service,
            },
            "schema_version": GET_SERVICE_TOPOLOGY_VERSION.value,
            "source": "service-catalog",
        }


def _similar_incident_input_schema(version: SemanticVersion) -> ToolSchema:
    return ToolSchema.from_mapping(
        version,
        {
            "additionalProperties": False,
            "properties": {
                "max_results": {
                    "maximum": MAX_SIMILAR_INCIDENT_RESULTS,
                    "minimum": 1,
                    "type": "integer",
                }
            },
            "required": ["max_results"],
            "type": "object",
        },
    )


def search_similar_incidents_disabled_definition() -> ToolDefinition:
    """Retain the immutable Phase 4 disabled v1 contract."""
    input_schema = _similar_incident_input_schema(SEARCH_SIMILAR_INCIDENTS_DISABLED_VERSION)
    output_schema = ToolSchema.from_mapping(
        SEARCH_SIMILAR_INCIDENTS_DISABLED_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "disabled_reason": {
                    "const": "MEMORY_BACKEND_DISABLED_UNTIL_PHASE_7",
                    "type": "string",
                },
                "enabled": {"const": False, "type": "boolean"},
                "historical_reference_only": {"const": True, "type": "boolean"},
                "query": {
                    "additionalProperties": False,
                    "properties": input_schema.as_dict()["properties"],
                    "required": input_schema.as_dict()["required"],
                    "type": "object",
                },
                "results": {
                    "items": {
                        "additionalProperties": False,
                        "properties": {
                            "historical_reference_only": {"const": True, "type": "boolean"},
                            "incident_id": {"type": "string"},
                            "similarity": {
                                "maximum": 1.0,
                                "minimum": 0.0,
                                "type": "number",
                            },
                        },
                        "required": [
                            "historical_reference_only",
                            "incident_id",
                            "similarity",
                        ],
                        "type": "object",
                    },
                    "maxItems": MAX_SIMILAR_INCIDENT_RESULTS,
                    "type": "array",
                },
                "schema_version": {
                    "const": SEARCH_SIMILAR_INCIDENTS_DISABLED_VERSION.value,
                    "type": "string",
                },
                "source": {"const": "incident-memory", "type": "string"},
            },
            "required": [
                "disabled_reason",
                "enabled",
                "historical_reference_only",
                "query",
                "results",
                "schema_version",
                "source",
            ],
            "type": "object",
        },
    )
    return _similar_incidents_definition(
        version=SEARCH_SIMILAR_INCIDENTS_DISABLED_VERSION,
        input_schema=input_schema,
        output_schema=output_schema,
    )


def search_similar_incidents_definition() -> ToolDefinition:
    """Return the enabled historical-reference-only v2 contract."""
    input_schema = _similar_incident_input_schema(SEARCH_SIMILAR_INCIDENTS_VERSION)
    result_properties = {
        "closed_at": {"type": "string"},
        "historical_reference_only": {"const": True, "type": "boolean"},
        "incident_id": {"type": "string"},
        "outcome": {"type": "string"},
        "outcome_summary": {"maxLength": 1024, "minLength": 1, "type": "string"},
        "root_cause_summary": {"maxLength": 1024, "minLength": 1, "type": "string"},
        "service": {"maxLength": 128, "minLength": 1, "type": "string"},
        "similarity": {"maximum": 1.0, "minimum": 0.0, "type": "number"},
    }
    input_schema = ToolSchema.from_mapping(
        SEARCH_SIMILAR_INCIDENTS_VERSION,
        input_schema.as_dict(),
    )
    output_schema = ToolSchema.from_mapping(
        SEARCH_SIMILAR_INCIDENTS_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "enabled": {"const": True, "type": "boolean"},
                "historical_reference_only": {"const": True, "type": "boolean"},
                "query": {
                    "additionalProperties": False,
                    "properties": input_schema.as_dict()["properties"],
                    "required": input_schema.as_dict()["required"],
                    "type": "object",
                },
                "results": {
                    "items": {
                        "additionalProperties": False,
                        "properties": result_properties,
                        "required": sorted(result_properties),
                        "type": "object",
                    },
                    "maxItems": MAX_SIMILAR_INCIDENT_RESULTS,
                    "type": "array",
                },
                "schema_version": {
                    "const": SEARCH_SIMILAR_INCIDENTS_VERSION.value,
                    "type": "string",
                },
                "source": {"const": "incident-memory", "type": "string"},
            },
            "required": [
                "enabled",
                "historical_reference_only",
                "query",
                "results",
                "schema_version",
                "source",
            ],
            "type": "object",
        },
    )
    return _similar_incidents_definition(
        version=SEARCH_SIMILAR_INCIDENTS_VERSION,
        input_schema=input_schema,
        output_schema=output_schema,
    )


def _similar_incidents_definition(
    *,
    version: SemanticVersion,
    input_schema: ToolSchema,
    output_schema: ToolSchema,
) -> ToolDefinition:
    return ToolDefinition(
        name="search_similar_incidents",
        semantic_version=version,
        input_schema=input_schema,
        output_schema=output_schema,
        access_class=ToolAccessClass.READ,
        risk=ToolRisk.LOW,
        required_permission=Permission.EVIDENCE_READ,
        timeout_ms=1_000,
        retry_policy=ToolRetryPolicy(1, 0, 0, frozenset()),
        idempotency=ToolIdempotency.NOT_APPLICABLE,
        audit=ToolAuditPolicy("tool.call", version),
        max_input_bytes=512,
        max_result_bytes=64 * 1024,
    )


class SearchSimilarIncidentsDisabledAdapter:
    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        del context
        max_results = int(arguments["max_results"])
        if not 1 <= max_results <= MAX_SIMILAR_INCIDENT_RESULTS:
            raise InvalidDomainValueError("similar incident result limit is outside bounds")
        return {
            "disabled_reason": "MEMORY_BACKEND_DISABLED_UNTIL_PHASE_7",
            "enabled": False,
            "historical_reference_only": True,
            "query": {"max_results": max_results},
            "results": [],
            "schema_version": SEARCH_SIMILAR_INCIDENTS_DISABLED_VERSION.value,
            "source": "incident-memory",
        }


class IncidentMemoryQueryProvider(Protocol):
    """Build a query vector from server-owned current-Incident context."""

    async def query_for(
        self,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
        max_results: int,
        requested_at: datetime,
        max_age: timedelta,
    ) -> IncidentMemorySearchQuery: ...


class SearchSimilarIncidentsAdapter:
    """Expose bounded historical retrieval without accepting model-supplied query content."""

    def __init__(
        self,
        query_provider: IncidentMemoryQueryProvider,
        store: IncidentMemorySearchStore,
        *,
        clock: Callable[[], datetime] = utc_now,
        max_age: timedelta = timedelta(days=365),
    ) -> None:
        if not timedelta(0) < max_age <= MAX_MEMORY_LOOKBACK:
            raise InvalidDomainValueError("similar Incident adapter freshness window is invalid")
        self._query_provider = query_provider
        self._store = store
        self._clock = clock
        self._max_age = max_age

    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        max_results = arguments["max_results"]
        if (
            not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or not 1 <= max_results <= MAX_SIMILAR_INCIDENT_RESULTS
        ):
            raise InvalidDomainValueError("similar incident result limit is outside bounds")
        requested_at = as_utc(self._clock())
        query = await self._query_provider.query_for(
            tenant_id=context.tenant_id,
            incident_id=context.incident_id,
            max_results=max_results,
            requested_at=requested_at,
            max_age=self._max_age,
        )
        if (
            not isinstance(query, IncidentMemorySearchQuery)
            or query.tenant_id != context.tenant_id
            or query.current_incident_id != context.incident_id
            or query.max_results != max_results
            or query.requested_at != requested_at
            or query.max_age != self._max_age
        ):
            raise InvalidDomainValueError("server-owned similar Incident query scope drifted")
        results = await self._store.search(query)
        if (
            not isinstance(results, tuple)
            or len(results) > max_results
            or any(not isinstance(item, SimilarIncidentReference) for item in results)
            or any(item.incident_id == context.incident_id for item in results)
            or len({item.incident_id for item in results}) != len(results)
            or results
            != tuple(
                sorted(
                    results,
                    key=lambda item: (
                        -item.similarity,
                        -item.closed_at.timestamp(),
                        item.incident_id.value,
                    ),
                )
            )
        ):
            raise InvalidDomainValueError("similar Incident backend result is invalid")
        return {
            "enabled": True,
            "historical_reference_only": True,
            "query": {"max_results": max_results},
            "results": [
                {
                    "closed_at": item.closed_at.isoformat(),
                    "historical_reference_only": True,
                    "incident_id": item.incident_id.value,
                    "outcome": item.outcome,
                    "outcome_summary": item.outcome_summary,
                    "root_cause_summary": item.root_cause_summary,
                    "service": item.service,
                    "similarity": item.similarity,
                }
                for item in results
            ],
            "schema_version": SEARCH_SIMILAR_INCIDENTS_VERSION.value,
            "source": "incident-memory",
        }
