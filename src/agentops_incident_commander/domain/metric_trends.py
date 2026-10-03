"""Deterministic metric trend summaries with resolvable Artifact provenance."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from .errors import InvalidDomainValueError
from .values import ArtifactId, as_utc

METRIC_TREND_SCHEMA_VERSION: Final = "1.0.0"
MAX_METRIC_POINTS: Final = 1_000
MAX_METRIC_LABELS: Final = 32


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise InvalidDomainValueError(f"metric {field} must be bounded non-null text")
    return normalized


class MetricTrendDirection(StrEnum):
    """Direction of a current interval relative to its explicit baseline."""

    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"


@dataclass(frozen=True, slots=True)
class MetricPoint:
    observed_at: datetime
    value: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))
        if not math.isfinite(self.value):
            raise InvalidDomainValueError("metric point value must be finite")


@dataclass(frozen=True, slots=True)
class MetricSeries:
    """One bounded, ordered metric interval stored in an immutable Artifact."""

    metric: str
    labels: tuple[tuple[str, str], ...]
    artifact_id: ArtifactId
    sampling_interval: timedelta
    points: tuple[MetricPoint, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric", _bounded_text(self.metric, field="name", maximum=256))
        if self.sampling_interval <= timedelta(0):
            raise InvalidDomainValueError("metric sampling interval must be positive")
        if not self.points or len(self.points) > MAX_METRIC_POINTS:
            raise InvalidDomainValueError("metric series point count is outside bounds")
        if len(self.labels) > MAX_METRIC_LABELS:
            raise InvalidDomainValueError("metric label count exceeds limit")

        normalized_labels = tuple(
            sorted(
                (
                    _bounded_text(key, field="label key", maximum=128),
                    _bounded_text(value, field="label value", maximum=256),
                )
                for key, value in self.labels
            )
        )
        if len({key for key, _ in normalized_labels}) != len(normalized_labels):
            raise InvalidDomainValueError("metric label keys must be unique")
        object.__setattr__(self, "labels", normalized_labels)

        previous: datetime | None = None
        for point in self.points:
            if previous is not None:
                gap = point.observed_at - previous
                if gap <= timedelta(0):
                    raise InvalidDomainValueError("metric points must be strictly time ordered")
                if gap % self.sampling_interval != timedelta(0):
                    raise InvalidDomainValueError(
                        "metric point gaps must align with the sampling interval"
                    )
            previous = point.observed_at

    @property
    def interval_start(self) -> datetime:
        return self.points[0].observed_at

    @property
    def interval_end(self) -> datetime:
        return self.points[-1].observed_at


@dataclass(frozen=True, slots=True)
class MetricTrendSummary:
    metric: str
    labels: tuple[tuple[str, str], ...]
    interval_start: datetime
    interval_end: datetime
    baseline_start: datetime
    baseline_end: datetime
    sampling_interval: timedelta
    source_artifact_id: ArtifactId
    baseline_artifact_id: ArtifactId
    point_count: int
    baseline_point_count: int
    first_value: float
    last_value: float
    minimum: float
    maximum: float
    mean: float
    baseline_mean: float
    absolute_change: float
    percent_change: float | None
    direction: MetricTrendDirection
    stable_relative_threshold: float
    schema_version: str = METRIC_TREND_SCHEMA_VERSION


def summarize_metric_trend(
    current: MetricSeries,
    baseline: MetricSeries,
    *,
    stable_relative_threshold: float = 0.05,
) -> MetricTrendSummary:
    """Compare a metric interval with a non-overlapping baseline without hiding sources."""
    if current.metric != baseline.metric or current.labels != baseline.labels:
        raise InvalidDomainValueError(
            "metric trend series must describe the same metric and labels"
        )
    if current.sampling_interval != baseline.sampling_interval:
        raise InvalidDomainValueError("metric trend sampling intervals must match")
    if baseline.interval_end >= current.interval_start:
        raise InvalidDomainValueError("metric baseline must end before the current interval")
    if not math.isfinite(stable_relative_threshold) or not 0 <= stable_relative_threshold <= 1:
        raise InvalidDomainValueError(
            "metric stable threshold must be finite and between zero and one"
        )

    values = tuple(point.value for point in current.points)
    baseline_values = tuple(point.value for point in baseline.points)
    mean = math.fsum(values) / len(values)
    baseline_mean = math.fsum(baseline_values) / len(baseline_values)
    absolute_change = mean - baseline_mean
    percent_change = None if baseline_mean == 0 else (absolute_change / abs(baseline_mean)) * 100

    if baseline_mean == 0:
        direction = (
            MetricTrendDirection.STABLE
            if absolute_change == 0
            else MetricTrendDirection.INCREASING
            if absolute_change > 0
            else MetricTrendDirection.DECREASING
        )
    else:
        relative_change = absolute_change / abs(baseline_mean)
        direction = (
            MetricTrendDirection.STABLE
            if abs(relative_change) <= stable_relative_threshold
            else MetricTrendDirection.INCREASING
            if relative_change > 0
            else MetricTrendDirection.DECREASING
        )

    return MetricTrendSummary(
        metric=current.metric,
        labels=current.labels,
        interval_start=current.interval_start,
        interval_end=current.interval_end,
        baseline_start=baseline.interval_start,
        baseline_end=baseline.interval_end,
        sampling_interval=current.sampling_interval,
        source_artifact_id=current.artifact_id,
        baseline_artifact_id=baseline.artifact_id,
        point_count=len(values),
        baseline_point_count=len(baseline_values),
        first_value=values[0],
        last_value=values[-1],
        minimum=min(values),
        maximum=max(values),
        mean=mean,
        baseline_mean=baseline_mean,
        absolute_change=absolute_change,
        percent_change=percent_change,
        direction=direction,
        stable_relative_threshold=stable_relative_threshold,
    )
