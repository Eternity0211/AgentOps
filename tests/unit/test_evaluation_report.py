"""Published evaluation claims stay bound to committed machine-readable results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "EVALUATION_REPORT.md"
COMPREHENSIVE = ROOT / "evaluation" / "results" / "comprehensive" / "v1" / "run-001"
LOAD = ROOT / "evaluation" / "results" / "load" / "v1" / "run-001" / "load-raw.json"


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_published_evaluation_summary_is_derived_from_committed_results() -> None:
    report = REPORT.read_text(encoding="utf-8")
    metrics = _load(COMPREHENSIVE / "metrics.json")
    worker = metrics["worker_recovery"]
    baselines = metrics["baselines"]
    labels = ("Rules", "Single pass", "Controlled graph", "Graph plus memory")

    for label, baseline in zip(labels, baselines, strict=True):
        diagnosis = baseline["diagnosis"]
        row = (
            f"| {label} | {diagnosis['top1_root_cause']['numerator']}/"
            f"{diagnosis['top1_root_cause']['denominator']} | "
            f"{diagnosis['top3_root_cause']['numerator']}/"
            f"{diagnosis['top3_root_cause']['denominator']} | "
            f"{diagnosis['correct_handoff']['numerator']}/"
            f"{diagnosis['correct_handoff']['denominator']} | "
            f"{diagnosis['unsupported_conclusions']['numerator']}/"
            f"{diagnosis['unsupported_conclusions']['denominator']} | "
            f"{diagnosis['input_tokens']['total']}/{diagnosis['output_tokens']['total']} |"
        )
        assert row in report

        recovery = baseline["recovery"]
        assert recovery["dangerous_action_blocks"] == {
            "denominator": 4,
            "numerator": 4,
            "status": "measured",
        }
        assert recovery["unapproved_executions"] == {
            "denominator": 2,
            "numerator": 0,
            "status": "measured",
        }
        assert recovery["eligible_automated_recovery"] == {
            "denominator": 2,
            "numerator": 1,
            "status": "measured",
        }
        assert recovery["recovery_safe_outcomes"] == {
            "denominator": 6,
            "numerator": 5,
            "status": "measured",
        }

    assert (
        f"passed {worker['result']['numerator']}/{worker['result']['denominator']} declared "
        f"controls across {worker['collected_tests']} collected tests"
    ) in report


def test_published_load_counts_and_raw_links_are_complete() -> None:
    report = REPORT.read_text(encoding="utf-8")
    normalized_report = " ".join(report.split())
    load = _load(LOAD)
    expected_labels = {
        "api-health": "API health",
        "evidence-query": "Evidence reads",
        "job-leasing": "Job leasing",
        "worker-processing": "worker processing",
    }
    for workload in load["workloads"]:
        expected = (
            f"{expected_labels[workload['workload_id']]} "
            f"{workload['completed_operations']}/{workload['configured_operations']}"
        )
        assert expected in normalized_report

    required_links = (
        "../evaluation/results/rules/v1/run-001/diagnosis-raw.json",
        "../evaluation/results/single-agent/v1/run-001/diagnosis-raw.json",
        "../evaluation/results/controlled-graph/v1/run-001/diagnosis-raw.json",
        "../evaluation/results/controlled-graph-memory/v1/run-001/diagnosis-raw.json",
        "../evaluation/results/comprehensive/v1/run-001/metrics.json",
        "../evaluation/results/comprehensive/v1/run-001/worker-resilience-raw.json",
        "../evaluation/results/load/v1/run-001/load-raw.json",
    )
    for link in required_links:
        assert link in report
