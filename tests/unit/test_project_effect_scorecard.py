from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

SCORECARD_PATH = Path("evaluation/scorecard/v1/scorecard.json")


def _load_scorecard() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(SCORECARD_PATH.read_text(encoding="utf-8")))


def test_scorecard_defines_product_outcomes_safety_and_engineering_support() -> None:
    scorecard = _load_scorecard()
    metrics = scorecard["metrics"]
    metric_ids = {metric["metric_id"] for metric in metrics}

    assert scorecard["schema_version"] == "project-effect-scorecard/1.0.0"
    assert {metric["tier"] for metric in metrics} == {
        "CORE_OUTCOME",
        "CRITICAL_SAFETY",
        "ENGINEERING_SUPPORT",
    }
    assert {
        "diagnosis_top1_rate",
        "time_to_correct_diagnosis",
        "active_operator_labor",
        "time_to_stable_recovery",
        "mttr",
        "correct_action_rate",
        "recurrence_rate",
        "input_tokens",
        "workflow_latency",
        "actual_cost_per_correct_diagnosis",
    } <= metric_ids


def test_every_metric_has_explicit_arms_and_measurement_boundaries() -> None:
    scorecard = _load_scorecard()
    for metric in scorecard["metrics"]:
        assert metric["direction"] in {"HIGHER", "LOWER"}
        assert metric["control_arm"].strip()
        assert metric["treatment_arm"].strip()
        assert metric["development_measurement"] in {
            "MEASURABLE_NOW",
            "PARTIAL_LAB_ONLY",
            "NOT_MEASURABLE_WITH_CURRENT_RUNS",
            "RATE_CARD_ESTIMATE_ONLY",
        }
        assert metric["formal_measurement"] in {
            "MEASURABLE_NOW",
            "BLOCKED_EXTERNAL_DATA",
        }
        assert metric["formal_requirement"].strip()


def test_current_evidence_never_turns_missing_measurement_into_zero() -> None:
    scorecard = _load_scorecard()
    by_id = {metric["metric_id"]: metric for metric in scorecard["metrics"]}

    for metric_id in {
        "time_to_correct_diagnosis",
        "active_operator_labor",
        "time_to_stable_recovery",
        "mttr",
        "correct_action_rate",
        "recurrence_rate",
        "actual_cost_per_correct_diagnosis",
    }:
        assert by_id[metric_id]["current_evidence"] is None

    assert scorecard["claim_policy"]["missing_measurements_are_never_zero"] is True
    assert scorecard["claim_policy"]["development_results_are_not_real_world_results"] is True


def test_critical_safety_list_resolves_to_zero_event_guardrails() -> None:
    scorecard = _load_scorecard()
    by_id = {metric["metric_id"]: metric for metric in scorecard["metrics"]}

    for metric_id in scorecard["critical_safety_metric_ids"]:
        metric = by_id[metric_id]
        assert metric["tier"] == "CRITICAL_SAFETY"
        assert metric["direction"] == "LOWER"
        evidence = metric["current_evidence"]
        assert evidence["control"] == 0
        assert evidence["treatment"] == 0
        assert evidence["disposition"] == "GUARDRAIL_PASSED"


def test_documented_measured_values_are_bound_to_existing_sources() -> None:
    scorecard = _load_scorecard()
    by_id = {metric["metric_id"]: metric for metric in scorecard["metrics"]}
    for metric in scorecard["metrics"]:
        evidence = metric["current_evidence"]
        if evidence is None:
            continue
        source = Path(evidence["source"])
        assert source.exists(), f"missing source for {metric['metric_id']}: {source}"

    structured_score = json.loads(
        Path("evaluation/results/structured-reliability/v7/run-001/analysis/score.json").read_text(
            encoding="utf-8"
        )
    )
    for metric_id, quality_key in {
        "diagnosis_top1_rate": "top1",
        "diagnosis_top3_rate": "top3",
    }.items():
        evidence = by_id[metric_id]["current_evidence"]
        for profile, scorecard_key in {
            "baseline-1.8": "control",
            "candidate-1.11": "treatment",
        }.items():
            modes = structured_score["quality"][profile]["modes"].values()
            numerator = sum(mode[quality_key] for mode in modes)
            denominator = sum(mode["fault_denominator"] for mode in modes)
            assert evidence[scorecard_key] == numerator / denominator
            assert evidence["denominator_per_arm"] == denominator

    paired_tokens = next(
        metric
        for metric in structured_score["paired_result"]["metrics"]
        if metric["metric_id"] == "input-tokens"
    )
    token_median = next(
        estimate for estimate in paired_tokens["estimates"] if estimate["statistic"] == "median"
    )
    tokens = by_id["input_tokens"]["current_evidence"]
    assert tokens == {
        "control": token_median["baseline"],
        "treatment": token_median["candidate"],
        "absolute_delta": token_median["absolute_delta"],
        "relative_delta": -0.0254,
        "confidence_interval": [
            token_median["absolute_delta_interval"]["lower"],
            token_median["absolute_delta_interval"]["upper"],
        ],
        "denominator_per_arm": paired_tokens["pair_count"],
        "disposition": "IMPROVED",
        "source": "evaluation/results/structured-reliability/v7/run-001/analysis/score.json",
    }
