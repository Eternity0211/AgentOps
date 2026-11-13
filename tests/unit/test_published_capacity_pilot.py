from __future__ import annotations

import hashlib
from pathlib import Path

from evaluation.contracts import load_json_object
from evaluation.run_capacity_pilot import load_plan, summarize

PLAN = Path("evaluation/load/v2/pilot-plan.json")
RESULT = Path("evaluation/results/final-load/v1/pilot-001/pilot.json")
CONFIRMATORY = Path("evaluation/load/v2/confirmatory-plan.json")


def test_published_capacity_pilot_recomputes_and_sizes_confirmation() -> None:
    plan = load_plan(PLAN)
    result = load_json_object(RESULT)
    recomputed = summarize(plan, result["rows"])

    assert result == recomputed | {"code_revision": result["code_revision"]}
    assert result["code_revision"] == "b15674cc3a678dbab2beabc7aaedfb802598a1a2"
    assert result["confirmatory_repetitions"] == 11
    assert sum(group["error_count"] for group in result["groups"]) == 0
    assert sum(group["duplicate_job_ownership"] for group in result["groups"]) == 0


def test_confirmatory_plan_is_bound_to_pilot_and_frozen_before_use() -> None:
    plan = load_json_object(CONFIRMATORY)

    assert plan["schema_version"] == "capacity-confirmatory-plan/1.0.0"
    assert plan["status"] == "FROZEN_BEFORE_CONFIRMATORY_RUN"
    assert plan["confirmatory_repetitions"] == 11
    assert plan["worker_levels"] == [1, 2, 4, 8]
    assert plan["sized_from_pilot_sha256"] == hashlib.sha256(RESULT.read_bytes()).hexdigest()
    assert plan["broker_threshold"]["minimum_throughput_ratio_8_to_4"] == 1.05
    assert plan["broker_threshold"]["maximum_queue_wait_p95_ratio_8_to_4"] == 1.25
