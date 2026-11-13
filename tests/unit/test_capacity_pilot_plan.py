from __future__ import annotations

import json
from pathlib import Path

PLAN = Path("evaluation/load/v2/pilot-plan.json")


def test_capacity_pilot_plan_is_frozen_and_has_all_worker_levels() -> None:
    value = json.loads(PLAN.read_text(encoding="utf-8"))

    assert value["schema_version"] == "capacity-pilot-plan/1.0.0"
    assert value["status"] == "FROZEN_BEFORE_PILOT"
    assert value["worker_levels"] == [1, 2, 4, 8]
    assert value["pilot_repetitions"] == 3
    assert value["operations_per_repetition"] == 64
    assert set(value["metrics"]) >= {
        "throughput_jobs_per_second",
        "queue_wait_p95_ms",
        "workflow_latency_p95_ms",
        "error_rate",
        "lease_contention_rate",
        "process_cpu_ms",
        "python_heap_peak_bytes",
        "database_statement_count",
    }


def test_capacity_pilot_predeclares_sizing_and_broker_decision() -> None:
    value = json.loads(PLAN.read_text(encoding="utf-8"))
    sizing = value["confirmatory_sizing"]
    threshold = value["broker_threshold"]

    assert sizing["minimum_relevant_relative_delta"] == 0.1
    assert (sizing["minimum_repetitions"], sizing["maximum_repetitions"]) == (5, 30)
    assert threshold["minimum_throughput_ratio_8_to_4"] == 1.05
    assert threshold["maximum_queue_wait_p95_ratio_8_to_4"] == 1.25
    assert "does not by itself justify a broker" in threshold["correctness_gate"]
