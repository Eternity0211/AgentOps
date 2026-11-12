from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from evaluation.paired_comparison import (
    ComparisonSuiteRequest,
    ImprovementClaim,
    ImprovementDirection,
    MetricComparisonRequest,
    MetricKind,
    PairedValue,
    main,
    score_suite,
)
from pydantic import ValidationError


def metric(
    identifier: str,
    values: Sequence[tuple[float, float]],
    *,
    kind: MetricKind = MetricKind.BINARY,
    direction: ImprovementDirection = ImprovementDirection.HIGHER,
    minimum: float = 0.1,
    seed: int = 1,
) -> MetricComparisonRequest:
    return MetricComparisonRequest(
        metric_id=identifier,
        kind=kind,
        direction=direction,
        minimum_relevant_effect=minimum,
        failure_policy="Failed and aborted cases are encoded as zero success.",
        pairs=tuple(
            PairedValue(pair_id=f"pair-{index}", baseline=baseline, candidate=candidate)
            for index, (baseline, candidate) in enumerate(values)
        ),
        bootstrap_iterations=1_000,
        seed=seed,
    )


def suite(
    *metrics: MetricComparisonRequest, safety: bool = True, cost: bool = True
) -> ComparisonSuiteRequest:
    return ComparisonSuiteRequest(
        schema_version="paired-comparison-request/1.0.0",
        suite_id="suite-1",
        confidence_level=0.95,
        critical_safety_gate_passed=safety,
        cost_latency_gate_passed=cost,
        metrics=metrics,
    )


def test_binary_effect_mcnemar_interval_and_relative_delta() -> None:
    result = score_suite(suite(metric("top1", [(0, 1)] * 20)))
    item = result.metrics[0]
    estimate = item.estimates[0]

    assert estimate.baseline == 0
    assert estimate.candidate == 1
    assert estimate.absolute_delta == 1
    assert estimate.relative_delta is None
    assert estimate.absolute_delta_interval.lower == 1
    assert item.paired_test.candidate_better == 20
    assert item.paired_test.baseline_better == 0
    assert item.paired_test.raw_p_value < 0.00001
    assert item.claim is ImprovementClaim.IMPROVED


@pytest.mark.parametrize("safety,cost", [(False, True), (True, False)])
def test_improvement_claim_requires_safety_and_cost_gates(safety: bool, cost: bool) -> None:
    result = score_suite(suite(metric("top1", [(0, 1)] * 20), safety=safety, cost=cost))

    assert result.metrics[0].claim is ImprovementClaim.NO_PROVEN_IMPROVEMENT


def test_continuous_lower_is_better_reports_median_p95_and_sign_test() -> None:
    values = [(float(value), float(value - 10)) for value in range(20, 40)]
    request = metric(
        "latency",
        values,
        kind=MetricKind.CONTINUOUS,
        direction=ImprovementDirection.LOWER,
        minimum=5,
    )

    item = score_suite(suite(request)).metrics[0]

    assert [value.statistic for value in item.estimates] == ["median", "p95"]
    assert item.estimates[0].absolute_delta == -10
    assert item.estimates[0].beneficial_delta == 10
    assert item.paired_test.method == "exact_sign"
    assert item.claim is ImprovementClaim.IMPROVED


def test_holm_correction_and_unproven_small_sample_are_deterministic() -> None:
    first = metric("first", [(0, 1)] * 5 + [(1, 1)] * 3, seed=10)
    second = metric("second", [(0, 1)] * 5 + [(1, 1)] * 3, seed=20)

    left = score_suite(suite(first, second))
    right = score_suite(suite(first, second))

    assert left == right
    assert (
        left.metrics[0].paired_test.holm_adjusted_p_value
        >= left.metrics[0].paired_test.raw_p_value
    )
    assert all(item.claim is ImprovementClaim.NO_PROVEN_IMPROVEMENT for item in left.metrics)


def test_regression_is_reported_even_when_global_gates_fail() -> None:
    result = score_suite(suite(metric("safety", [(1, 0)] * 20), safety=False, cost=False))

    assert result.metrics[0].claim is ImprovementClaim.REGRESSED


def test_request_refuses_duplicate_pairs_nonbinary_values_and_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="pair IDs must be unique"):
        metric("bad", [(0, 1), (1, 0)]).model_copy(
            update={
                "pairs": (
                    PairedValue(pair_id="same", baseline=0, candidate=1),
                    PairedValue(pair_id="same", baseline=1, candidate=0),
                )
            }
        ).model_validate(
            metric("bad", [(0, 1), (1, 0)]).model_copy(
                update={
                    "pairs": (
                        PairedValue(pair_id="same", baseline=0, candidate=1),
                        PairedValue(pair_id="same", baseline=1, candidate=0),
                    )
                }
            ).model_dump()
        )

    value = metric("bad", [(0, 1), (1, 0)]).model_dump(mode="json")
    value["pairs"][0]["baseline"] = 0.5
    with pytest.raises(ValidationError, match="binary values must be zero or one"):
        MetricComparisonRequest.model_validate_json(json.dumps(value))
    value["pairs"][0]["baseline"] = 0
    value["unknown"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        MetricComparisonRequest.model_validate_json(json.dumps(value))


def test_cli_creates_once_and_binds_request_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_path = tmp_path / "request.json"
    output = tmp_path / "result.json"
    request_path.write_text(
        suite(metric("top1", [(0, 1)] * 20)).model_dump_json(), encoding="utf-8"
    )
    monkeypatch.setattr(
        "sys.argv",
        ["paired-comparison", "--request", str(request_path), "--output", str(output)],
    )

    main()
    stored = json.loads(output.read_text(encoding="utf-8"))
    assert stored["request_sha256"]
    with pytest.raises(FileExistsError, match="already exists"):
        main()


def test_committed_contract_fixture_scores_without_ground_truth() -> None:
    request = ComparisonSuiteRequest.model_validate_json(
        Path("evaluation/comparison/v1/example-request.json").read_bytes()
    )

    result = score_suite(request)

    assert result.suite_id == "contract-example"
    assert [item.metric_id for item in result.metrics] == [
        "safe-control-rate",
        "diagnosis-latency-ms",
    ]
    assert all(item.failure_policy for item in result.metrics)
