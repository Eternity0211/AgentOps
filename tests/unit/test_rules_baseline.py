"""Rules-baseline preparation, isolation, safety-chain, and artifact tests."""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from evaluation.baselines import rules as rules_module
from evaluation.baselines.rules import (
    DeterministicRecoverySafetySystem,
    RulesDiagnosisSystem,
)
from evaluation.contracts import EvaluationContractError, load_json_object
from evaluation.fairness import CandidateExecutionConfig, FairnessPlan, FairnessPolicy
from evaluation.harness import load_fair_suite, load_recovery_fixtures, load_suite
from evaluation.report import load_bound_result, render_markdown
from evaluation.run_rules_baseline import execute_rules_baseline
from evaluation.scoring import (
    load_score_result,
    render_safe_outcome_markdown,
)
from evaluation.tracks import DiagnosisRawResult, RecoverySafetyRawResult

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "evaluation" / "datasets" / "v1" / "dataset.json"
RULES_PATH = ROOT / "evaluation" / "rules" / "v2" / "rules.json"
FAIRNESS_POLICY_PATH = ROOT / "evaluation" / "fairness" / "v1" / "policy.json"
FAIRNESS_PLAN_PATH = ROOT / "evaluation" / "plans" / "v1" / "comparison.json"
RECOVERY_FIXTURES_PATH = ROOT / "evaluation" / "recovery" / "v1" / "fixtures.json"
RESULT_ROOT = ROOT / "evaluation" / "results" / "rules" / "v1" / "run-001"


def suite() -> tuple[Any, Any, FairnessPolicy, FairnessPlan, CandidateExecutionConfig]:
    dataset, rules, policy, plan = load_fair_suite(
        DATASET_PATH, RULES_PATH, FAIRNESS_POLICY_PATH, FAIRNESS_PLAN_PATH
    )
    profile = next(item for item in plan.baselines if item.kind == "rules")
    return (
        dataset,
        rules,
        policy,
        plan,
        CandidateExecutionConfig(profile, plan.tool_schema_versions),
    )


def test_committed_comparison_plan_is_exact_and_predeclares_all_four_baselines() -> None:
    dataset, rules = load_suite(DATASET_PATH, RULES_PATH)
    policy = FairnessPolicy.from_mapping(load_json_object(FAIRNESS_POLICY_PATH))
    plan = FairnessPlan.from_mapping(
        load_json_object(FAIRNESS_PLAN_PATH), policy=policy, dataset=dataset, rules=rules
    )

    assert plan.plan_version == "phase12-comparison-v1"
    assert [profile.baseline_id for profile in plan.baselines] == [
        "baseline-a-rules",
        "baseline-b-single",
        "baseline-c-graph",
        "baseline-d-memory",
    ]
    assert {profile.model_id for profile in plan.baselines if profile.kind != "rules"} == {
        "diagnosis-mock"
    }
    assert len({profile.model_settings_sha256 for profile in plan.baselines[1:]}) == 1
    rules_profile = plan.baselines[0]
    assert rules_profile.model_id is None
    assert rules_profile.budget.max_context_tokens == 0
    assert rules_profile.budget.max_model_tokens == 0
    assert rules_profile.budget.max_cost_microusd == 0


def test_rules_diagnosis_is_observation_driven_zero_model_and_ground_truth_blind() -> None:
    dataset, _, _, _, configuration = suite()
    system = RulesDiagnosisSystem()
    expected = {
        "bad-configuration-001": "CONFIGURATION_ACTION_UNAVAILABLE",
        "db-pool-exhaustion-001": "POOL_CAPACITY_ACTION_UNAVAILABLE",
        "downstream-latency-001": "DOWNSTREAM_LATENCY_ACTION_UNAVAILABLE",
        "http-500-001": "ROLLBACK_PREREQUISITES_MISSING",
        "memory-leak-001": "ROLLBACK_PREREQUISITES_MISSING",
        "redis-timeout-001": "DEPENDENCY_RECOVERY_ACTION_UNAVAILABLE",
    }

    for case in dataset.cases:
        result = system.evaluate(replace(case, scenario_id="opaque-scenario"), configuration)
        assert result["outcome_reason_code"] == expected[case.case_id]
        assert result["status"] == "handoff"
        assert result["diagnosis_top3"] == []
        assert result["cited_evidence_ids"] == []
        assert result["tool_calls"] == 0
        assert result["input_tokens"] == result["output_tokens"] == 0
        assert result["cost_microusd"] == 0

    source = inspect.getsource(rules_module).casefold()
    assert "ground_truth" not in source
    assert "evaluation.scoring" not in source


def test_rules_diagnosis_unknown_or_ambiguous_signal_fails_to_conservative_handoff() -> None:
    dataset, _, _, _, configuration = suite()
    case = dataset.cases[0]
    changed_observation = replace(case.observation, signals=case.observation.signals[:1])
    result = RulesDiagnosisSystem().evaluate(
        replace(case, observation=changed_observation), configuration
    )
    assert result["status"] == "handoff"
    assert result["outcome_reason_code"] == "EVIDENCE_INSUFFICIENT"
    assert result["evidence_gate_outcome"] == "fail"


def test_recovery_system_enforces_chain_order_idempotency_and_failure_route() -> None:
    _, _, _, _, configuration = suite()
    fixtures = load_recovery_fixtures(RECOVERY_FIXTURES_PATH)
    system = DeterministicRecoverySafetySystem()
    results = {
        fixture.scenario_id: system.evaluate(fixture.system_input, configuration)
        for fixture in fixtures.cases
    }

    for scenario in (
        "bad-configuration",
        "db-pool-exhaustion",
        "downstream-latency",
        "redis-timeout",
    ):
        assert results[scenario]["executor_outcome"] == "not_run"
        assert results[scenario]["executed_actions"] == 0
        assert results[scenario]["final_route"] == "human_handoff"
    assert results["redis-timeout"]["schema_validation_outcome"] == "fail"
    assert results["http-500"]["approval_outcome"] == "approved"
    assert results["http-500"]["executed_actions"] == 1
    assert results["http-500"]["duplicate_executions"] == 0
    assert results["http-500"]["verification_outcome"] == "pass"
    assert results["http-500"]["final_route"] == "closed"
    assert results["memory-leak"]["executed_actions"] == 1
    assert results["memory-leak"]["duplicate_executions"] == 0
    assert results["memory-leak"]["verification_outcome"] == "fail"
    assert results["memory-leak"]["final_route"] == "rediagnose"


def test_wrong_profile_is_rejected_before_rules_evaluation() -> None:
    dataset, _, _, plan, _ = suite()
    model_profile = next(item for item in plan.baselines if item.kind == "single-agent")
    wrong = CandidateExecutionConfig(model_profile, plan.tool_schema_versions)
    with pytest.raises(EvaluationContractError, match="no-model profile"):
        RulesDiagnosisSystem().evaluate(dataset.cases[0], wrong)


def test_rules_runner_creates_bound_artifacts_and_never_overwrites(tmp_path: Path) -> None:
    times = iter(
        datetime(2026, 10, 29, 4, 0, tzinfo=UTC) + timedelta(seconds=index) for index in range(4)
    )
    ticks = iter(index * 1_000_000 for index in range(24))
    output = tmp_path / "rules-run"
    diagnosis_sha, recovery_sha, score_sha = execute_rules_baseline(
        output_dir=output,
        code_revision="a" * 40,
        run_id="rules-baseline-test-001",
        wall_clock=lambda: next(times),
        duration_clock_ns=lambda: next(ticks),
    )

    expected_files = {
        "diagnosis-raw.json",
        "diagnosis-report.md",
        "recovery-safety-raw.json",
        "recovery-safety-report.md",
        "safe-outcomes.json",
        "safe-outcomes.md",
    }
    assert {path.name for path in output.iterdir()} == expected_files
    dataset, rules, _, _, _ = suite()
    diagnosis = DiagnosisRawResult.from_mapping(
        load_json_object(output / "diagnosis-raw.json"), rules=rules
    )
    recovery = RecoverySafetyRawResult.from_mapping(
        load_json_object(output / "recovery-safety-raw.json"), rules=rules
    )
    score = load_score_result(output / "safe-outcomes.json")
    assert diagnosis.fingerprint == diagnosis_sha
    assert recovery.fingerprint == recovery_sha
    assert score.fingerprint == score_sha
    assert diagnosis.dataset_sha256 == dataset.fingerprint
    assert all(case.input_tokens == case.output_tokens == 0 for case in diagnosis.cases)
    assert all(case.cost_microusd == 0 for case in diagnosis.cases)
    assert score.summary.correct_handoff_numerator == 6
    assert score.summary.handoff_attempt_denominator == 6
    assert score.summary.recovery_safe_outcome_numerator == 5
    assert score.summary.recovery_safe_outcome_denominator == 6
    assert score.summary.automated_recovery_numerator == 1
    assert score.summary.automated_recovery_denominator == 2
    assert "Eligible automated recovery | 1 | 2" in (output / "safe-outcomes.md").read_text(
        encoding="utf-8"
    )

    with pytest.raises(EvaluationContractError, match="already exists"):
        execute_rules_baseline(
            output_dir=output,
            code_revision="a" * 40,
            run_id="rules-baseline-test-002",
        )


def test_rules_runner_rejects_noncanonical_revision_before_creating_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "invalid"
    with pytest.raises(EvaluationContractError, match="Git SHA"):
        execute_rules_baseline(
            output_dir=output, code_revision="short", run_id="rules-baseline-invalid"
        )
    assert not output.exists()


def test_committed_rules_result_is_bound_reproducible_and_exact() -> None:
    diagnosis = load_bound_result(
        RESULT_ROOT / "diagnosis-raw.json",
        DATASET_PATH,
        RULES_PATH,
        FAIRNESS_POLICY_PATH,
        FAIRNESS_PLAN_PATH,
    )
    recovery = load_bound_result(
        RESULT_ROOT / "recovery-safety-raw.json",
        DATASET_PATH,
        RULES_PATH,
        FAIRNESS_POLICY_PATH,
        FAIRNESS_PLAN_PATH,
        RECOVERY_FIXTURES_PATH,
    )
    score = load_score_result(RESULT_ROOT / "safe-outcomes.json")

    assert isinstance(diagnosis, DiagnosisRawResult)
    assert isinstance(recovery, RecoverySafetyRawResult)
    assert diagnosis.metadata.code_revision == "f6f6395a297ed6c723017973924cd3b455874a0b"
    assert diagnosis.metadata.run_id == "rules-baseline-20261029-001"
    assert diagnosis.fingerprint == score.diagnosis_raw_sha256
    assert recovery.fingerprint == score.recovery_raw_sha256
    assert score.summary.correct_handoff_numerator == 6
    assert score.summary.handoff_attempt_denominator == 6
    assert score.summary.recovery_safe_outcome_numerator == 5
    assert score.summary.recovery_safe_outcome_denominator == 6
    assert score.summary.automated_recovery_numerator == 1
    assert score.summary.automated_recovery_denominator == 2
    assert render_markdown(diagnosis) == (RESULT_ROOT / "diagnosis-report.md").read_text(
        encoding="utf-8"
    )
    assert render_markdown(recovery) == (RESULT_ROOT / "recovery-safety-report.md").read_text(
        encoding="utf-8"
    )
    assert render_safe_outcome_markdown(score) == (RESULT_ROOT / "safe-outcomes.md").read_text(
        encoding="utf-8"
    )
