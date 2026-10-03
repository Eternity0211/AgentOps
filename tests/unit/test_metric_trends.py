"""Deterministic metric trend summary tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from agentops_incident_commander.domain import (
    MAX_METRIC_LABELS,
    MAX_METRIC_POINTS,
    METRIC_TREND_SCHEMA_VERSION,
    ArtifactId,
    InvalidDomainValueError,
    MetricPoint,
    MetricSeries,
    MetricTrendDirection,
    summarize_metric_trend,
)

NOW = datetime(2026, 10, 3, 8, tzinfo=UTC)
INTERVAL = timedelta(minutes=1)


def series(
    values: tuple[float, ...],
    *,
    start: datetime,
    metric: str = "http.server.duration.p95",
    labels: tuple[tuple[str, str], ...] = (("service", "order"),),
    artifact_id: str = "artifact-current",
    sampling_interval: timedelta = INTERVAL,
) -> MetricSeries:
    return MetricSeries(
        metric,
        labels,
        ArtifactId(artifact_id),
        sampling_interval,
        tuple(
            MetricPoint(start + sampling_interval * index, value)
            for index, value in enumerate(values)
        ),
    )


def baseline(
    values: tuple[float, ...] = (10.0, 12.0),
    **overrides: Any,
) -> MetricSeries:
    return series(
        values,
        start=overrides.pop("start", NOW - timedelta(minutes=3)),
        artifact_id=overrides.pop("artifact_id", "artifact-baseline"),
        **overrides,
    )


def test_summary_retains_statistics_intervals_and_artifact_sources() -> None:
    result = summarize_metric_trend(series((20.0, 24.0), start=NOW), baseline())

    assert result.metric == "http.server.duration.p95"
    assert result.labels == (("service", "order"),)
    assert result.interval_start == NOW
    assert result.interval_end == NOW + INTERVAL
    assert result.baseline_start == NOW - timedelta(minutes=3)
    assert result.baseline_end == NOW - timedelta(minutes=2)
    assert result.sampling_interval == INTERVAL
    assert result.source_artifact_id == ArtifactId("artifact-current")
    assert result.baseline_artifact_id == ArtifactId("artifact-baseline")
    assert result.point_count == result.baseline_point_count == 2
    assert result.first_value == 20.0
    assert result.last_value == 24.0
    assert result.minimum == 20.0
    assert result.maximum == 24.0
    assert result.mean == 22.0
    assert result.baseline_mean == 11.0
    assert result.absolute_change == 11.0
    assert result.percent_change == 100.0
    assert result.direction is MetricTrendDirection.INCREASING
    assert result.stable_relative_threshold == 0.05
    assert result.schema_version == METRIC_TREND_SCHEMA_VERSION


@pytest.mark.parametrize(
    ("values", "base_values", "threshold", "expected"),
    [
        ((9.5,), (10.0,), 0.05, MetricTrendDirection.STABLE),
        ((9.0,), (10.0,), 0.05, MetricTrendDirection.DECREASING),
        ((0.0,), (0.0,), 0.05, MetricTrendDirection.STABLE),
        ((1.0,), (0.0,), 0.05, MetricTrendDirection.INCREASING),
        ((-1.0,), (0.0,), 0.05, MetricTrendDirection.DECREASING),
        ((-9.0,), (-10.0,), 0.05, MetricTrendDirection.INCREASING),
    ],
)
def test_direction_is_relative_to_explicit_baseline(
    values: tuple[float, ...],
    base_values: tuple[float, ...],
    threshold: float,
    expected: MetricTrendDirection,
) -> None:
    result = summarize_metric_trend(
        series(values, start=NOW),
        baseline(base_values),
        stable_relative_threshold=threshold,
    )
    assert result.direction is expected
    assert (
        result.percent_change is None
        if base_values == (0.0,)
        else result.percent_change is not None
    )


def test_series_normalizes_utc_and_label_order() -> None:
    east = timezone(timedelta(hours=8))
    value = series(
        (1.0,),
        start=NOW.astimezone(east),
        labels=(("zone", "east"), ("service", "order")),
    )
    assert value.interval_start == NOW
    assert value.interval_end == NOW
    assert value.labels == (("service", "order"), ("zone", "east"))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_metric_points_reject_nonfinite_values(value: float) -> None:
    with pytest.raises(InvalidDomainValueError, match="finite"):
        MetricPoint(NOW, value)


@pytest.mark.parametrize("name", ["", "x" * 257, "bad\x00name"])
def test_metric_name_is_bounded(name: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="name"):
        series((1.0,), start=NOW, metric=name)


@pytest.mark.parametrize(
    "labels",
    [
        (("", "value"),),
        ((("x" * 129), "value"),),
        (("bad\x00key", "value"),),
        (("key", ""),),
        (("key", "x" * 257),),
        (("key", "bad\x00value"),),
    ],
)
def test_metric_labels_are_bounded(labels: tuple[tuple[str, str], ...]) -> None:
    with pytest.raises(InvalidDomainValueError, match="label"):
        series((1.0,), start=NOW, labels=labels)


def test_metric_labels_reject_duplicates_and_excess() -> None:
    with pytest.raises(InvalidDomainValueError, match="unique"):
        series((1.0,), start=NOW, labels=(("service", "one"), ("service", "two")))
    labels = tuple((f"label-{index}", "value") for index in range(MAX_METRIC_LABELS + 1))
    with pytest.raises(InvalidDomainValueError, match="label count"):
        series((1.0,), start=NOW, labels=labels)


def test_metric_series_rejects_empty_or_excess_points() -> None:
    with pytest.raises(InvalidDomainValueError, match="point count"):
        series((), start=NOW)
    points = tuple(
        MetricPoint(NOW + INTERVAL * index, 1.0) for index in range(MAX_METRIC_POINTS + 1)
    )
    with pytest.raises(InvalidDomainValueError, match="point count"):
        MetricSeries("metric", (), ArtifactId("artifact"), INTERVAL, points)


def test_metric_series_rejects_nonpositive_sampling_interval() -> None:
    point = MetricPoint(NOW, 1.0)
    for interval in (timedelta(0), timedelta(seconds=-1)):
        with pytest.raises(InvalidDomainValueError, match="sampling interval"):
            MetricSeries("metric", (), ArtifactId("artifact"), interval, (point,))


def test_metric_series_rejects_duplicate_unordered_and_misaligned_points() -> None:
    point = MetricPoint(NOW, 1.0)
    for later in (NOW, NOW - INTERVAL):
        with pytest.raises(InvalidDomainValueError, match="strictly"):
            MetricSeries(
                "metric",
                (),
                ArtifactId("artifact"),
                INTERVAL,
                (point, MetricPoint(later, 2.0)),
            )
    with pytest.raises(InvalidDomainValueError, match="align"):
        MetricSeries(
            "metric",
            (),
            ArtifactId("artifact"),
            INTERVAL,
            (point, MetricPoint(NOW + timedelta(seconds=90), 2.0)),
        )


def test_metric_series_allows_missing_aligned_samples() -> None:
    value = MetricSeries(
        "metric",
        (),
        ArtifactId("artifact"),
        INTERVAL,
        (MetricPoint(NOW, 1.0), MetricPoint(NOW + INTERVAL * 2, 2.0)),
    )
    assert value.interval_end == NOW + INTERVAL * 2


def test_summary_rejects_mixed_metric_or_label_series() -> None:
    current = series((1.0,), start=NOW)
    with pytest.raises(InvalidDomainValueError, match="same metric"):
        summarize_metric_trend(current, baseline(metric="other"))
    with pytest.raises(InvalidDomainValueError, match="same metric"):
        summarize_metric_trend(current, baseline(labels=(("service", "payment"),)))


def test_summary_rejects_mismatched_sampling_intervals() -> None:
    with pytest.raises(InvalidDomainValueError, match="sampling intervals"):
        summarize_metric_trend(
            series((1.0,), start=NOW),
            baseline(sampling_interval=timedelta(seconds=30)),
        )


def test_summary_rejects_overlapping_or_future_baseline() -> None:
    current = series((1.0,), start=NOW)
    for start in (NOW, NOW + INTERVAL):
        with pytest.raises(InvalidDomainValueError, match="end before"):
            summarize_metric_trend(current, baseline((1.0,), start=start))


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_summary_rejects_invalid_stable_threshold(threshold: float) -> None:
    with pytest.raises(InvalidDomainValueError, match="threshold"):
        summarize_metric_trend(
            series((1.0,), start=NOW),
            baseline((1.0,)),
            stable_relative_threshold=threshold,
        )
