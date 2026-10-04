"""Deterministic trace critical-path and error summaries with raw references."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from .errors import InvalidDomainValueError
from .values import ArtifactId, as_utc

TRACE_SUMMARY_SCHEMA_VERSION: Final = "1.0.0"
MAX_TRACE_SPANS: Final = 1_000
_ERROR_STATUS: Final = "ERROR"


def _bounded_text(value: str, *, field: str, maximum: int = 256) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise InvalidDomainValueError(f"trace {field} must be bounded non-null text")
    return normalized


@dataclass(frozen=True, slots=True, order=True)
class TraceSpanReference:
    """Resolvable position and identity of one span in an immutable Artifact."""

    artifact_id: ArtifactId
    record_index: int
    trace_id: str
    span_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.record_index, int)
            or isinstance(self.record_index, bool)
            or not 0 <= self.record_index < MAX_TRACE_SPANS
        ):
            raise InvalidDomainValueError("trace Artifact record index is outside collector bounds")
        object.__setattr__(self, "trace_id", _bounded_text(self.trace_id, field="ID", maximum=128))
        object.__setattr__(
            self, "span_id", _bounded_text(self.span_id, field="span ID", maximum=128)
        )


@dataclass(frozen=True, slots=True)
class TraceSpanObservation:
    reference: TraceSpanReference
    parent_span_id: str | None
    service: str
    operation: str
    started_at: datetime
    ended_at: datetime
    status: str

    def __post_init__(self) -> None:
        if self.parent_span_id is not None:
            object.__setattr__(
                self,
                "parent_span_id",
                _bounded_text(self.parent_span_id, field="parent span ID", maximum=128),
            )
        object.__setattr__(self, "service", _bounded_text(self.service, field="service"))
        object.__setattr__(self, "operation", _bounded_text(self.operation, field="operation"))
        object.__setattr__(
            self, "status", _bounded_text(self.status, field="status", maximum=32).upper()
        )
        started_at = as_utc(self.started_at)
        ended_at = as_utc(self.ended_at)
        if ended_at < started_at:
            raise InvalidDomainValueError("trace span time range is reversed")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "ended_at", ended_at)

    @property
    def duration(self) -> timedelta:
        return self.ended_at - self.started_at

    @property
    def is_error(self) -> bool:
        return self.status == _ERROR_STATUS


@dataclass(frozen=True, slots=True)
class TracePathSegment:
    reference: TraceSpanReference
    parent_span_id: str | None
    service: str
    operation: str
    duration: timedelta
    status: str


@dataclass(frozen=True, slots=True)
class TraceSummary:
    trace_id: str
    started_at: datetime
    ended_at: datetime
    duration: timedelta
    span_count: int
    services: tuple[str, ...]
    root_span: TraceSpanReference
    critical_path: tuple[TracePathSegment, ...]
    critical_path_duration: timedelta
    error_spans: tuple[TracePathSegment, ...]
    error_count: int
    critical_path_has_error: bool
    source_artifact_ids: tuple[ArtifactId, ...]
    schema_version: str = TRACE_SUMMARY_SCHEMA_VERSION


def _segment(span: TraceSpanObservation) -> TracePathSegment:
    return TracePathSegment(
        reference=span.reference,
        parent_span_id=span.parent_span_id,
        service=span.service,
        operation=span.operation,
        duration=span.duration,
        status=span.status,
    )


def summarize_trace(spans: tuple[TraceSpanObservation, ...]) -> TraceSummary:
    """Validate one trace tree and return its longest cumulative root-to-leaf path."""
    if not spans or len(spans) > MAX_TRACE_SPANS:
        raise InvalidDomainValueError("trace span count is outside bounds")

    trace_ids = {span.reference.trace_id for span in spans}
    if len(trace_ids) != 1:
        raise InvalidDomainValueError("trace summary cannot mix trace IDs")

    by_id: dict[str, TraceSpanObservation] = {}
    raw_positions: set[tuple[ArtifactId, int]] = set()
    for span in spans:
        if span.reference.span_id in by_id:
            raise InvalidDomainValueError("trace span IDs must be unique")
        raw_position = (span.reference.artifact_id, span.reference.record_index)
        if raw_position in raw_positions:
            raise InvalidDomainValueError("trace Artifact record positions must be unique")
        by_id[span.reference.span_id] = span
        raw_positions.add(raw_position)

    roots = tuple(span for span in spans if span.parent_span_id is None)
    if len(roots) != 1:
        raise InvalidDomainValueError("trace must contain exactly one root span")
    root = roots[0]

    children: dict[str, list[TraceSpanObservation]] = {span_id: [] for span_id in by_id}
    for span in spans:
        parent_id = span.parent_span_id
        if parent_id is None:
            continue
        if parent_id == span.reference.span_id:
            raise InvalidDomainValueError("trace span cannot be its own parent")
        parent = by_id.get(parent_id)
        if parent is None:
            raise InvalidDomainValueError("trace parent span is missing")
        if span.started_at < parent.started_at or span.ended_at > parent.ended_at:
            raise InvalidDomainValueError("trace child span must be contained by its parent")
        children[parent_id].append(span)

    traversal: list[TraceSpanObservation] = []
    stack = [root]
    visited: set[str] = set()
    while stack:
        span = stack.pop()
        span_id = span.reference.span_id
        visited.add(span_id)
        traversal.append(span)
        stack.extend(
            sorted(children[span_id], key=lambda item: item.reference.span_id, reverse=True)
        )
    if len(visited) != len(spans):
        raise InvalidDomainValueError("trace hierarchy contains a disconnected cycle")

    best_paths: dict[str, tuple[timedelta, tuple[TraceSpanObservation, ...]]] = {}
    for span in reversed(traversal):
        child_paths = tuple(
            best_paths[item.reference.span_id] for item in children[span.reference.span_id]
        )
        if child_paths:
            child_duration, child_path = min(
                child_paths,
                key=lambda item: (-item[0], tuple(s.reference.span_id for s in item[1])),
            )
            best_paths[span.reference.span_id] = (
                span.duration + child_duration,
                (span, *child_path),
            )
        else:
            best_paths[span.reference.span_id] = (span.duration, (span,))

    critical_duration, critical_spans = best_paths[root.reference.span_id]
    error_spans = tuple(
        sorted(
            (span for span in spans if span.is_error),
            key=lambda item: (item.started_at, item.reference),
        )
    )
    return TraceSummary(
        trace_id=next(iter(trace_ids)),
        started_at=root.started_at,
        ended_at=root.ended_at,
        duration=root.duration,
        span_count=len(spans),
        services=tuple(sorted({span.service for span in spans})),
        root_span=root.reference,
        critical_path=tuple(_segment(span) for span in critical_spans),
        critical_path_duration=critical_duration,
        error_spans=tuple(_segment(span) for span in error_spans),
        error_count=len(error_spans),
        critical_path_has_error=any(span.is_error for span in critical_spans),
        source_artifact_ids=tuple(
            sorted({span.reference.artifact_id for span in spans}, key=lambda item: item.value)
        ),
    )
