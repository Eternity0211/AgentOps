from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from evaluation.autonomous_diagnosis import EvidenceStrategy
from evaluation.run_evidence_strategy_pair import BOUND_SOURCES, check_plan
from evaluation.structured_model import StructuredTransportProfile

PLAN = Path("evaluation/evidence_strategy_development/v3/pair-plan.json")
DATASET = Path("evaluation/datasets/evidence-strategy-development-v1")


def test_run_003_protocol_is_implementation_bound_and_final() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert plan["protocol_id"] == "fc4-evidence-strategy-development-pair-v3"
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "3a1ecff92c3b662ab600b75bb75c0d6721c30627"
    assert plan["expected_outcomes"] == 54
    assert plan["model_provider_call_ceiling"] == 6
    assert plan["graph_model_call_ceiling"] == 4
    assert plan["tool_call_ceiling"] == 12
    assert set(plan["source_hashes"]) == BOUND_SOURCES
    assert plan["acceptance"]["minimum_top1_correct_gain"] == 2
    assert plan["development_stopping_rule"] == {
        "final_development_run": True,
        "single_complete_pair": True,
        "selective_reruns_forbidden": True,
        "stop_after_scoring_regardless_of_result": True,
        "on_acceptance_failure": (
            "Reject this candidate for FC4 confirmation, retain the negative result, and do not "
            "tune again on this development set."
        ),
    }

    for name, expected in plan["source_hashes"].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected
    error_analysis = Path(plan["error_analysis"])
    assert hashlib.sha256(error_analysis.read_bytes()).hexdigest() == plan[
        "error_analysis_sha256"
    ]


def test_run_003_protocol_passes_preflight_without_provider_work() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
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
