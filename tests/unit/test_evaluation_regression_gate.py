"""Measured prompt/model/policy promotion regression gate tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from evaluation.contracts import EvaluationContractError, load_json_object
from evaluation.regression_gate import evaluate_promotion, load_promotion_policy, write_decision

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "evaluation" / "results" / "comprehensive" / "v1" / "run-001" / "metrics.json"
POLICY = ROOT / "evaluation" / "regression" / "v1" / "policy.json"


def _candidate(tmp_path: Path, mutate: Any | None = None) -> Path:
    value = load_json_object(REFERENCE)
    if mutate is not None:
        mutate(value)
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _baseline(value: dict[str, Any], baseline_id: str) -> dict[str, Any]:
    return next(item for item in value["baselines"] if item["baseline_id"] == baseline_id)


@pytest.mark.parametrize(
    ("change_kind", "target"),
    (
        ("prompt", "baseline-b-single"),
        ("model", "baseline-c-graph"),
        ("prompt", "baseline-d-memory"),
        ("policy", "all"),
    ),
)
def test_measured_reference_passes_each_allowed_promotion_scope(
    tmp_path: Path, change_kind: str, target: str
) -> None:
    decision = evaluate_promotion(
        candidate_path=_candidate(tmp_path),
        policy_path=POLICY,
        change_kind=change_kind,
        target=target,
        root=ROOT,
    )
    assert decision["outcome"] == "pass"
    assert decision["reasons"] == []
    assert decision["reference_metrics_sha256"] == (
        "a83ddda5ae2fc934805ef0cfadda228c6e44a194e4ad4261a642a68927ed6223"
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (
            lambda value: _baseline(value, "baseline-b-single")["diagnosis"][
                "top1_root_cause"
            ].update(numerator=1),
            "TOP1_REGRESSION",
        ),
        (
            lambda value: _baseline(value, "baseline-b-single")["diagnosis"][
                "fabricated_references"
            ].update(numerator=1),
            "FABRICATED_REFERENCE_REGRESSION",
        ),
        (
            lambda value: _baseline(value, "baseline-b-single")["diagnosis"][
                "cost_microusd"
            ].update(total=1),
            "COST_REGRESSION",
        ),
        (
            lambda value: _baseline(value, "baseline-b-single")["recovery"][
                "dangerous_action_blocks"
            ].update(numerator=3),
            "DANGEROUS_ACTION_BLOCK_REGRESSION",
        ),
        (
            lambda value: value["worker_recovery"]["result"].update(numerator=12),
            "WORKER_RECOVERY_REGRESSION",
        ),
    ),
)
def test_prompt_gate_fails_closed_on_measured_regressions(
    tmp_path: Path, mutation: Any, reason: str
) -> None:
    decision = evaluate_promotion(
        candidate_path=_candidate(tmp_path, mutation),
        policy_path=POLICY,
        change_kind="prompt",
        target="baseline-b-single",
        root=ROOT,
    )
    assert decision["outcome"] == "fail"
    assert reason in decision["reasons"]


def test_policy_gate_checks_all_profiles_and_source_bindings(tmp_path: Path) -> None:
    def mutate(value: dict[str, Any]) -> None:
        value["diagnosis_dataset_sha256"] = "0" * 64
        recovery = _baseline(value, "baseline-d-memory")["recovery"]
        recovery["recovery_safe_outcomes"]["numerator"] = 4
        recovery["unapproved_executions"]["numerator"] = 1
        recovery["future_compensation_attempts"]["numerator"] = 1

    decision = evaluate_promotion(
        candidate_path=_candidate(tmp_path, mutate),
        policy_path=POLICY,
        change_kind="policy",
        target="all",
        root=ROOT,
    )
    assert decision["outcome"] == "fail"
    assert decision["reasons"] == [
        "SOURCE_BINDING_DRIFT",
        "UNAPPROVED_EXECUTION_REGRESSION",
        "SAFE_OUTCOME_REGRESSION",
        "FUTURE_COMPENSATION_REGRESSION",
    ]


def test_duplicate_metric_cannot_be_recast_as_a_measured_baseline_rate(tmp_path: Path) -> None:
    def mutate(value: dict[str, Any]) -> None:
        duplicate = _baseline(value, "baseline-c-graph")["recovery"]["duplicate_executions"]
        duplicate.update(numerator=0, denominator=6, status="measured")

    decision = evaluate_promotion(
        candidate_path=_candidate(tmp_path, mutate),
        policy_path=POLICY,
        change_kind="model",
        target="baseline-c-graph",
        root=ROOT,
    )
    assert decision["outcome"] == "fail"
    assert decision["reasons"] == ["DUPLICATE_REPLAY_EVIDENCE_MISSING"]


def test_gate_rejects_wrong_scope_and_weakened_policy(tmp_path: Path) -> None:
    with pytest.raises(EvaluationContractError, match="target"):
        evaluate_promotion(
            candidate_path=_candidate(tmp_path),
            policy_path=POLICY,
            change_kind="prompt",
            target="baseline-a-rules",
            root=ROOT,
        )

    policy = load_json_object(POLICY)
    policy["worker_recovery_minimum"] = 12
    changed = tmp_path / "policy.json"
    changed.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="worker recovery"):
        load_promotion_policy(changed)


def test_promotion_decision_is_create_only_and_hash_bound(tmp_path: Path) -> None:
    decision = evaluate_promotion(
        candidate_path=_candidate(tmp_path),
        policy_path=POLICY,
        change_kind="model",
        target="baseline-d-memory",
        root=ROOT,
    )
    output = tmp_path / "decision.json"
    fingerprint = write_decision(decision, output)
    assert len(fingerprint) == 64
    assert load_json_object(output) == decision
    with pytest.raises(EvaluationContractError, match="already exists"):
        write_decision(decision, output)
