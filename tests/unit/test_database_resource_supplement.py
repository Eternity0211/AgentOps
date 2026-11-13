from __future__ import annotations

from pathlib import Path

from evaluation.run_database_resource_supplement import (
    ContainerCounters,
    load_resource_plan,
    parse_container_stats,
    summarize,
)

PLAN = Path("evaluation/load/v3/database-resource-plan.json")


def test_container_stats_parser_sums_devices_and_converts_cpu_to_microseconds() -> None:
    counters = parse_container_stats(
        {
            "cpu_stats": {"cpu_usage": {"total_usage": 12_345_000}},
            "memory_stats": {"usage": 98_765},
            "blkio_stats": {
                "io_service_bytes_recursive": [
                    {"op": "read", "value": 100},
                    {"op": "write", "value": 200},
                    {"op": "read", "value": 300},
                    {"op": "sync", "value": 999},
                ]
            },
        }
    )

    assert counters == ContainerCounters(12_345, 98_765, 400, 200)


def _rows() -> list[dict[str, int | float | str]]:
    rows = []
    resource_metrics = (
        "postgres_container_cpu_usage_usec",
        "postgres_container_memory_peak_observed_bytes",
        "postgres_container_io_read_bytes",
        "postgres_container_io_write_bytes",
        "postgres_xact_commit",
        "postgres_xact_rollback",
        "postgres_blks_read",
        "postgres_blks_hit",
        "postgres_temp_bytes",
        "postgres_deadlocks",
        "postgres_tup_returned",
        "postgres_tup_fetched",
        "postgres_tup_inserted",
        "postgres_tup_updated",
        "postgres_tup_deleted",
    )
    for repetition in range(1, 12):
        for workers in (1, 2, 4, 8):
            row: dict[str, int | float | str] = {
                "workers": workers,
                "repetition": repetition,
                "completed_jobs": 64,
                "error_count": 0,
                "duplicate_job_ownership": 0,
                "postgres_memory_sample_count": 3,
            }
            row.update(
                {
                    metric: workers * 100 + repetition + index
                    for index, metric in enumerate(resource_metrics)
                }
            )
            rows.append(row)
    return rows


def test_database_resource_summary_has_all_pairs_deltas_and_intervals() -> None:
    result = summarize(load_resource_plan(PLAN), _rows())

    assert result["accepted"] is True
    assert len(result["rows"]) == 44
    assert len(result["groups"]) == 4
    assert len(result["comparisons"]) == 45
    assert {item["workers"] for item in result["comparisons"]} == {2, 4, 8}
    assert all(item["denominator_pairs"] == 11 for item in result["comparisons"])
    assert all(
        len(item["paired_absolute_delta_median_95pct_bootstrap"]) == 2
        for item in result["comparisons"]
    )
    assert all(
        item["interpretation"] == "RESOURCE_LOAD_NOT_BENEFIT" for item in result["comparisons"]
    )
