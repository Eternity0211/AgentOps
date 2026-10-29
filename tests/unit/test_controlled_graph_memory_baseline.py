"""Controlled graph plus historical-memory baseline tests."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from evaluation.baselines import controlled_graph_memory as memory_module
from evaluation.baselines.controlled_graph import ControlledGraphDiagnosisSystem
from evaluation.baselines.controlled_graph_memory import (
    ControlledGraphMemoryDiagnosisSystem,
    HistoricalMemoryIndex,
)
from evaluation.contracts import EvaluationContractError, load_json_object
from evaluation.fairness import CandidateExecutionConfig
from evaluation.harness import load_fair_suite
from evaluation.report import load_bound_result, render_markdown
from evaluation.run_controlled_graph_memory_baseline import (
    execute_controlled_graph_memory_baseline,
)
from evaluation.scoring import load_score_result, render_safe_outcome_markdown
from evaluation.tracks import DiagnosisRawResult, RecoverySafetyRawResult

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "evaluation" / "datasets" / "v1" / "dataset.json"
RULES_PATH = ROOT / "evaluation" / "rules" / "v2" / "rules.json"
FAIRNESS_POLICY_PATH = ROOT / "evaluation" / "fairness" / "v1" / "policy.json"
FAIRNESS_PLAN_PATH = ROOT / "evaluation" / "plans" / "v1" / "comparison.json"
MEMORY_PATH = ROOT / "evaluation" / "memory" / "v1" / "references.json"
RECOVERY_FIXTURES_PATH = ROOT / "evaluation" / "recovery" / "v1" / "fixtures.json"
RESULT_ROOT = ROOT / "evaluation" / "results" / "controlled-graph-memory" / "v1" / "run-001"


def suite() -> tuple[Any, Any, Any, Any, CandidateExecutionConfig]:
    dataset, rules, policy, plan = load_fair_suite(
        DATASET_PATH, RULES_PATH, FAIRNESS_POLICY_PATH, FAIRNESS_PLAN_PATH
    )
    profile = next(item for item in plan.baselines if item.kind == "controlled-langgraph-memory")
    return (
        dataset,
        rules,
        policy,
        plan,
        CandidateExecutionConfig(profile, plan.tool_schema_versions),
    )


def test_historical_memory_is_versioned_ordered_advisory_and_ground_truth_blind() -> None:
    index = HistoricalMemoryIndex()
    assert len(index.records) == 3
    assert [record.reference_id for record in index.records] == sorted(
        record.reference_id for record in index.records
    )
    assert {record.trust for record in index.records} == {"HISTORICAL_REFERENCE"}
    assert len(index.fingerprint) == 64
    source = inspect.getsource(memory_module).casefold()
    assert "ground_truth" not in source
    assert "evaluation.scoring" not in source


def test_memory_retrieval_uses_observation_text_not_current_scenario_identity() -> None:
    dataset, _, _, _, configuration = suite()
    case = dataset.cases[0]
    system = ControlledGraphMemoryDiagnosisSystem()
    first = system.evaluate(case, configuration)
    first_trace = system.traces[case.case_id]
    changed = replace(case, scenario_id="opaque-current-case")
    second = system.evaluate(changed, configuration)
    second_trace = system.traces[case.case_id]

    assert first == second
    assert first_trace.memory_reference_ids == second_trace.memory_reference_ids
    assert first_trace.memory_reference_ids
    assert first["cited_evidence_ids"] == [
        f"observation-{case.case_id}-1-{case.observation.signals[0].source}"
    ]
    assert all(not evidence_id.startswith("ref-") for evidence_id in first["cited_evidence_ids"])


def test_memory_is_the_only_profile_difference_and_does_not_change_mock_output() -> None:
    dataset, _, _, plan, memory_configuration = suite()
    graph_profile = next(item for item in plan.baselines if item.kind == "controlled-langgraph")
    graph_configuration = CandidateExecutionConfig(graph_profile, plan.tool_schema_versions)
    case = dataset.cases[3]
    graph_result = ControlledGraphDiagnosisSystem().evaluate(case, graph_configuration)
    memory_system = ControlledGraphMemoryDiagnosisSystem()
    memory_result = memory_system.evaluate(case, memory_configuration)

    for field in (
        "status",
        "diagnosis_top3",
        "cited_evidence_ids",
        "evidence_gate_outcome",
        "outcome_reason_code",
        "tool_calls",
        "output_tokens",
        "cost_microusd",
    ):
        assert memory_result[field] == graph_result[field]
    assert memory_result["input_tokens"] > graph_result["input_tokens"]
    assert memory_system.traces[case.case_id].memory_reference_ids


def test_memory_contract_rejects_nonhistorical_records_and_wrong_profile(tmp_path: Path) -> None:
    changed = load_json_object(MEMORY_PATH)
    changed["records"][0]["trust"] = "DIRECT_OBSERVATION"
    path = tmp_path / "memory.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="closed and advisory"):
        HistoricalMemoryIndex(path)

    dataset, _, _, plan, _ = suite()
    graph_profile = next(item for item in plan.baselines if item.kind == "controlled-langgraph")
    configuration = CandidateExecutionConfig(graph_profile, plan.tool_schema_versions)
    with pytest.raises(EvaluationContractError, match="exact predeclared profile"):
        ControlledGraphMemoryDiagnosisSystem().evaluate(dataset.cases[0], configuration)


def _clocks() -> tuple[Any, Any]:
    times = iter(
        datetime(2026, 10, 29, 12, 0, tzinfo=UTC) + timedelta(seconds=index) for index in range(4)
    )
    ticks = iter(index * 1_000_000 for index in range(24))
    return lambda: next(times), lambda: next(ticks)


def test_memory_runner_is_create_only_and_preserves_shared_safety_scores(tmp_path: Path) -> None:
    clocks = _clocks()
    output = tmp_path / "memory"
    hashes = execute_controlled_graph_memory_baseline(
        output_dir=output,
        code_revision="d" * 40,
        run_id="controlled-memory-test-001",
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
    assert diagnosis.metadata.model_settings_sha256 == configuration.profile.model_settings_sha256
    assert diagnosis.fingerprint == hashes[0]
    assert recovery.fingerprint == hashes[1]
    assert score.fingerprint == hashes[2]
    assert sum(case.tool_calls for case in diagnosis.cases) == 12
    assert sum(case.input_tokens for case in diagnosis.cases) > 912
    assert sum(case.output_tokens for case in diagnosis.cases) == 1484
    assert sum(case.cost_microusd for case in diagnosis.cases) == 0
    assert score.summary.correct_handoff_numerator == 0
    assert score.summary.handoff_attempt_denominator == 6
    assert score.summary.recovery_safe_outcome_numerator == 5
    assert score.summary.automated_recovery_numerator == 1
    assert score.summary.automated_recovery_denominator == 2

    with pytest.raises(EvaluationContractError, match="already exists"):
        execute_controlled_graph_memory_baseline(
            output_dir=output,
            code_revision="d" * 40,
            run_id="controlled-memory-test-002",
        )


def test_committed_memory_result_is_bound_reproducible_and_exact() -> None:
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
    assert diagnosis.metadata.code_revision == "70f53d64f1f3a3fe681f1c18473f6d1c4ca61c65"
    assert diagnosis.metadata.run_id == "controlled-graph-memory-baseline-20261029-001"
    assert diagnosis.fingerprint == score.diagnosis_raw_sha256
    assert recovery.fingerprint == score.recovery_raw_sha256
    assert sum(case.tool_calls for case in diagnosis.cases) == 12
    assert sum(case.input_tokens for case in diagnosis.cases) == 1104
    assert sum(case.output_tokens for case in diagnosis.cases) == 1484
    assert sum(case.cost_microusd for case in diagnosis.cases) == 0
    assert sum(case.duration_ms for case in diagnosis.cases) == 365
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
