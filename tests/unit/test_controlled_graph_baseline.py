"""Controlled LangGraph baseline topology, isolation, and runner tests."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from evaluation.baselines import controlled_graph as controlled_graph_module
from evaluation.baselines.controlled_graph import ControlledGraphDiagnosisSystem
from evaluation.contracts import EvaluationContractError, content_sha256, load_json_object
from evaluation.fairness import CandidateExecutionConfig
from evaluation.harness import load_fair_suite
from evaluation.report import load_bound_result, render_markdown
from evaluation.run_controlled_graph_baseline import execute_controlled_graph_baseline
from evaluation.scoring import load_score_result, render_safe_outcome_markdown
from evaluation.tracks import DiagnosisRawResult, RecoverySafetyRawResult

from agentops_incident_commander.workflows import DIAGNOSIS_NODE_NAMES, GraphPhase

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "evaluation" / "datasets" / "v1" / "dataset.json"
RULES_PATH = ROOT / "evaluation" / "rules" / "v2" / "rules.json"
FAIRNESS_POLICY_PATH = ROOT / "evaluation" / "fairness" / "v1" / "policy.json"
FAIRNESS_PLAN_PATH = ROOT / "evaluation" / "plans" / "v1" / "comparison.json"
MODEL_SETTINGS_PATH = ROOT / "evaluation" / "models" / "v1" / "diagnosis-mock.json"
PROMPT_PATH = ROOT / "evaluation" / "prompts" / "v1" / "controlled-graph.json"
RECOVERY_FIXTURES_PATH = ROOT / "evaluation" / "recovery" / "v1" / "fixtures.json"
RESULT_ROOT = ROOT / "evaluation" / "results" / "controlled-graph" / "v1" / "run-001"


def suite() -> tuple[Any, Any, Any, Any, CandidateExecutionConfig]:
    dataset, rules, policy, plan = load_fair_suite(
        DATASET_PATH, RULES_PATH, FAIRNESS_POLICY_PATH, FAIRNESS_PLAN_PATH
    )
    profile = next(item for item in plan.baselines if item.kind == "controlled-langgraph")
    return (
        dataset,
        rules,
        policy,
        plan,
        CandidateExecutionConfig(profile, plan.tool_schema_versions),
    )


def test_controlled_graph_profile_binds_same_model_and_its_versioned_prompt() -> None:
    _, _, _, _, configuration = suite()
    assert content_sha256(load_json_object(MODEL_SETTINGS_PATH)) == (
        configuration.profile.model_settings_sha256
    )
    prompt = load_json_object(PROMPT_PATH)
    assert prompt["prompt_version"] == configuration.profile.prompt_version
    assert prompt["purpose"] == "DIAGNOSIS"
    assert prompt["interface"] == "langgraph"


def test_controlled_graph_runs_real_nodes_parallel_reads_gate_and_checkpoints() -> None:
    dataset, _, _, _, configuration = suite()
    system = ControlledGraphDiagnosisSystem()
    case = dataset.cases[0]
    result = system.evaluate(case, configuration)
    trace = system.traces[case.case_id]

    assert result["status"] == "handoff"
    assert result["diagnosis_top3"] == ["deployment-regression"]
    assert result["evidence_gate_outcome"] == "fail"
    assert result["outcome_reason_code"] == "EVIDENCE_GATE_INDEPENDENT_SOURCES_MISSING"
    assert result["tool_calls"] == 2
    assert result["input_tokens"] == 152
    assert result["output_tokens"] == 249
    assert result["cost_microusd"] == 0
    assert trace.node_authorizations == (
        "load_context",
        "plan",
        "execute_read_tools",
        "persist_evidence",
        "hypothesis",
        "evidence_gate",
        "human_handoff",
    )
    assert set(trace.node_authorizations) == DIAGNOSIS_NODE_NAMES
    assert len(trace.tool_calls) == 2
    assert trace.maximum_parallel_tools == 2
    assert trace.checkpoint_count >= 8
    assert trace.final_phase is GraphPhase.HUMAN_HANDOFF

    source = inspect.getsource(controlled_graph_module).casefold()
    assert "ground_truth" not in source
    assert "evaluation.scoring" not in source
    assert "incident_memory" not in source


def test_controlled_graph_rejects_non_graph_profile() -> None:
    dataset, _, _, plan, _ = suite()
    profile = next(item for item in plan.baselines if item.kind == "single-agent")
    configuration = CandidateExecutionConfig(profile, plan.tool_schema_versions)
    with pytest.raises(EvaluationContractError, match="exact predeclared profile"):
        ControlledGraphDiagnosisSystem().evaluate(dataset.cases[0], configuration)


def _clocks() -> tuple[Any, Any]:
    times = iter(
        datetime(2026, 10, 29, 11, 0, tzinfo=UTC) + timedelta(seconds=index) for index in range(4)
    )
    ticks = iter(index * 1_000_000 for index in range(24))
    return lambda: next(times), lambda: next(ticks)


def test_controlled_graph_runner_is_create_only_and_resource_bound(tmp_path: Path) -> None:
    clocks = _clocks()
    output = tmp_path / "graph"
    hashes = execute_controlled_graph_baseline(
        output_dir=output,
        code_revision="c" * 40,
        run_id="controlled-graph-test-001",
        wall_clock=clocks[0],
        duration_clock_ns=clocks[1],
    )

    _, rules, _, _, configuration = suite()
    diagnosis = DiagnosisRawResult.from_mapping(
        load_json_object(output / "diagnosis-raw.json"), rules=rules
    )
    recovery = RecoverySafetyRawResult.from_mapping(
        load_json_object(output / "recovery-safety-raw.json"), rules=rules
    )
    score = load_score_result(output / "safe-outcomes.json")
    assert diagnosis.metadata.model_id == "diagnosis-mock"
    assert diagnosis.metadata.model_settings_sha256 == configuration.profile.model_settings_sha256
    assert diagnosis.fingerprint == hashes[0]
    assert recovery.fingerprint == hashes[1]
    assert score.fingerprint == hashes[2]
    assert sum(case.tool_calls for case in diagnosis.cases) == 12
    assert sum(case.input_tokens for case in diagnosis.cases) == 912
    assert sum(case.output_tokens for case in diagnosis.cases) == 1484
    assert sum(case.cost_microusd for case in diagnosis.cases) == 0
    assert score.summary.correct_handoff_numerator == 0
    assert score.summary.handoff_attempt_denominator == 6
    assert score.summary.recovery_safe_outcome_numerator == 5
    assert score.summary.automated_recovery_numerator == 1
    assert score.summary.automated_recovery_denominator == 2

    with pytest.raises(EvaluationContractError, match="already exists"):
        execute_controlled_graph_baseline(
            output_dir=output,
            code_revision="c" * 40,
            run_id="controlled-graph-test-002",
        )


def test_committed_controlled_graph_result_is_bound_reproducible_and_exact() -> None:
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
    assert diagnosis.metadata.code_revision == "0fab551974a3d6e10adc7e84d1566a3045d60887"
    assert diagnosis.metadata.run_id == "controlled-graph-baseline-20261029-001"
    assert diagnosis.fingerprint == score.diagnosis_raw_sha256
    assert recovery.fingerprint == score.recovery_raw_sha256
    assert sum(case.tool_calls for case in diagnosis.cases) == 12
    assert sum(case.input_tokens for case in diagnosis.cases) == 912
    assert sum(case.output_tokens for case in diagnosis.cases) == 1484
    assert sum(case.cost_microusd for case in diagnosis.cases) == 0
    assert sum(case.duration_ms for case in diagnosis.cases) == 338
    assert score.summary.correct_handoff_numerator == 0
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
