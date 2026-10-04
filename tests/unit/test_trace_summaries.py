"""Trace critical-path, error, and raw provenance summary tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from agentops_incident_commander.domain import (
    MAX_TRACE_SPANS,
    TRACE_SUMMARY_SCHEMA_VERSION,
    ArtifactId,
    InvalidDomainValueError,
    TraceSpanObservation,
    TraceSpanReference,
    summarize_trace,
)

NOW = datetime(2026, 10, 4, 8, tzinfo=UTC)


def span(
    span_id: str,
    *,
    parent_span_id: str | None = None,
    start_ms: int = 0,
    end_ms: int = 100,
    status: str = "OK",
    service: str = "gateway",
    operation: str = "request",
    trace_id: str = "trace-1",
    artifact_id: str = "artifact-trace",
    record_index: int = 0,
) -> TraceSpanObservation:
    return TraceSpanObservation(
        TraceSpanReference(ArtifactId(artifact_id), record_index, trace_id, span_id),
        parent_span_id,
        service,
        operation,
        NOW + timedelta(milliseconds=start_ms),
        NOW + timedelta(milliseconds=end_ms),
        status,
    )


def test_trace_summary_extracts_longest_path_errors_and_raw_references() -> None:
    spans = (
        span("root", end_ms=100, record_index=0),
        span(
            "slow",
            parent_span_id="root",
            end_ms=80,
            status=" error ",
            service=" order ",
            operation=" create ",
            record_index=1,
        ),
        span(
            "database",
            parent_span_id="slow",
            end_ms=70,
            service="postgres",
            operation="query",
            artifact_id="artifact-db",
            record_index=0,
        ),
        span(
            "later",
            parent_span_id="root",
            start_ms=10,
            end_ms=100,
            status="ERROR",
            service="payment",
            operation="charge",
            record_index=2,
        ),
    )

    result = summarize_trace(spans)

    assert result.trace_id == "trace-1"
    assert result.started_at == NOW
    assert result.ended_at == NOW + timedelta(milliseconds=100)
    assert result.duration == timedelta(milliseconds=100)
    assert result.span_count == 4
    assert result.services == ("gateway", "order", "payment", "postgres")
    assert result.root_span == spans[0].reference
    assert tuple(item.reference.span_id for item in result.critical_path) == (
        "root",
        "slow",
        "database",
    )
    assert result.critical_path_duration == timedelta(milliseconds=250)
    assert tuple(item.reference.span_id for item in result.error_spans) == ("slow", "later")
    assert result.error_count == 2
    assert result.critical_path_has_error
    assert result.source_artifact_ids == (
        ArtifactId("artifact-db"),
        ArtifactId("artifact-trace"),
    )
    assert result.schema_version == TRACE_SUMMARY_SCHEMA_VERSION
    slow = result.critical_path[1]
    assert slow.parent_span_id == "root"
    assert slow.service == "order"
    assert slow.operation == "create"
    assert slow.duration == timedelta(milliseconds=80)
    assert slow.status == "ERROR"


def test_equal_critical_paths_use_stable_span_id_tiebreaker() -> None:
    result = summarize_trace(
        (
            span("root", record_index=0),
            span("z-child", parent_span_id="root", end_ms=50, record_index=1),
            span("a-child", parent_span_id="root", end_ms=50, record_index=2),
        )
    )
    assert tuple(item.reference.span_id for item in result.critical_path) == (
        "root",
        "a-child",
    )
    assert result.error_spans == ()
    assert result.error_count == 0
    assert not result.critical_path_has_error


def test_span_normalizes_timezone_and_exposes_duration() -> None:
    east = timezone(timedelta(hours=8))
    value = TraceSpanObservation(
        TraceSpanReference(ArtifactId("artifact"), 0, " trace ", " span "),
        None,
        " service ",
        " operation ",
        NOW.astimezone(east),
        (NOW + timedelta(seconds=1)).astimezone(east),
        " ok ",
    )
    assert value.reference.trace_id == "trace"
    assert value.reference.span_id == "span"
    assert value.started_at == NOW
    assert value.ended_at == NOW + timedelta(seconds=1)
    assert value.duration == timedelta(seconds=1)
    assert value.service == "service"
    assert value.operation == "operation"
    assert value.status == "OK"
    assert not value.is_error


@pytest.mark.parametrize("record_index", [-1, MAX_TRACE_SPANS, True, 1.5])
def test_trace_reference_rejects_out_of_bounds_record_index(record_index: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="outside"):
        TraceSpanReference(ArtifactId("artifact"), record_index, "trace", "span")


@pytest.mark.parametrize(
    ("trace_id", "span_id", "field"),
    [
        ("", "span", "ID"),
        ("x" * 129, "span", "ID"),
        ("bad\x00trace", "span", "ID"),
        ("trace", "", "span ID"),
        ("trace", "x" * 129, "span ID"),
        ("trace", "bad\x00span", "span ID"),
    ],
)
def test_trace_reference_text_is_bounded(trace_id: str, span_id: str, field: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=field):
        TraceSpanReference(ArtifactId("artifact"), 0, trace_id, span_id)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"parent_span_id": ""}, "parent span ID"),
        ({"parent_span_id": "x" * 129}, "parent span ID"),
        ({"parent_span_id": "bad\x00parent"}, "parent span ID"),
        ({"service": ""}, "service"),
        ({"service": "x" * 257}, "service"),
        ({"service": "bad\x00service"}, "service"),
        ({"operation": ""}, "operation"),
        ({"operation": "x" * 257}, "operation"),
        ({"operation": "bad\x00operation"}, "operation"),
        ({"status": ""}, "status"),
        ({"status": "x" * 33}, "status"),
        ({"status": "bad\x00status"}, "status"),
    ],
)
def test_trace_span_text_is_bounded(overrides: dict[str, Any], field: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=field):
        span("span", **overrides)


def test_trace_span_rejects_reversed_time() -> None:
    with pytest.raises(InvalidDomainValueError, match="reversed"):
        span("span", start_ms=2, end_ms=1)


def test_trace_summary_rejects_empty_and_excess_span_sets() -> None:
    with pytest.raises(InvalidDomainValueError, match="span count"):
        summarize_trace(())
    spans = tuple(
        span(
            f"span-{index}",
            artifact_id=f"artifact-{index // MAX_TRACE_SPANS}",
            record_index=index % MAX_TRACE_SPANS,
        )
        for index in range(MAX_TRACE_SPANS + 1)
    )
    with pytest.raises(InvalidDomainValueError, match="span count"):
        summarize_trace(spans)


def test_trace_summary_rejects_mixed_traces() -> None:
    with pytest.raises(InvalidDomainValueError, match="mix trace"):
        summarize_trace(
            (
                span("one", trace_id="trace-1", record_index=0),
                span("two", trace_id="trace-2", record_index=1),
            )
        )


def test_trace_summary_rejects_duplicate_span_ids_and_raw_positions() -> None:
    with pytest.raises(InvalidDomainValueError, match="span IDs"):
        summarize_trace((span("same", record_index=0), span("same", record_index=1)))
    with pytest.raises(InvalidDomainValueError, match="record positions"):
        summarize_trace((span("one", record_index=0), span("two", record_index=0)))


def test_trace_summary_requires_exactly_one_root() -> None:
    with pytest.raises(InvalidDomainValueError, match="exactly one root"):
        summarize_trace((span("one", record_index=0), span("two", record_index=1)))
    with pytest.raises(InvalidDomainValueError, match="exactly one root"):
        summarize_trace(
            (
                span("one", parent_span_id="two", record_index=0),
                span("two", parent_span_id="one", record_index=1),
            )
        )


def test_trace_summary_rejects_self_or_missing_parent() -> None:
    root = span("root", record_index=0)
    with pytest.raises(InvalidDomainValueError, match="own parent"):
        summarize_trace((root, span("self", parent_span_id="self", record_index=1)))
    with pytest.raises(InvalidDomainValueError, match="missing"):
        summarize_trace((root, span("child", parent_span_id="absent", record_index=1)))


@pytest.mark.parametrize(("start_ms", "end_ms"), [(-1, 50), (10, 101)])
def test_trace_summary_requires_child_inside_parent(start_ms: int, end_ms: int) -> None:
    with pytest.raises(InvalidDomainValueError, match="contained"):
        summarize_trace(
            (
                span("root", record_index=0),
                span(
                    "child",
                    parent_span_id="root",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    record_index=1,
                ),
            )
        )


def test_trace_summary_rejects_disconnected_cycle() -> None:
    with pytest.raises(InvalidDomainValueError, match="disconnected cycle"):
        summarize_trace(
            (
                span("root", record_index=0),
                span("cycle-a", parent_span_id="cycle-b", record_index=1),
                span("cycle-b", parent_span_id="cycle-a", record_index=2),
            )
        )
