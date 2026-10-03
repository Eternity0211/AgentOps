"""Deterministic, bounded telemetry/deployment/topology Evidence collectors."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from agentops_incident_commander.domain import (
    EvidenceBuildRequest,
    EvidenceNormalizer,
    EvidenceSourceType,
    InvalidDomainValueError,
    JsonValue,
    NormalizedEvidence,
    PromptInjectionStatus,
    QualitySignals,
    as_utc,
)

MAX_COLLECTOR_RECORDS: Final = 1_000


def _text(value: str, *, field: str, maximum: int = 256) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise InvalidDomainValueError(f"collector {field} must be bounded non-null text")
    return normalized


def _records(values: tuple[object, ...]) -> None:
    if len(values) > MAX_COLLECTOR_RECORDS:
        raise InvalidDomainValueError("collector record limit exceeded")


def _collect(
    request: EvidenceBuildRequest,
    payload: JsonValue,
    *,
    source_type: EvidenceSourceType,
    tool_name: str,
    record_count: int,
    complete_window: bool,
    records_dropped: int,
    parser_warning_count: int,
    injection_status: PromptInjectionStatus = PromptInjectionStatus.NONE,
) -> NormalizedEvidence:
    if request.source_type is not source_type or request.tool_name != tool_name:
        raise InvalidDomainValueError("collector request does not match its typed adapter")
    adjusted = replace(
        request,
        quality_signals=QualitySignals(
            source_available=True,
            complete_window=complete_window,
            records_seen=record_count,
            records_dropped=records_dropped,
            parser_warning_count=parser_warning_count,
        ),
        prompt_injection_status=injection_status,
    )
    return EvidenceNormalizer().normalize(adjusted, payload)


@dataclass(frozen=True, slots=True)
class MetricSample:
    metric: str
    observed_at: datetime
    value: float
    labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric", _text(self.metric, field="metric"))
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))
        if not math.isfinite(self.value):
            raise InvalidDomainValueError("collector metric value must be finite")
        normalized = tuple(
            sorted(
                (_text(k, field="label key"), _text(v, field="label value")) for k, v in self.labels
            )
        )
        if len({key for key, _ in normalized}) != len(normalized):
            raise InvalidDomainValueError("collector metric labels must be unique")
        object.__setattr__(self, "labels", normalized)


class MetricsCollector:
    def collect(
        self,
        request: EvidenceBuildRequest,
        samples: tuple[MetricSample, ...],
        *,
        complete_window: bool = True,
        records_dropped: int = 0,
    ) -> NormalizedEvidence:
        _records(samples)
        payload: JsonValue = {
            "kind": "metrics",
            "samples": [
                {
                    "labels": dict(sample.labels),
                    "metric": sample.metric,
                    "observed_at": sample.observed_at.isoformat(),
                    "value": sample.value,
                }
                for sample in samples
            ],
        }
        return _collect(
            request,
            payload,
            source_type=EvidenceSourceType.METRIC,
            tool_name="query_metrics",
            record_count=len(samples),
            complete_window=complete_window,
            records_dropped=records_dropped,
            parser_warning_count=0,
        )


@dataclass(frozen=True, slots=True)
class LogRecord:
    observed_at: datetime
    service: str
    severity: str
    message: str
    trace_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))
        object.__setattr__(self, "service", _text(self.service, field="log service"))
        object.__setattr__(
            self, "severity", _text(self.severity, field="log severity", maximum=32).upper()
        )
        object.__setattr__(self, "message", _text(self.message, field="log message", maximum=4_096))
        if self.trace_id is not None:
            object.__setattr__(
                self, "trace_id", _text(self.trace_id, field="trace ID", maximum=128)
            )


class LogsCollector:
    def collect(
        self,
        request: EvidenceBuildRequest,
        records: tuple[LogRecord, ...],
        *,
        injection_status: PromptInjectionStatus = PromptInjectionStatus.NONE,
        complete_window: bool = True,
        records_dropped: int = 0,
        parser_warning_count: int = 0,
    ) -> NormalizedEvidence:
        _records(records)
        payload: JsonValue = {
            "kind": "logs",
            "records": [
                {
                    "message": record.message,
                    "observed_at": record.observed_at.isoformat(),
                    "service": record.service,
                    "severity": record.severity,
                    "trace_id": record.trace_id,
                }
                for record in records
            ],
        }
        return _collect(
            request,
            payload,
            source_type=EvidenceSourceType.LOG,
            tool_name="query_logs",
            record_count=len(records),
            complete_window=complete_window,
            records_dropped=records_dropped,
            parser_warning_count=parser_warning_count,
            injection_status=injection_status,
        )


@dataclass(frozen=True, slots=True)
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    operation: str
    started_at: datetime
    ended_at: datetime
    status: str

    def __post_init__(self) -> None:
        for field, value in (
            ("trace ID", self.trace_id),
            ("span ID", self.span_id),
            ("service", self.service),
            ("operation", self.operation),
            ("status", self.status),
        ):
            object.__setattr__(self, field.lower().replace(" ", "_"), _text(value, field=field))
        if self.parent_span_id is not None:
            object.__setattr__(
                self, "parent_span_id", _text(self.parent_span_id, field="parent span ID")
            )
        started_at = as_utc(self.started_at)
        ended_at = as_utc(self.ended_at)
        if ended_at < started_at:
            raise InvalidDomainValueError("collector trace span time range is reversed")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "ended_at", ended_at)


class TracesCollector:
    def collect(
        self, request: EvidenceBuildRequest, spans: tuple[TraceSpan, ...]
    ) -> NormalizedEvidence:
        _records(spans)
        payload: JsonValue = {
            "kind": "traces",
            "spans": [
                {
                    "ended_at": span.ended_at.isoformat(),
                    "operation": span.operation,
                    "parent_span_id": span.parent_span_id,
                    "service": span.service,
                    "span_id": span.span_id,
                    "started_at": span.started_at.isoformat(),
                    "status": span.status,
                    "trace_id": span.trace_id,
                }
                for span in spans
            ],
        }
        return _collect(
            request,
            payload,
            source_type=EvidenceSourceType.TRACE,
            tool_name="query_traces",
            record_count=len(spans),
            complete_window=True,
            records_dropped=0,
            parser_warning_count=0,
        )


@dataclass(frozen=True, slots=True)
class DeploymentChange:
    service: str
    environment: str
    version: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        for field in ("service", "environment", "version"):
            object.__setattr__(
                self, field, _text(getattr(self, field), field=f"deployment {field}")
            )
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))


class DeploymentsCollector:
    def collect(
        self, request: EvidenceBuildRequest, changes: tuple[DeploymentChange, ...]
    ) -> NormalizedEvidence:
        _records(changes)
        payload: JsonValue = {
            "changes": [
                {
                    "environment": item.environment,
                    "occurred_at": item.occurred_at.isoformat(),
                    "service": item.service,
                    "version": item.version,
                }
                for item in changes
            ],
            "kind": "deployments",
        }
        return _collect(
            request,
            payload,
            source_type=EvidenceSourceType.DEPLOYMENT,
            tool_name="query_deployments",
            record_count=len(changes),
            complete_window=True,
            records_dropped=0,
            parser_warning_count=0,
        )


@dataclass(frozen=True, slots=True, order=True)
class TopologyEdge:
    source_service: str
    target_service: str
    relation: str

    def __post_init__(self) -> None:
        for field in ("source_service", "target_service", "relation"):
            object.__setattr__(self, field, _text(getattr(self, field), field=f"topology {field}"))
        if self.source_service == self.target_service:
            raise InvalidDomainValueError("collector topology self edges are not allowed")


class TopologyCollector:
    def collect(
        self, request: EvidenceBuildRequest, edges: tuple[TopologyEdge, ...]
    ) -> NormalizedEvidence:
        _records(edges)
        ordered = tuple(sorted(edges))
        if len(set(ordered)) != len(ordered):
            raise InvalidDomainValueError("collector topology edges must be unique")
        payload: JsonValue = {
            "edges": [
                {
                    "relation": edge.relation,
                    "source": edge.source_service,
                    "target": edge.target_service,
                }
                for edge in ordered
            ],
            "kind": "topology",
        }
        return _collect(
            request,
            payload,
            source_type=EvidenceSourceType.TOPOLOGY,
            tool_name="get_service_topology",
            record_count=len(edges),
            complete_window=True,
            records_dropped=0,
            parser_warning_count=0,
        )
