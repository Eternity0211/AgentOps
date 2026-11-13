from __future__ import annotations

from pathlib import Path

from evaluation.contracts import load_json_object
from evaluation.run_database_resource_supplement import load_resource_plan, summarize

PLAN = Path("evaluation/load/v3/database-resource-plan.json")
RESULT = Path("evaluation/results/database-resource/v1/run-001/result.json")


def test_published_database_resource_supplement_recomputes_from_all_rows() -> None:
    plan = load_resource_plan(PLAN)
    result = load_json_object(RESULT)
    recomputed = summarize(plan, result["rows"])

    assert result == recomputed | {"code_revision": result["code_revision"]}
    assert result["code_revision"] == "4bde60093c1559395c35949d51a84213054f0351"
    assert len(result["rows"]) == 44
    assert len(result["comparisons"]) == 45
    assert result["accepted"] is True
    assert all(row["error_count"] == 0 for row in result["rows"])
    assert all(row["duplicate_job_ownership"] == 0 for row in result["rows"])
    assert all(row["postgres_memory_sample_count"] >= 2 for row in result["rows"])
    assert all(
        comparison["denominator_pairs"] == 11
        and len(comparison["paired_absolute_delta_median_95pct_bootstrap"]) == 2
        for comparison in result["comparisons"]
    )
