from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evaluation.score_recall_development import (
    DevelopmentInputs,
    DevelopmentLabels,
    evidence_ready,
    score,
)

ROOT = Path("evaluation/recall_development/v1")


def test_inputs_are_label_isolated_and_have_paired_controls() -> None:
    inputs = DevelopmentInputs.model_validate_json((ROOT / "inputs.json").read_text("utf-8"))
    labels = DevelopmentLabels.model_validate_json(
        (ROOT / "evaluator_only/labels.json").read_text("utf-8")
    )
    assert set(labels.labels) == {case.case_id for case in inputs.cases}
    serialized = json.dumps(inputs.model_dump(mode="json"))
    assert "target_positive" not in serialized
    assert sum(label.target_positive for label in labels.labels.values()) == 4
    assert sum(not label.target_positive for label in labels.labels.values()) == 4


def test_candidate_keeps_gate_rules_and_rejects_negative_controls() -> None:
    inputs = DevelopmentInputs.model_validate_json((ROOT / "inputs.json").read_text("utf-8"))
    labels = DevelopmentLabels.model_validate_json(
        (ROOT / "evaluator_only/labels.json").read_text("utf-8")
    )
    outcomes = {
        case.case_id: evidence_ready(case.candidate, inputs.retention_limit_bytes)[0]
        for case in inputs.cases
    }
    assert outcomes == {case_id: label.target_positive for case_id, label in labels.labels.items()}


def test_scorer_reports_precision_recall_safety_resources_and_all_failures(tmp_path: Path) -> None:
    inputs = ROOT / "inputs.json"
    labels = ROOT / "evaluator_only/labels.json"
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "inputs_sha256": hashlib.sha256(inputs.read_bytes()).hexdigest(),
                "labels_sha256": hashlib.sha256(labels.read_bytes()).hexdigest(),
            }
        ),
        "utf-8",
    )
    result = score(inputs, labels, plan)
    assert result["baseline"]["recall"] == 0
    assert result["candidate"] == {
        "true_positive": 4,
        "false_positive": 0,
        "false_negative": 0,
        "true_negative": 4,
        "precision": 1.0,
        "recall": 1.0,
        "negative_control_safety": 1.0,
    }
    assert result["failures"] == []
    assert result["resources"]["model_calls"] == 0
    assert result["resources"]["write_calls"] == 0


def test_scorer_refuses_hash_drift(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"inputs_sha256": "0" * 64, "labels_sha256": "0" * 64}), "utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        score(ROOT / "inputs.json", ROOT / "evaluator_only/labels.json", plan)
