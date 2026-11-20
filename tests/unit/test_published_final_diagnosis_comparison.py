from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation.final_diagnosis_publication import collect_hashes, write_manifest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.score_final_diagnosis_comparison import score

PLAN = Path("evaluation/final_diagnosis_comparison/v1/plan.json")
AMENDMENT = Path("evaluation/final_diagnosis_comparison/v1/scorer-compatibility-amendment.json")
RESULTS = Path("evaluation/results/final-diagnosis-comparison/v1/run-001")


def test_published_final_diagnosis_score_recomputes_exactly(tmp_path: Path) -> None:
    regenerated = tmp_path / "analysis"
    score(PLAN, RESULTS, regenerated, compatibility_amendment=AMENDMENT)

    assert (regenerated / "score.json").read_bytes() == (
        RESULTS / "analysis/score.json"
    ).read_bytes()
    assert (regenerated / "README.md").read_bytes() == (RESULTS / "analysis/README.md").read_bytes()


def test_published_final_diagnosis_effect_and_gates_are_exact() -> None:
    result = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))
    comparison = result["comparisons"]["single-to-graph"]["result"]
    metrics = {item["metric_id"]: item for item in comparison["metrics"]}
    top1 = metrics["top1"]
    median_latency = metrics["duration-ms"]["estimates"][0]
    median_tokens = metrics["input-tokens"]["estimates"][0]

    assert result["outcome_count"] == 480
    assert comparison["critical_safety_gate_passed"] is False
    assert comparison["cost_latency_gate_passed"] is True
    assert top1["claim"] == "NO_PROVEN_IMPROVEMENT"
    assert top1["estimates"][0]["baseline"] == pytest.approx(10 / 120)
    assert top1["estimates"][0]["candidate"] == pytest.approx(49 / 120)
    assert top1["estimates"][0]["absolute_delta"] == pytest.approx(39 / 120)
    assert top1["estimates"][0]["absolute_delta_interval"] == {
        "lower": pytest.approx(28 / 120),
        "upper": pytest.approx(51 / 120),
    }
    assert top1["paired_test"]["holm_adjusted_p_value"] == pytest.approx(3.059311382003216e-08)
    assert median_latency["absolute_delta"] == 508
    assert median_tokens["absolute_delta"] == 201


def test_published_final_diagnosis_outcomes_and_manifest_are_complete() -> None:
    protocol_hash = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))[
        "protocol_sha256"
    ]
    outcomes = OutcomeLedger(RESULTS / "outcomes").collect(protocol_hash=protocol_hash)
    by_mode = {
        mode: [item for item in outcomes if item.mode == mode]
        for mode in ("rules-only", "single-agent", "controlled-graph")
    }
    expected = json.loads((RESULTS / "file-hashes.json").read_text(encoding="utf-8"))

    assert len(outcomes) == 480
    assert {mode: len(rows) for mode, rows in by_mode.items()} == {
        "rules-only": 160,
        "single-agent": 160,
        "controlled-graph": 160,
    }
    assert {
        mode: sum(item.status == "FAILED" for item in rows) for mode, rows in by_mode.items()
    } == {
        "rules-only": 10,
        "single-agent": 0,
        "controlled-graph": 1,
    }
    assert len(expected) == 5994
    assert collect_hashes(RESULTS) == expected


def test_final_diagnosis_manifest_writer_is_create_only(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text("{}\n", encoding="utf-8")
    manifest = write_manifest(tmp_path)

    assert json.loads(manifest.read_text(encoding="utf-8")) == collect_hashes(tmp_path)
    with pytest.raises(FileExistsError):
        write_manifest(tmp_path)
