from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from evaluation.run_evidence_strategy_pair import BOUND_SOURCES, check_plan

PLAN = Path("evaluation/evidence_strategy_development/v2/pair-plan.json")
DATASET = Path("evaluation/datasets/evidence-strategy-development-v1")


def test_run_002_protocol_is_implementation_bound_and_label_isolated() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert plan["protocol_id"] == "fc4-evidence-strategy-development-pair-v2"
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "7d3d2e3fed2bfeee4abfb35d5a741c66ac2b5d0c"
    assert plan["expected_outcomes"] == 54
    assert plan["model_provider_call_ceiling"] == 6
    assert plan["graph_model_call_ceiling"] == 4
    assert plan["tool_call_ceiling"] == 12
    assert set(plan["source_hashes"]) == BOUND_SOURCES
    assert "labels" not in plan["independent_variable"].lower()
    assert "novel-read filter" in plan["shared_replan_filter"]
    assert plan["acceptance"]["minimum_top1_correct_gain"] == 2

    for name, expected in plan["source_hashes"].items():
        committed = subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=D:/AgentOps",
                "show",
                f"{plan['implementation_commit']}:{name}",
            ]
        )
        assert hashlib.sha256(committed).hexdigest() == expected
    assert hashlib.sha256((DATASET / "index.json").read_bytes()).hexdigest() == plan[
        "dataset_index_sha256"
    ]
    labels = Path(plan["evaluator_labels"])
    assert hashlib.sha256(labels.read_bytes()).hexdigest() == plan["evaluator_labels_sha256"]


def test_run_002_protocol_refuses_evolved_source_without_provider_work() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    with pytest.raises(ValueError, match="source hash mismatch"):
        check_plan(plan, revision, DATASET)
