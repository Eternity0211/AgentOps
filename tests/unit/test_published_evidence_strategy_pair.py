from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from evaluation.autonomous_diagnosis import EvidenceStrategy
from evaluation.run_evidence_strategy_pair import BOUND_SOURCES, check_plan
from evaluation.structured_model import StructuredTransportProfile

PLAN = Path("evaluation/evidence_strategy_development/v1/pair-plan.json")
DATASET = Path("evaluation/datasets/evidence-strategy-development-v1")


def test_evidence_strategy_pair_was_frozen_before_provider_calls() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "18fda0a65b485536528c74a4dba21b12956cb6f1"
    assert plan["expected_outcomes"] == 54
    assert plan["model_provider_call_ceiling"] == 6
    assert plan["graph_model_call_ceiling"] == 4
    assert plan["tool_call_ceiling"] == 12
    assert plan["acceptance"]["minimum_top1_correct_gain"] == 2
    assert set(plan["source_hashes"]) == BOUND_SOURCES
    assert plan["profiles"] == {
        "baseline-legacy": StructuredTransportProfile.CANDIDATE_1_11.value,
        "candidate-causal-scope": StructuredTransportProfile.CANDIDATE_1_11.value,
    }
    assert plan["arms"]["baseline-legacy"]["evidence_strategy"] == EvidenceStrategy.LEGACY.value
    assert (
        plan["arms"]["candidate-causal-scope"]["evidence_strategy"]
        == EvidenceStrategy.GC_AWARE_CAUSAL_SCOPE.value
    )


def test_evidence_strategy_pair_binds_committed_sources_and_inputs() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for name, expected in plan["source_hashes"].items():
        content = subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=D:/AgentOps",
                "show",
                f"{plan['implementation_commit']}:{name}",
            ]
        )
        assert hashlib.sha256(content).hexdigest() == expected
    assert (
        hashlib.sha256((DATASET / "index.json").read_bytes()).hexdigest()
        == plan["dataset_index_sha256"]
    )
    labels = Path(plan["evaluator_labels"])
    assert hashlib.sha256(labels.read_bytes()).hexdigest() == plan["evaluator_labels_sha256"]
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    assert check_plan(plan, revision, DATASET) == (
        (
            "baseline-legacy",
            StructuredTransportProfile.CANDIDATE_1_11,
            EvidenceStrategy.LEGACY,
        ),
        (
            "candidate-causal-scope",
            StructuredTransportProfile.CANDIDATE_1_11,
            EvidenceStrategy.GC_AWARE_CAUSAL_SCOPE,
        ),
    )
