from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.score_evidence_strategy_pair import score_pair

PLAN = Path("evaluation/evidence_strategy_development/v2/pair-plan.json")
RESULTS = Path("evaluation/results/evidence-strategy-development/v1/run-002")


def test_run_002_is_complete_and_reproducibly_scored(tmp_path: Path) -> None:
    protocol_hash = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    for arm in ("baseline-legacy", "candidate-causal-scope"):
        outcomes = OutcomeLedger(RESULTS / arm / "outcomes").collect(
            protocol_hash=protocol_hash
        )
        assert len(outcomes) == 27
        assert all(outcome.status == "SUCCEEDED" for outcome in outcomes)

    regenerated = tmp_path / "analysis"
    actual = score_pair(PLAN, RESULTS, regenerated)
    published = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(actual)) == published
    assert (regenerated / "README.md").read_bytes() == (RESULTS / "analysis/README.md").read_bytes()


def test_run_002_eliminates_failures_but_misses_quality_acceptance() -> None:
    result = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))
    assert result["acceptance"]["top1_correct"] == {
        "baseline": 11,
        "candidate": 12,
        "gain": 1,
    }
    assert result["acceptance"]["candidate_failures_zero"] is True
    assert result["acceptance"]["candidate_terminal_schema_protocol_invalids_zero"] is True
    assert result["acceptance"]["safe_control_noninferior"] is True
    assert result["acceptance"]["evidence_integrity"] is True
    assert result["acceptance"]["cost_latency_gate"] is True
    assert result["acceptance"]["passed"] is False
    assert result["quality"]["baseline-legacy"]["modes"]["controlled-graph"]["failures"] == 0
    assert (
        result["quality"]["candidate-causal-scope"]["modes"]["controlled-graph"]["failures"]
        == 0
    )
    metrics = {item["metric_id"]: item for item in result["paired_result"]["metrics"]}
    top1 = metrics["top1"]["estimates"][0]
    assert top1["baseline"] == 11 / 18
    assert top1["candidate"] == 12 / 18
    assert top1["absolute_delta"] == pytest.approx(1 / 18)
    assert top1["absolute_delta_interval"] == {
        "lower": pytest.approx(-4 / 18),
        "upper": pytest.approx(6 / 18),
    }
    assert metrics["safe-control"]["estimates"][0]["baseline"] == 1.0
    assert metrics["safe-control"]["estimates"][0]["candidate"] == 1.0


def test_run_002_audits_novel_read_filter_without_failed_comparisons() -> None:
    filter_events: list[dict[str, Any]] = []
    for path in RESULTS.glob("*/controlled-graph/*/events.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            assert event.get("event") != "comparison.failed"
            if event.get("kind") == "novel-read-filter":
                filter_events.append(event)
    assert len(filter_events) == 22
    assert sum(int(event["dropped_count"]) for event in filter_events) == 19
    assert sum(int(event["dropped_count"]) > 0 for event in filter_events) == 15
    assert {event["decision"] for event in filter_events} == {"EXECUTE_NOVEL_READS"}
