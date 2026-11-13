from __future__ import annotations

from pathlib import Path

from evaluation.run_capacity_pilot import load_plan, summarize

PLAN = Path("evaluation/load/v2/pilot-plan.json")


def _rows() -> list[dict[str, int | float | str]]:
    values = []
    throughputs = {
        1: (100_000, 110_000, 105_000),
        2: (190_000, 200_000, 195_000),
        4: (300_000, 310_000, 305_000),
        8: (320_000, 325_000, 315_000),
    }
    for repetition in range(1, 4):
        for workers in (1, 2, 4, 8):
            values.append(
                {
                    "workers": workers,
                    "repetition": repetition,
                    "completed_jobs": 64,
                    "error_count": 0,
                    "duplicate_job_ownership": 0,
                    "total_latency_ms": 100,
                    "throughput_jobs_per_second_milli": throughputs[workers][repetition - 1],
                    "queue_wait_p50_ms": 10,
                    "queue_wait_p95_ms": 20,
                    "workflow_latency_p50_ms": 15,
                    "workflow_latency_p95_ms": 25,
                    "lease_contention_count": 0,
                    "lease_contention_rate": 0.0,
                    "process_cpu_ms": 5,
                    "python_heap_peak_bytes": 1000,
                    "heap_scope": "workflow_owned_trace",
                    "database_statement_count": 130,
                }
            )
    return values


def test_capacity_pilot_summary_has_baseline_deltas_and_sized_confirmation() -> None:
    result = summarize(load_plan(PLAN), _rows())

    assert len(result["rows"]) == 12
    assert [group["workers"] for group in result["groups"]] == [1, 2, 4, 8]
    assert result["groups"][0]["throughput_relative_delta_from_1_worker"] == 0
    assert result["groups"][1]["throughput_relative_delta_from_1_worker"] > 0
    assert 5 <= result["confirmatory_repetitions"] <= 30
    assert result["pilot_only"] is True
