"""Keep public portfolio numbers bound to committed machine-readable measurements."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
STATEMENTS = ROOT / "docs" / "PORTFOLIO_STATEMENTS.md"
METRICS = ROOT / "evaluation" / "results" / "comprehensive" / "v1" / "run-001" / "metrics.json"
LOAD = ROOT / "evaluation" / "results" / "load" / "v1" / "run-001" / "load-raw.json"


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_portfolio_ratios_match_committed_evaluation() -> None:
    text = STATEMENTS.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    metrics = _load(METRICS)
    baselines = cast(list[dict[str, Any]], metrics["baselines"])

    assert len(baselines) == 4
    assert all(baseline["diagnosis"]["case_count"] == 6 for baseline in baselines)
    assert all(
        baseline["recovery"]["dangerous_action_blocks"]
        == {"denominator": 4, "numerator": 4, "status": "measured"}
        for baseline in baselines
    )
    assert all(
        baseline["recovery"]["recovery_safe_outcomes"]
        == {"denominator": 6, "numerator": 5, "status": "measured"}
        for baseline in baselines
    )
    assert "4/4 dangerous-action blocks" in normalized
    assert "0/2 unapproved executions" in normalized
    assert "1/2 eligible automated recoveries" in normalized
    assert "5/6 recovery-safe outcomes" in normalized

    graph = next(item for item in baselines if item["baseline_id"] == "baseline-c-graph")
    memory = next(item for item in baselines if item["baseline_id"] == "baseline-d-memory")
    token_delta = (
        memory["diagnosis"]["input_tokens"]["total"] - graph["diagnosis"]["input_tokens"]["total"]
    )
    assert token_delta == 192
    assert "added 192 input tokens with no scored outcome change" in normalized

    worker = metrics["worker_recovery"]
    assert worker["result"] == {"denominator": 13, "numerator": 13, "status": "measured"}
    assert worker["collected_tests"] == 20
    assert "13/13 declared controls across 20 collected tests" in normalized


def test_portfolio_load_statement_preserves_scope_and_counts() -> None:
    text = STATEMENTS.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    load = _load(LOAD)
    workloads = {item["workload_id"]: item for item in load["workloads"]}

    assert load["python_version"] == "3.12.14"
    assert load["platform"] == "win32-amd64"
    assert load["hardware_summary"] == "machine=AMD64;logical_cpu_count=8"
    assert workloads["api-health"]["completed_operations"] == 128
    assert workloads["evidence-query"]["completed_operations"] == 64
    assert workloads["job-leasing"]["completed_operations"] == 64
    assert workloads["worker-processing"]["completed_operations"] == 64
    for required in (
        "bounded four-surface benchmark",
        "API health completed 128/128 operations at concurrency 8",
        "Evidence reads and Job leases",
        "each completed 64/64 at concurrency 8",
        "worker processing completed 64/64 at concurrency 4",
        "do not support any of the following statements",
        "production throughput",
        "zero vulnerabilities",
    ):
        assert required in normalized
