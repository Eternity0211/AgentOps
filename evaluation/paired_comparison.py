"""Deterministic paired effect-size scoring for evaluation-only artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictComparisonModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MetricKind(StrEnum):
    BINARY = "BINARY"
    CONTINUOUS = "CONTINUOUS"


class ImprovementDirection(StrEnum):
    HIGHER = "HIGHER"
    LOWER = "LOWER"


class ImprovementClaim(StrEnum):
    IMPROVED = "IMPROVED"
    NO_PROVEN_IMPROVEMENT = "NO_PROVEN_IMPROVEMENT"
    REGRESSED = "REGRESSED"


class PairedValue(StrictComparisonModel):
    pair_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    baseline: float = Field(allow_inf_nan=False)
    candidate: float = Field(allow_inf_nan=False)


class MetricComparisonRequest(StrictComparisonModel):
    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    kind: MetricKind
    direction: ImprovementDirection
    minimum_relevant_effect: float = Field(gt=0, allow_inf_nan=False)
    failure_policy: str = Field(min_length=1, max_length=500)
    pairs: tuple[PairedValue, ...] = Field(min_length=2, max_length=1_000_000)
    bootstrap_iterations: int = Field(default=5_000, ge=1_000, le=100_000)
    seed: int = Field(ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def valid_pairs(self) -> MetricComparisonRequest:
        identifiers = [item.pair_id for item in self.pairs]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("pair IDs must be unique")
        if self.kind is MetricKind.BINARY and any(
            value not in (0.0, 1.0)
            for pair in self.pairs
            for value in (pair.baseline, pair.candidate)
        ):
            raise ValueError("binary values must be zero or one")
        return self


class ComparisonSuiteRequest(StrictComparisonModel):
    schema_version: Literal["paired-comparison-request/1.0.0"]
    suite_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    confidence_level: float = Field(ge=0.95, le=0.95, allow_inf_nan=False)
    critical_safety_gate_passed: bool
    cost_latency_gate_passed: bool
    metrics: tuple[MetricComparisonRequest, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_metrics(self) -> ComparisonSuiteRequest:
        identifiers = [item.metric_id for item in self.metrics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("metric IDs must be unique")
        return self


class ConfidenceInterval(StrictComparisonModel):
    lower: float
    upper: float


class EffectEstimate(StrictComparisonModel):
    statistic: Literal["rate", "median", "p95"]
    baseline: float
    candidate: float
    absolute_delta: float
    relative_delta: float | None
    beneficial_delta: float
    absolute_delta_interval: ConfidenceInterval
    beneficial_delta_interval: ConfidenceInterval


class PairedTest(StrictComparisonModel):
    method: Literal["exact_mcnemar", "exact_sign"]
    candidate_better: int = Field(ge=0)
    baseline_better: int = Field(ge=0)
    ties: int = Field(ge=0)
    raw_p_value: float = Field(ge=0, le=1)
    holm_adjusted_p_value: float = Field(ge=0, le=1)


class MetricComparisonResult(StrictComparisonModel):
    metric_id: str
    kind: MetricKind
    direction: ImprovementDirection
    pair_count: int = Field(ge=2)
    failure_policy: str
    minimum_relevant_effect: float
    estimates: tuple[EffectEstimate, ...]
    paired_test: PairedTest
    claim: ImprovementClaim


class ComparisonSuiteResult(StrictComparisonModel):
    schema_version: Literal["paired-comparison-result/1.0.0"]
    suite_id: str
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confidence_level: float = Field(ge=0.95, le=0.95, allow_inf_nan=False)
    critical_safety_gate_passed: bool
    cost_latency_gate_passed: bool
    multiple_comparison_method: Literal["holm"]
    metrics: tuple[MetricComparisonResult, ...]


def _canonical_bytes(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    left = math.floor(position)
    right = math.ceil(position)
    if left == right:
        return ordered[left]
    weight = position - left
    return ordered[left] * (1 - weight) + ordered[right] * weight


def _p95(values: list[float]) -> float:
    return values[max(0, math.ceil(0.95 * len(values)) - 1)] if values == sorted(values) else _p95(
        sorted(values)
    )


def _exact_two_sided_binomial(successes: int, failures: int) -> float:
    trials = successes + failures
    if trials == 0:
        return 1.0
    observed = min(successes, failures)
    tail = float(sum(math.comb(trials, value) for value in range(observed + 1))) / float(
        2**trials
    )
    return min(1.0, 2 * tail)


def _relative_delta(baseline: float, delta: float) -> float | None:
    return None if baseline == 0 else delta / abs(baseline)


def _beneficial(value: float, direction: ImprovementDirection) -> float:
    return value if direction is ImprovementDirection.HIGHER else -value


def _estimate(
    statistic: Literal["rate", "median", "p95"],
    baseline: float,
    candidate: float,
    deltas: list[float],
    direction: ImprovementDirection,
) -> EffectEstimate:
    delta = candidate - baseline
    interval = ConfidenceInterval(
        lower=_percentile(deltas, 0.025), upper=_percentile(deltas, 0.975)
    )
    beneficial_interval = (
        interval
        if direction is ImprovementDirection.HIGHER
        else ConfidenceInterval(lower=-interval.upper, upper=-interval.lower)
    )
    return EffectEstimate(
        statistic=statistic,
        baseline=baseline,
        candidate=candidate,
        absolute_delta=delta,
        relative_delta=_relative_delta(baseline, delta),
        beneficial_delta=_beneficial(delta, direction),
        absolute_delta_interval=interval,
        beneficial_delta_interval=beneficial_interval,
    )


def _bootstrap_deltas(
    request: MetricComparisonRequest,
    statistic: Literal["rate", "median", "p95"],
) -> list[float]:
    rng = random.Random(request.seed + {"rate": 0, "median": 1, "p95": 2}[statistic])
    count = len(request.pairs)
    result = []
    for _ in range(request.bootstrap_iterations):
        sample = [request.pairs[rng.randrange(count)] for _ in range(count)]
        baseline = [item.baseline for item in sample]
        candidate = [item.candidate for item in sample]
        if statistic == "rate":
            result.append(statistics.fmean(candidate) - statistics.fmean(baseline))
        elif statistic == "median":
            result.append(statistics.median(candidate) - statistics.median(baseline))
        else:
            result.append(_p95(candidate) - _p95(baseline))
    return result


def _raw_metric(request: MetricComparisonRequest) -> tuple[tuple[EffectEstimate, ...], PairedTest]:
    baseline = [item.baseline for item in request.pairs]
    candidate = [item.candidate for item in request.pairs]
    estimates: tuple[EffectEstimate, ...]
    if request.kind is MetricKind.BINARY:
        estimates = (
            _estimate(
                "rate",
                statistics.fmean(baseline),
                statistics.fmean(candidate),
                _bootstrap_deltas(request, "rate"),
                request.direction,
            ),
        )
        method: Literal["exact_mcnemar", "exact_sign"] = "exact_mcnemar"
    else:
        estimates = (
            _estimate(
                "median",
                statistics.median(baseline),
                statistics.median(candidate),
                _bootstrap_deltas(request, "median"),
                request.direction,
            ),
            _estimate(
                "p95",
                _p95(baseline),
                _p95(candidate),
                _bootstrap_deltas(request, "p95"),
                request.direction,
            ),
        )
        method = "exact_sign"
    improvements = sum(
        _beneficial(item.candidate - item.baseline, request.direction) > 0
        for item in request.pairs
    )
    regressions = sum(
        _beneficial(item.candidate - item.baseline, request.direction) < 0
        for item in request.pairs
    )
    paired_test = PairedTest(
        method=method,
        candidate_better=improvements,
        baseline_better=regressions,
        ties=len(request.pairs) - improvements - regressions,
        raw_p_value=_exact_two_sided_binomial(improvements, regressions),
        holm_adjusted_p_value=1.0,
    )
    return estimates, paired_test


def _holm_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    adjusted = [1.0] * count
    previous = 0.0
    for rank, index in enumerate(sorted(range(count), key=p_values.__getitem__)):
        value = min(1.0, (count - rank) * p_values[index])
        previous = max(previous, value)
        adjusted[index] = previous
    return adjusted


def score_suite(request: ComparisonSuiteRequest) -> ComparisonSuiteResult:
    raw = [_raw_metric(metric) for metric in request.metrics]
    adjusted = _holm_adjust([item[1].raw_p_value for item in raw])
    results = []
    for metric, (estimates, paired_test), adjusted_p in zip(
        request.metrics, raw, adjusted, strict=True
    ):
        primary = estimates[0]
        if primary.beneficial_delta_interval.upper < 0:
            claim = ImprovementClaim.REGRESSED
        elif (
            primary.beneficial_delta_interval.lower > 0
            and primary.beneficial_delta >= metric.minimum_relevant_effect
            and adjusted_p < 0.05
            and request.critical_safety_gate_passed
            and request.cost_latency_gate_passed
        ):
            claim = ImprovementClaim.IMPROVED
        else:
            claim = ImprovementClaim.NO_PROVEN_IMPROVEMENT
        results.append(
            MetricComparisonResult(
                metric_id=metric.metric_id,
                kind=metric.kind,
                direction=metric.direction,
                pair_count=len(metric.pairs),
                failure_policy=metric.failure_policy,
                minimum_relevant_effect=metric.minimum_relevant_effect,
                estimates=estimates,
                paired_test=paired_test.model_copy(
                    update={"holm_adjusted_p_value": adjusted_p}
                ),
                claim=claim,
            )
        )
    return ComparisonSuiteResult(
        schema_version="paired-comparison-result/1.0.0",
        suite_id=request.suite_id,
        request_sha256=hashlib.sha256(_canonical_bytes(request)).hexdigest(),
        confidence_level=request.confidence_level,
        critical_safety_gate_passed=request.critical_safety_gate_passed,
        cost_latency_gate_passed=request.cost_latency_gate_passed,
        multiple_comparison_method="holm",
        metrics=tuple(results),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("comparison output already exists")
    request = ComparisonSuiteRequest.model_validate_json(args.request.read_bytes())
    result = score_suite(request)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
