from __future__ import annotations

import hashlib
import json
from pathlib import Path

PLAN = Path("evaluation/load/v3/database-resource-plan.json")


def test_database_resource_plan_is_frozen_complete_and_parent_bound() -> None:
    value = json.loads(PLAN.read_text(encoding="utf-8"))

    assert value["schema_version"] == "database-resource-plan/1.0.0"
    assert value["status"] == "FROZEN_BEFORE_MEASUREMENT"
    assert value["worker_levels"] == [1, 2, 4, 8]
    assert value["repetitions"] == 11
    assert value["operations_per_repetition"] == 64
    assert value["acceptance"]["required_rows"] == 44
    assert value["acceptance"]["maximum_errors"] == 0
    assert value["acceptance"]["maximum_duplicate_job_ownership"] == 0
    parent = Path(value["parent_result"])
    workload = Path(value["workload_source"])
    assert hashlib.sha256(parent.read_bytes()).hexdigest() == value["parent_result_sha256"]
    assert hashlib.sha256(workload.read_bytes()).hexdigest() == value["workload_source_sha256"]


def test_database_resource_plan_covers_cpu_memory_io_and_postgres_counters() -> None:
    value = json.loads(PLAN.read_text(encoding="utf-8"))

    assert set(value["container_metrics"]) == {
        "postgres_container_cpu_usage_usec",
        "postgres_container_memory_peak_observed_bytes",
        "postgres_container_io_read_bytes",
        "postgres_container_io_write_bytes",
    }
    assert set(value["postgres_metrics"]) >= {
        "xact_commit",
        "xact_rollback",
        "blks_read",
        "blks_hit",
        "temp_bytes",
        "deadlocks",
        "tup_inserted",
        "tup_updated",
    }
    assert "candidate-minus-baseline" in value["intervals"]["method"]
    assert "Do not reinterpret resource increase as benefit" in value["reporting"]
