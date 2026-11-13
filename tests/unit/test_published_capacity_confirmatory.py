from __future__ import annotations

from pathlib import Path

from evaluation.contracts import load_json_object
from evaluation.run_capacity_pilot import load_plan, summarize_confirmatory

PLAN = Path("evaluation/load/v2/confirmatory-plan.json")
RESULT = Path("evaluation/results/final-load/v1/confirmatory-001/confirmatory.json")


def test_published_capacity_confirmation_recomputes_and_decides_broker_evaluation() -> None:
    plan = load_plan(PLAN)
    result = load_json_object(RESULT)
    recomputed = summarize_confirmatory(plan, result["rows"])

    assert result == recomputed | {"code_revision": result["code_revision"]}
    assert result["code_revision"] == "ba7b696614a7e55c0752795acd89aecab611ff95"
    assert len(result["rows"]) == 44
    assert result["correctness_passed"] is True
    assert result["broker_decision"] == "BROKER_EVALUATION_REQUIRED"
    assert result["throughput_ratio_8_to_4"] <= 1.05
    assert result["queue_wait_p95_ratio_8_to_4"] >= 1.25
    assert sum(item["error_count"] for item in result["groups"]) == 0
    assert sum(item["duplicate_job_ownership"] for item in result["groups"]) == 0
