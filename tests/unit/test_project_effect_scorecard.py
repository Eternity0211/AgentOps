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
        evidence_source = Path(evidence["source"])
        assert evidence_source.exists(), (
            f"missing source for {metric['metric_id']}: {evidence_source}"
        )

    final_score = json.loads(
        Path(
            "evaluation/results/final-diagnosis-comparison/v1/run-001/analysis/score.json"
        ).read_text(encoding="utf-8")
    )
    paired = final_score["comparisons"]["single-to-graph"]["result"]["metrics"]
    metrics = {metric["metric_id"]: metric for metric in paired}
    source = "evaluation/results/final-diagnosis-comparison/v1/run-001/analysis/score.json"
    for scorecard_id, result_id in {
        "diagnosis_top1_rate": "top1",
        "diagnosis_top3_rate": "top3",
    }.items():
        metric = metrics[result_id]
        estimate = metric["estimates"][0]
        assert by_id[scorecard_id]["current_evidence"] == {
            "control": estimate["baseline"],
            "treatment": estimate["candidate"],
            "absolute_delta": estimate["absolute_delta"],
            "relative_delta": estimate["relative_delta"],
            "confidence_interval": [
                estimate["absolute_delta_interval"]["lower"],
                estimate["absolute_delta_interval"]["upper"],
            ],
            "denominator_per_arm": metric["pair_count"],
            "disposition": "NO_PROVEN_IMPROVEMENT_CRITICAL_SAFETY_GATE_FAILED",
            "source": source,
        }

    for scorecard_id, result_id, unit in (
        ("input_tokens", "input-tokens", None),
        ("workflow_latency", "duration-ms", "milliseconds"),
        ("rate_card_cost_upper_bound", "cost-upper-bound", "nanousd_upper_bound"),
    ):
        metric = metrics[result_id]
        estimate = next(item for item in metric["estimates"] if item["statistic"] == "median")
        expected = {
            "control": estimate["baseline"],
            "treatment": estimate["candidate"],
            "absolute_delta": estimate["absolute_delta"],
            "relative_delta": estimate["relative_delta"],
            "confidence_interval": [
                estimate["absolute_delta_interval"]["lower"],
                estimate["absolute_delta_interval"]["upper"],
            ],
            "denominator_per_arm": metric["pair_count"],
            "disposition": "REGRESSED",
            "source": source,
        }
        if unit is not None:
            expected["unit"] = unit
        assert by_id[scorecard_id]["current_evidence"] == expected
