from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import CAUSES, CONTROLS, Outcome
from evaluation.score_evidence_strategy_pair import score_pair


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "dataset"
    inputs = dataset / "inputs"
    inputs.mkdir(parents=True)
    labels_path = tmp_path / "labels.json"
    results = tmp_path / "results"
    labels = []
    index = []
    for stratum_index, stratum in enumerate((*CAUSES, *CONTROLS)):
        for offset in range(3):
            identity = f"instance-{stratum_index:02x}{offset:02x}000000000000"
            input_hash = hashlib.sha256(identity.encode()).hexdigest()
            labels.append({"instance_id": identity, "stratum": stratum})
            index.append({"instance_id": identity, "input_hash": input_hash})
    (dataset / "index.json").write_text(json.dumps(index), encoding="utf-8")
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    plan = {
        "schema_version": "evidence-strategy-pair/1.0.0",
        "protocol_id": "evidence-strategy-test",
        "dataset": dataset.as_posix(),
        "dataset_index_sha256": hashlib.sha256((dataset / "index.json").read_bytes()).hexdigest(),
        "evaluator_labels": labels_path.as_posix(),
        "evaluator_labels_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
        "profiles": {
            "baseline-legacy": "real-structured-evaluation/1.11.0",
            "candidate-causal-scope": "real-structured-evaluation/1.11.0",
        },
        "arms": {
            "baseline-legacy": {},
            "candidate-causal-scope": {},
        },
        "paired_scorer": {
            "bootstrap_iterations": 1000,
            "seed": 42,
            "binary_metrics": {
                "top1": {"minimum_relevant_effect": 0.1},
                "top3": {"minimum_relevant_effect": 0.1},
                "safe_control": {"minimum_relevant_effect": 0.1},
                "valid": {"minimum_relevant_effect": 0.01},
                "integrity": {"minimum_relevant_effect": 0.01},
            },
            "continuous_metrics": {
                "duration_ms": {"minimum_relevant_effect": 100.0},
                "input_tokens": {"minimum_relevant_effect": 100.0},
                "output_tokens": {"minimum_relevant_effect": 20.0},
                "cost_upper_bound_nanousd": {"minimum_relevant_effect": 100000.0},
            },
        },
        "acceptance": {"minimum_top1_correct_gain": 2},
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    protocol_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    for arm in plan["profiles"]:
        ledger = OutcomeLedger(results / arm / "outcomes")
        for label, row in zip(labels, index, strict=True):
            stratum = label["stratum"]
            fault = stratum in CAUSES
            correct = fault and (
                arm == "candidate-causal-scope"
                or stratum
                not in {
                    "memory-leak",
                    "bad-configuration",
                }
            )
            outcome = Outcome(
                instance_id=label["instance_id"],
                mode="controlled-graph",
                protocol_hash=protocol_hash,
                input_hash=row["input_hash"],
                status="SUCCEEDED",
                candidates=(stratum if correct else "http-500",) if fault else (),
                disposition="CANDIDATES" if fault else "HUMAN_HANDOFF",
                missing_evidence_count=0 if fault else 1,
                gate_pass=fault,
                duration_ms=900 if arm == "baseline-legacy" else 850,
                input_tokens=1000,
                output_tokens=100,
                cost_upper_bound_nanousd=420000,
            )
            ledger.append(outcome)
            case = results / arm / "controlled-graph" / label["instance_id"]
            case.mkdir(parents=True)
            (case / "events.jsonl").write_text("", encoding="utf-8")
    return plan_path, results


def test_strategy_scorer_publishes_quality_deltas_intervals_and_decision(tmp_path: Path) -> None:
    plan, results = _write_fixture(tmp_path)
    output = tmp_path / "score"

    document = score_pair(plan, results, output)

    assert document["acceptance"]["top1_correct"] == {
        "baseline": 12,
        "candidate": 18,
        "gain": 6,
    }
    assert document["acceptance"]["passed"] is True
    metrics = {item["metric_id"]: item for item in document["paired_result"]["metrics"]}
    top1 = metrics["top1"]["estimates"][0]
    assert top1["baseline"] == 2 / 3
    assert top1["candidate"] == 1.0
    assert top1["absolute_delta"] == pytest.approx(1 / 3)
    assert set(top1["absolute_delta_interval"]) == {"lower", "upper"}
    assert metrics["duration-ms"]["estimates"][0]["absolute_delta"] == -50
    readme = (output / "README.md").read_text(encoding="utf-8")
    assert "Baseline Top-1 correct: 12" in readme
    assert "Candidate Top-1 correct: 18" in readme

    with pytest.raises(FileExistsError, match="already exists"):
        score_pair(plan, results, output)
