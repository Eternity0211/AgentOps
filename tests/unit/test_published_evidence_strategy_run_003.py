from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.score_evidence_strategy_pair import score_pair

PLAN = Path("evaluation/evidence_strategy_development/v3/pair-plan.json")
RESULTS = Path("evaluation/results/evidence-strategy-development/v1/run-003")


def test_run_003_is_complete_and_reproducibly_scored(tmp_path: Path) -> None:
    protocol_hash = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    baseline = OutcomeLedger(RESULTS / "baseline-legacy/outcomes").collect(
        protocol_hash=protocol_hash
    )
    candidate = OutcomeLedger(RESULTS / "candidate-causal-scope/outcomes").collect(
        protocol_hash=protocol_hash
    )
    assert len(baseline) == len(candidate) == 27
    assert sum(outcome.status == "FAILED" for outcome in baseline) == 1
    assert all(outcome.status == "SUCCEEDED" for outcome in candidate)

    regenerated = tmp_path / "analysis"
    actual = score_pair(PLAN, RESULTS, regenerated)
    published = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(actual)) == published
    assert (regenerated / "README.md").read_bytes() == (RESULTS / "analysis/README.md").read_bytes()


def test_run_003_passes_frozen_development_acceptance() -> None:
    result = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))
    assert result["acceptance"]["top1_correct"] == {
        "baseline": 7,
        "candidate": 11,
        "gain": 4,
    }
    assert result["acceptance"]["candidate_failures_zero"] is True
    assert result["acceptance"]["candidate_terminal_schema_protocol_invalids_zero"] is True
    assert result["acceptance"]["safe_control_noninferior"] is True
    assert result["acceptance"]["evidence_integrity"] is True
    assert result["acceptance"]["cost_latency_gate"] is True
    assert result["acceptance"]["passed"] is True
    assert result["quality"]["baseline-legacy"]["modes"]["controlled-graph"] == {
        "control_denominator": 9,
        "failures": 1,
        "fault_denominator": 18,
        "safe_controls": 9,
        "top1": 7,
        "top3": 7,
    }
    assert result["quality"]["candidate-causal-scope"]["modes"]["controlled-graph"] == {
        "control_denominator": 9,
        "failures": 0,
        "fault_denominator": 18,
        "safe_controls": 9,
        "top1": 11,
        "top3": 11,
    }
    metrics = {item["metric_id"]: item for item in result["paired_result"]["metrics"]}
    top1 = metrics["top1"]
    assert top1["claim"] == "NO_PROVEN_IMPROVEMENT"
    assert top1["estimates"][0]["baseline"] == 7 / 18
    assert top1["estimates"][0]["candidate"] == 11 / 18
    assert top1["estimates"][0]["absolute_delta"] == pytest.approx(4 / 18)
    assert top1["estimates"][0]["absolute_delta_interval"] == {
        "lower": pytest.approx(1 / 18),
        "upper": pytest.approx(8 / 18),
    }
    assert top1["paired_test"]["raw_p_value"] == 0.125
    assert top1["paired_test"]["holm_adjusted_p_value"] == 1.0


def test_run_003_audits_filtered_replans_and_provider_validation() -> None:
    filter_events: list[dict[str, Any]] = []
    comparison_failures: list[dict[str, Any]] = []
    for path in RESULTS.glob("*/controlled-graph/*/events.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("event") == "comparison.failed":
                comparison_failures.append(event)
            if event.get("kind") == "novel-read-filter":
                filter_events.append(event)
    assert comparison_failures == [
        {
            "error_type": "StructuredModelFailure",
            "event": "comparison.failed",
            "failure_site": "structured_model.py:invoke:401",
        }
    ]
    assert len(filter_events) == 19
    assert sum(int(event["dropped_count"]) for event in filter_events) == 10
    assert sum(int(event["dropped_count"]) > 0 for event in filter_events) == 8
    assert {event["decision"] for event in filter_events} == {"EXECUTE_NOVEL_READS"}

    result = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))
    assert result["provider_error_codes"] == {
        "baseline-legacy": {"INVALID_RESPONSE": 2},
        "candidate-causal-scope": {"INVALID_RESPONSE": 2},
    }
    assert result["audit"]["baseline-legacy"]["terminal_schema_protocol_invalids"] == 1
    assert result["audit"]["candidate-causal-scope"]["terminal_schema_protocol_invalids"] == 0
