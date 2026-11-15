from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "evaluation/evidence_strategy_development/v3/error-analysis.json"
RUN = ROOT / "evaluation/results/evidence-strategy-development/v1/run-002"
PROTOCOL = ROOT / "evaluation/evidence_strategy_development/v2/pair-plan.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(arm: str, instance_id: str) -> list[dict[str, Any]]:
    path = RUN / arm / "controlled-graph" / instance_id / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _initial_plan_result(arm: str, instance_id: str) -> dict[str, Any]:
    return next(
        event
        for event in _events(arm, instance_id)
        if event.get("purpose") == "PLAN"
        and event.get("call_number") == 1
        and event.get("status") != "STARTED"
    )


def test_error_analysis_is_bound_to_published_run_002() -> None:
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))

    assert _sha256(RUN / "analysis/score.json") == analysis["score_sha256"]
    assert _sha256(PROTOCOL) == analysis["protocol_sha256"]
    assert analysis["observed_top1"] == {
        "baseline_correct": 11,
        "candidate_correct": 12,
        "candidate_gain": 1,
        "candidate_better_pairs": 4,
        "baseline_better_pairs": 3,
        "ties": 11,
        "acceptance_minimum_gain": 2,
        "accepted": False,
    }


def test_every_discordance_has_identical_initial_request_and_divergent_response() -> None:
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    gains = losses = 0

    for pair in analysis["discordant_pairs"]:
        baseline = _initial_plan_result("baseline-legacy", pair["instance_id"])
        candidate = _initial_plan_result("candidate-causal-scope", pair["instance_id"])
        assert baseline["request_hash"] == candidate["request_hash"]
        assert baseline["request_hash"] == pair["initial_request_hash"]
        assert baseline["response_hash"] == pair["baseline_initial_response_hash"]
        assert candidate["response_hash"] == pair["candidate_initial_response_hash"]
        assert baseline["response_hash"] != candidate["response_hash"]
        assert candidate["status"] == pair["candidate_initial_status"]
        if pair["direction"] == "CANDIDATE_BETTER":
            gains += 1
        else:
            assert pair["direction"] == "BASELINE_BETTER"
            losses += 1

    assert (gains, losses) == (4, 3)
    assert analysis["discordance_interpretation"]["identical_initial_requests"] == 7
    assert analysis["discordance_interpretation"]["different_initial_responses"] == 7
    assert analysis["discordance_interpretation"]["raw_provider_content_retained_here"] is False


def test_shared_misses_and_final_stopping_rule_are_predeclared() -> None:
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    assert {item["instance_id"] for item in analysis["shared_incorrect_pairs"]} == {
        "instance-62ced7d282ab3d15",
        "instance-b0e2e76a44c66362",
        "instance-ffefeff723faf580",
    }
    assert analysis["final_development_run_rule"] == {
        "run_id": "run-003",
        "single_execution": True,
        "selective_reruns_forbidden": True,
        "stop_after_run": True,
        "decision": (
            "Apply the frozen acceptance criteria once. If they fail, reject this candidate "
            "revision for FC4 confirmation and retain the negative result; do not tune again "
            "on this development set."
        ),
    }
