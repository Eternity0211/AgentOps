"""Versioned bounded-load plan and create-only runner tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from evaluation.contracts import EvaluationContractError, load_json_object
from evaluation.run_bounded_load_evaluation import (
    LoadExecution,
    execute_bounded_load_evaluation,
    junit_name_matches,
    load_bounded_load_result,
    load_plan,
    render_load_markdown,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "evaluation" / "load" / "v1" / "plan.json"
RESULT_ROOT = ROOT / "evaluation" / "results" / "load" / "v1" / "run-001"


def _clock() -> Callable[[], datetime]:
    times = iter(
        (
            datetime(2026, 10, 29, 15, 0, tzinfo=UTC),
            datetime(2026, 10, 29, 15, 1, tzinfo=UTC),
        )
    )
    return lambda: next(times)


def test_load_plan_is_closed_bounded_and_covers_required_surfaces() -> None:
    plan = load_plan(PLAN_PATH)
    assert [item.workload_id for item in plan.workloads] == [
        "api-health",
        "evidence-query",
        "job-leasing",
        "worker-processing",
    ]
    assert [item.operations for item in plan.workloads] == [128, 64, 64, 64]
    assert [item.concurrency for item in plan.workloads] == [8, 8, 8, 4]
    assert len(plan.fingerprint) == 64


def test_junit_match_accepts_anyio_suffix_without_prefix_collision() -> None:
    name = "test_bounded_api_health_load"
    assert junit_name_matches(name, name)
    assert junit_name_matches(f"{name}[asyncio]", name)
    assert not junit_name_matches(f"{name}_other[asyncio]", name)


def test_bounded_load_runner_is_create_only_and_reports_exact_counts(tmp_path: Path) -> None:
    clock = _clock()
    output = tmp_path / "result"
    fingerprints = execute_bounded_load_evaluation(
        output_dir=output,
        plan_path=PLAN_PATH,
        code_revision="a" * 40,
        run_id="bounded-load-test-001",
        executor=lambda _root, _plan: LoadExecution(
            {
                "api-health": 100,
                "evidence-query": 200,
                "job-leasing": 400,
                "worker-processing": 80,
            },
            4,
        ),
        clock=clock,
    )
    assert all(len(item) == 64 for item in fingerprints)
    result = load_json_object(output / "load-raw.json")
    assert result["code_revision"] == "a" * 40
    assert result["collected_tests"] == 4
    workloads = {item["workload_id"]: item for item in result["workloads"]}
    assert workloads["api-health"]["completed_operations"] == 128
    assert workloads["api-health"]["operations_per_second_milli"] == 1_280_000
    assert workloads["worker-processing"]["concurrency"] == 4
    report = (output / "README.md").read_text(encoding="utf-8")
    assert "not production throughput" in report

    with pytest.raises(EvaluationContractError, match="already exists"):
        execute_bounded_load_evaluation(
            output_dir=output,
            plan_path=PLAN_PATH,
            code_revision="a" * 40,
            run_id="bounded-load-test-002",
            executor=lambda _root, _plan: LoadExecution(
                {item.workload_id: 1 for item in _plan.workloads}, 4
            ),
        )


def test_load_plan_rejects_unbounded_or_reordered_workloads(tmp_path: Path) -> None:
    value = load_json_object(PLAN_PATH)
    value["workloads"][0]["concurrency"] = 129
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="values"):
        load_plan(path)

    value = load_json_object(PLAN_PATH)
    value["workloads"].reverse()
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="reordered"):
        load_plan(path)


def test_bounded_load_runner_rejects_missing_workload_and_backwards_clock(
    tmp_path: Path,
) -> None:
    with pytest.raises(EvaluationContractError, match="omitted"):
        execute_bounded_load_evaluation(
            output_dir=tmp_path / "missing",
            plan_path=PLAN_PATH,
            code_revision="b" * 40,
            run_id="bounded-load-test-003",
            executor=lambda _root, _plan: LoadExecution({"api-health": 1}, 1),
        )

    now = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
    times = iter((now, now - timedelta(seconds=1)))
    with pytest.raises(EvaluationContractError, match="timestamps"):
        execute_bounded_load_evaluation(
            output_dir=tmp_path / "backwards",
            plan_path=PLAN_PATH,
            code_revision="b" * 40,
            run_id="bounded-load-test-004",
            executor=lambda _root, plan: LoadExecution(
                {item.workload_id: 1 for item in plan.workloads}, 4
            ),
            clock=lambda: next(times),
        )


def test_committed_bounded_load_result_is_bound_and_reproducible() -> None:
    result = load_bounded_load_result(RESULT_ROOT / "load-raw.json", PLAN_PATH)
    assert result["code_revision"] == "1678dd05e077dcf16db7dd7779f2642009275406"
    assert result["run_id"] == "bounded-load-20261030-001"
    assert result["collected_tests"] == 4
    assert [item["completed_operations"] for item in result["workloads"]] == [128, 64, 64, 64]
    assert [item["concurrency"] for item in result["workloads"]] == [8, 8, 8, 4]
    assert render_load_markdown(result) == (RESULT_ROOT / "README.md").read_text(encoding="utf-8")
