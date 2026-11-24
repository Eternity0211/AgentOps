"""Label-free bounded telemetry features for RCAEval service localization."""

from __future__ import annotations

import math
from collections import Counter
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from evaluation.rcaeval_contract import (
    Modality,
    ReadOnlyTelemetryAdapter,
    TelemetryQuery,
    TelemetryResult,
)


class FeatureArm(StrEnum):
    BASELINE = "BASELINE"
    CANDIDATE = "CANDIDATE"


class StrictFeatureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ServiceFeature(StrictFeatureModel):
    service: str
    metric_after_mean: float | None
    metric_delta: float | None
    log_after_count: int = Field(ge=0)
    log_delta: int | None
    trace_after_count: int = Field(ge=0)
    trace_delta: int | None
    error_after_count: int = Field(ge=0)
    error_delta: int | None
    duration_after_mean: float | None
    duration_delta: float | None


class LocalizationContext(StrictFeatureModel):
    schema_version: str = "rcaeval-localization-context/1.0.0"
    case_id: str
    arm: FeatureArm
    candidate_services: tuple[str, ...]
    features: tuple[ServiceFeature, ...]
    missing_modalities: tuple[Modality, ...]
    truncated_queries: int = Field(ge=0)
    tool_calls: int = Field(ge=0, le=24)


def _normalized(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _service_for(value: object, candidates: tuple[str, ...]) -> str | None:
    normalized = _normalized(value)
    matches = [item for item in candidates if _normalized(item) in normalized]
    return max(matches, key=len) if matches else None


def _mean(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    return None if not finite else sum(finite) / len(finite)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _difference(after: float | None, before: float | None) -> float | None:
    return None if after is None or before is None else after - before


def _select_metric_columns(columns: tuple[str, ...], service: str) -> tuple[str, ...]:
    priority = ("error", "latency", "duration", "cpu", "memory", "network", "request")
    candidates = [
        column
        for column in columns
        if column != "time" and _normalized(service) in _normalized(column)
    ]
    return tuple(
        sorted(
            candidates,
            key=lambda column: (
                next(
                    (index for index, token in enumerate(priority) if token in column.lower()),
                    len(priority),
                ),
                column,
            ),
        )[:6]
    )


def _query(
    adapter: ReadOnlyTelemetryAdapter,
    modality: Modality,
    columns: tuple[str, ...],
    start: int,
    end: int,
) -> TelemetryResult | None:
    if not columns or end < start:
        return None
    return adapter.query(
        TelemetryQuery(
            modality=modality,
            columns=columns,
            start_unix_s=start,
            end_unix_s=end,
            limit=200,
        )
    )


def _metric_means(result: TelemetryResult | None, columns: tuple[str, ...]) -> list[float]:
    if result is None:
        return []
    means = []
    for column in columns:
        value = _mean(
            [number for row in result.rows if (number := _number(row.get(column))) is not None]
        )
        if value is not None:
            means.append(value)
    return means


def _row_counts(
    result: TelemetryResult | None,
    service_column: str,
    candidates: tuple[str, ...],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    if result is not None:
        for row in result.rows:
            service = _service_for(row.get(service_column, ""), candidates)
            if service is not None:
                counts[service] += 1
    return counts


def _trace_stats(
    result: TelemetryResult | None,
    candidates: tuple[str, ...],
    *,
    duration_column: str | None,
    status_column: str | None,
) -> tuple[Counter[str], Counter[str], dict[str, float | None]]:
    counts: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    durations: dict[str, list[float]] = {service: [] for service in candidates}
    if result is not None:
        for row in result.rows:
            service = _service_for(row.get("serviceName", ""), candidates)
            if service is None:
                continue
            counts[service] += 1
            if status_column is not None:
                status = str(row.get(status_column, "")).lower()
                if "error" in status or status in {"2", "500", "503"}:
                    errors[service] += 1
            if duration_column is not None:
                duration = _number(row.get(duration_column))
                if duration is not None:
                    durations[service].append(duration)
    return counts, errors, {service: _mean(values) for service, values in durations.items()}


def build_localization_context(task_dir: Path, arm: FeatureArm) -> LocalizationContext:
    """Build bounded aggregate features; evaluator answers are never accepted or read."""
    adapter = ReadOnlyTelemetryAdapter(task_dir)
    task = adapter.task
    before = (task.observation_start_unix_s, task.injection_time_unix_s - 1)
    after = (task.injection_time_unix_s, task.observation_end_unix_s)
    queries: list[TelemetryResult] = []
    metric_values: dict[str, tuple[float | None, float | None]] = {}
    metric_schema = adapter.columns(Modality.METRICS)
    for service in task.candidate_services:
        columns = _select_metric_columns(metric_schema, service)
        before_result = _query(adapter, Modality.METRICS, columns, *before)
        after_result = _query(adapter, Modality.METRICS, columns, *after)
        queries.extend(item for item in (before_result, after_result) if item is not None)
        metric_values[service] = (
            _mean(_metric_means(before_result, columns)),
            _mean(_metric_means(after_result, columns)),
        )

    log_before = log_after = None
    log_columns = adapter.columns(Modality.LOGS)
    if log_columns:
        service_column = "container_name" if "container_name" in log_columns else "serviceName"
        log_selected = (service_column,)
        log_before = _query(adapter, Modality.LOGS, log_selected, *before)
        log_after = _query(adapter, Modality.LOGS, log_selected, *after)
        queries.extend(item for item in (log_before, log_after) if item is not None)
        log_before_counts = _row_counts(log_before, service_column, task.candidate_services)
        log_after_counts = _row_counts(log_after, service_column, task.candidate_services)
    else:
        log_before_counts = Counter()
        log_after_counts = Counter()

    trace_before = trace_after = None
    trace_columns = adapter.columns(Modality.TRACES)
    duration_column = next(
        (name for name in ("duration", "durationMillis") if name in trace_columns), None
    )
    status_column = next((name for name in ("statusCode", "status") if name in trace_columns), None)
    if trace_columns and "serviceName" in trace_columns:
        trace_selected = tuple(
            name for name in ("serviceName", duration_column, status_column) if name is not None
        )
        trace_before = _query(adapter, Modality.TRACES, trace_selected, *before)
        trace_after = _query(adapter, Modality.TRACES, trace_selected, *after)
        queries.extend(item for item in (trace_before, trace_after) if item is not None)
    before_counts, before_errors, before_durations = _trace_stats(
        trace_before,
        task.candidate_services,
        duration_column=duration_column,
        status_column=status_column,
    )
    after_counts, after_errors, after_durations = _trace_stats(
        trace_after,
        task.candidate_services,
        duration_column=duration_column,
        status_column=status_column,
    )
    include_delta = arm is FeatureArm.CANDIDATE
    features = []
    for service in task.candidate_services:
        metric_before, metric_after = metric_values[service]
        features.append(
            ServiceFeature(
                service=service,
                metric_after_mean=metric_after,
                metric_delta=_difference(metric_after, metric_before) if include_delta else None,
                log_after_count=log_after_counts[service],
                log_delta=(log_after_counts[service] - log_before_counts[service])
                if include_delta
                else None,
                trace_after_count=after_counts[service],
                trace_delta=(after_counts[service] - before_counts[service])
                if include_delta
                else None,
                error_after_count=after_errors[service],
                error_delta=(after_errors[service] - before_errors[service])
                if include_delta
                else None,
                duration_after_mean=after_durations[service],
                duration_delta=_difference(after_durations[service], before_durations[service])
                if include_delta
                else None,
            )
        )
    available = {item.modality for item in task.files if item.available}
    return LocalizationContext(
        case_id=task.case_id,
        arm=arm,
        candidate_services=task.candidate_services,
        features=tuple(features),
        missing_modalities=tuple(item for item in Modality if item not in available),
        truncated_queries=sum(item.truncated for item in queries),
        tool_calls=len(queries),
    )
