from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.score_evidence_strategy_pair import score_pair

PLAN = Path("evaluation/evidence_strategy_development/v1/pair-plan.json")
RESULTS = Path("evaluation/results/evidence-strategy-development/v1/run-001")


def test_published_strategy_development_pair_is_complete_and_reproducible(tmp_path: Path) -> None:
    protocol_hash = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert (
        len(
            OutcomeLedger(RESULTS / "baseline-legacy/outcomes").collect(protocol_hash=protocol_hash)
        )
        == 27
    )
    assert (
        len(
            OutcomeLedger(RESULTS / "candidate-causal-scope/outcomes").collect(
                protocol_hash=protocol_hash
            )
        )
        == 27
    )

    regenerated = tmp_path / "analysis"
    actual = score_pair(PLAN, RESULTS, regenerated)
    published = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(actual)) == published
    assert (regenerated / "README.md").read_bytes() == (RESULTS / "analysis/README.md").read_bytes()


def test_published_strategy_result_reports_gain_but_rejects_candidate() -> None:
    result = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))
    assert result["acceptance"]["top1_correct"] == {
        "baseline": 2,
        "candidate": 7,
        "gain": 5,
    }
    assert result["acceptance"]["safe_control_noninferior"] is True
    assert result["acceptance"]["evidence_integrity"] is True
    assert result["acceptance"]["cost_latency_gate"] is True
    assert result["acceptance"]["candidate_failures_zero"] is False
    assert result["acceptance"]["passed"] is False
    assert result["quality"]["baseline-legacy"]["modes"]["controlled-graph"]["failures"] == 9
    assert result["quality"]["candidate-causal-scope"]["modes"]["controlled-graph"]["failures"] == 3
    metrics = {item["metric_id"]: item for item in result["paired_result"]["metrics"]}
    top1 = metrics["top1"]["estimates"][0]
    assert top1["statistic"] == "rate"
    assert top1["baseline"] == 2 / 18
    assert top1["candidate"] == 7 / 18
    assert top1["absolute_delta"] == 5 / 18
    assert top1["relative_delta"] == pytest.approx(2.5)
    assert top1["beneficial_delta"] == 5 / 18
    assert top1["absolute_delta_interval"] == {"lower": 0.0, "upper": 10 / 18}
    assert top1["beneficial_delta_interval"] == {"lower": 0.0, "upper": 10 / 18}
    assert metrics["safe-control"]["estimates"][0]["baseline"] == 1.0
    assert metrics["safe-control"]["estimates"][0]["candidate"] == 1.0


def test_published_runtime_manifests_bind_equal_ceilings_and_distinct_strategy() -> None:
    manifests = {}
    for arm in ("baseline-legacy", "candidate-causal-scope"):
        paths = sorted((RESULTS / arm / "controlled-graph").glob("*/runtime.json"))
        assert len(paths) == 27
        values = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        assert {item["model_provider_call_ceiling"] for item in values} == {6}
        assert {item["structured_transport_profile"] for item in values} == {
            "real-structured-evaluation/1.11.0"
        }
        manifests[arm] = {item["evidence_strategy"] for item in values}
    assert manifests == {
        "baseline-legacy": {"legacy/1.0.0"},
        "candidate-causal-scope": {"gc-aware-causal-scope/1.0.0"},
    }
