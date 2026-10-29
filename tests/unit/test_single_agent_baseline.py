"""Single-Agent baseline profile, isolation, model, and runner tests."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from evaluation.baselines import single_agent as single_agent_module
from evaluation.baselines.recovery import DeterministicRecoverySafetySystem
from evaluation.baselines.single_agent import SingleAgentDiagnosisSystem
from evaluation.contracts import EvaluationContractError, content_sha256, load_json_object
from evaluation.fairness import CandidateExecutionConfig
from evaluation.harness import load_fair_suite, load_recovery_fixtures
from evaluation.run_single_agent_baseline import execute_single_agent_baseline
from evaluation.scoring import load_score_result
from evaluation.tracks import DiagnosisRawResult, RecoverySafetyRawResult

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "evaluation" / "datasets" / "v1" / "dataset.json"
RULES_PATH = ROOT / "evaluation" / "rules" / "v2" / "rules.json"
FAIRNESS_POLICY_PATH = ROOT / "evaluation" / "fairness" / "v1" / "policy.json"
FAIRNESS_PLAN_PATH = ROOT / "evaluation" / "plans" / "v1" / "comparison.json"
RECOVERY_FIXTURES_PATH = ROOT / "evaluation" / "recovery" / "v1" / "fixtures.json"
MODEL_SETTINGS_PATH = ROOT / "evaluation" / "models" / "v1" / "diagnosis-mock.json"
PROMPT_PATH = ROOT / "evaluation" / "prompts" / "v1" / "single-agent.json"


def suite() -> tuple[Any, Any, Any, Any, CandidateExecutionConfig]:
    dataset, rules, policy, plan = load_fair_suite(
        DATASET_PATH, RULES_PATH, FAIRNESS_POLICY_PATH, FAIRNESS_PLAN_PATH
    )
    profile = next(item for item in plan.baselines if item.kind == "single-agent")
    return (
        dataset,
        rules,
        policy,
        plan,
        CandidateExecutionConfig(profile, plan.tool_schema_versions),
    )


def test_single_agent_profile_binds_committed_model_settings_and_prompt() -> None:
    _, _, _, _, configuration = suite()
    settings = load_json_object(MODEL_SETTINGS_PATH)
    prompt = load_json_object(PROMPT_PATH)

    assert content_sha256(settings) == configuration.profile.model_settings_sha256
    assert settings == {
        "model_version": "diagnosis-mock/1.0.0",
        "scenario": "VALID",
        "seed": 7,
        "temperature_millidegrees": 0,
    }
    assert prompt["prompt_version"] == configuration.profile.prompt_version
    assert prompt["purpose"] == "DIAGNOSIS"
    assert prompt["interface"] == "single-pass"


def test_single_agent_is_model_driven_but_gate_fail_closed() -> None:
    dataset, _, _, _, configuration = suite()
    system = SingleAgentDiagnosisSystem()

    for case in dataset.cases:
        result = system.evaluate(case, configuration)
        assert result["status"] == "handoff"
        assert result["diagnosis_top3"] == ["deployment-regression"]
        assert result["cited_evidence_ids"] == [
            f"observation-{case.case_id}-1-{case.observation.signals[0].source}"
        ]
        assert result["evidence_gate_outcome"] == "fail"
        assert result["outcome_reason_code"] == "EVIDENCE_GATE_INDEPENDENT_SOURCES_MISSING"
        assert result["tool_calls"] == 0
        assert result["input_tokens"] > 0
        assert result["output_tokens"] > 0
        assert result["cost_microusd"] == 0

    source = inspect.getsource(single_agent_module).casefold()
    assert "ground_truth" not in source
    assert "evaluation.scoring" not in source
    assert "import langgraph" not in source
    assert "incident_memory" not in source


def test_single_agent_rejects_wrong_profile_and_changed_versioned_inputs(
    tmp_path: Path,
) -> None:
    dataset, _, _, plan, configuration = suite()
    rules_profile = next(item for item in plan.baselines if item.kind == "rules")
    wrong = CandidateExecutionConfig(rules_profile, plan.tool_schema_versions)
    with pytest.raises(EvaluationContractError, match="exact predeclared profile"):
        SingleAgentDiagnosisSystem().evaluate(dataset.cases[0], wrong)

    settings = load_json_object(MODEL_SETTINGS_PATH)
    settings["seed"] = 8
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="not predeclared"):
        SingleAgentDiagnosisSystem(model_settings_path=settings_path)

    prompt = load_json_object(PROMPT_PATH)
    prompt["purpose"] = "REMEDIATION"
    prompt_path = tmp_path / "prompt.json"
    prompt_path.write_text(json.dumps(prompt), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="approved version"):
        SingleAgentDiagnosisSystem(prompt_path=prompt_path)

    assert configuration.profile.memory_access is False


def test_every_profile_receives_the_identical_deterministic_recovery_chain() -> None:
    _, _, _, plan, single_configuration = suite()
    rules_profile = next(item for item in plan.baselines if item.kind == "rules")
    rules_configuration = CandidateExecutionConfig(rules_profile, plan.tool_schema_versions)
    fixture = load_recovery_fixtures(RECOVERY_FIXTURES_PATH).cases[3].system_input
    system = DeterministicRecoverySafetySystem()

    assert system.evaluate(fixture, single_configuration) == system.evaluate(
        fixture, rules_configuration
    )


def _clocks() -> tuple[Any, Any]:
    times = iter(
        datetime(2026, 10, 29, 10, 0, tzinfo=UTC) + timedelta(seconds=index) for index in range(4)
    )
    ticks = iter(index * 1_000_000 for index in range(24))
    return lambda: next(times), lambda: next(ticks)


def test_single_agent_runner_is_create_only_deterministic_and_hash_bound(tmp_path: Path) -> None:
    first_clocks = _clocks()
    first_output = tmp_path / "first"
    first_hashes = execute_single_agent_baseline(
        output_dir=first_output,
        code_revision="b" * 40,
        run_id="single-agent-test-001",
        wall_clock=first_clocks[0],
        duration_clock_ns=first_clocks[1],
    )
    second_clocks = _clocks()
    second_output = tmp_path / "second"
    second_hashes = execute_single_agent_baseline(
        output_dir=second_output,
        code_revision="b" * 40,
        run_id="single-agent-test-001",
        wall_clock=second_clocks[0],
        duration_clock_ns=second_clocks[1],
    )

    assert first_hashes == second_hashes
    names = {
        "diagnosis-raw.json",
        "diagnosis-report.md",
        "recovery-safety-raw.json",
        "recovery-safety-report.md",
        "safe-outcomes.json",
        "safe-outcomes.md",
    }
    assert {path.name for path in first_output.iterdir()} == names
    for name in names:
        assert (first_output / name).read_bytes() == (second_output / name).read_bytes()

    _, rules, _, _, configuration = suite()
    diagnosis = DiagnosisRawResult.from_mapping(
        load_json_object(first_output / "diagnosis-raw.json"), rules=rules
    )
    recovery = RecoverySafetyRawResult.from_mapping(
        load_json_object(first_output / "recovery-safety-raw.json"), rules=rules
    )
    score = load_score_result(first_output / "safe-outcomes.json")
    assert diagnosis.metadata.model_id == "diagnosis-mock"
    assert diagnosis.metadata.model_settings_sha256 == configuration.profile.model_settings_sha256
    assert diagnosis.fingerprint == first_hashes[0]
    assert recovery.fingerprint == first_hashes[1]
    assert score.fingerprint == first_hashes[2]
    assert all(case.input_tokens > 0 and case.output_tokens > 0 for case in diagnosis.cases)
    assert all(case.cost_microusd == 0 for case in diagnosis.cases)
    assert score.summary.correct_handoff_numerator == 0
    assert score.summary.handoff_attempt_denominator == 6
    assert score.summary.recovery_safe_outcome_numerator == 5
    assert score.summary.automated_recovery_numerator == 1
    assert score.summary.automated_recovery_denominator == 2

    with pytest.raises(EvaluationContractError, match="already exists"):
        execute_single_agent_baseline(
            output_dir=first_output,
            code_revision="b" * 40,
            run_id="single-agent-test-002",
        )
