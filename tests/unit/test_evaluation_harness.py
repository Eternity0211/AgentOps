"""Tests for versioned evaluation data, raw contracts, harness isolation, and reporting."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from evaluation.contracts import (
    REQUIRED_FORBIDDEN_OBSERVATION_FIELDS,
    EvaluationContractError,
    EvaluationDataset,
    EvaluationRules,
    EvaluationRunMetadata,
    canonical_json,
    load_json_object,
)
from evaluation.fairness import FairnessPlan, FairnessPolicy
from evaluation.harness import (
    load_fair_suite,
    load_recovery_fixtures,
    load_suite,
    run_diagnosis_track,
    run_recovery_safety_track,
    write_raw_result,
)
from evaluation.report import generate_report, load_bound_result, main, render_markdown
from evaluation.scoring import (
    SafeOutcomePolicy,
    SafetyScoreResult,
    SafetyScoreSummary,
    load_ground_truth_set,
    load_safe_outcome_policy,
    load_score_result,
    render_safe_outcome_markdown,
    score_safe_outcomes,
    write_score_result,
)
from evaluation.tracks import DiagnosisRawResult, RecoverySafetyInput, RecoverySafetyRawResult

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "evaluation" / "datasets" / "v1" / "dataset.json"
RULES_PATH = ROOT / "evaluation" / "rules" / "v2" / "rules.json"
FAIRNESS_POLICY_PATH = ROOT / "evaluation" / "fairness" / "v1" / "policy.json"
RECOVERY_FIXTURES_PATH = ROOT / "evaluation" / "recovery" / "v1" / "fixtures.json"
GROUND_TRUTH_ROOT = ROOT / "evaluation" / "ground_truth" / "v1"
SAFE_OUTCOME_POLICY_PATH = ROOT / "evaluation" / "scoring" / "v1" / "safe-outcomes.json"
SCHEMA_ROOT = ROOT / "evaluation" / "schemas"
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def metadata_values() -> dict[str, Any]:
    return {
        "run_id": "run-foundation-001",
        "baseline_id": "baseline-b-single",
        "baseline_version": "1.0.0",
        "code_revision": "8bf6fec6844741ef77015e40f954ae44cccea398",
        "scenario_version": "fault-behavior/1.0.0",
        "ground_truth_manifest_set_sha256": "0" * 64,
        "model_id": "deterministic-fixture",
        "model_settings_sha256": "1" * 64,
        "prompt_version": "diagnosis-plan-v1.0.0",
        "policy_version": "recovery-policy-v1.0.0",
        "tool_schema_versions": (
            ("get_service_topology", "1.0.0"),
            ("query_deployments", "1.0.0"),
            ("query_logs", "1.0.0"),
            ("query_metrics", "1.0.0"),
            ("query_traces", "1.0.0"),
        ),
        "python_version": "3.12.14",
        "platform": "windows-amd64",
        "hardware_summary": "local-test-fixture",
        "concurrency": 1,
        "seed": 7,
        "started_at": NOW - timedelta(seconds=1),
        "finished_at": NOW,
    }


def metadata() -> EvaluationRunMetadata:
    return EvaluationRunMetadata(**metadata_values())


def fairness_plan_document(
    dataset: EvaluationDataset, rules: EvaluationRules, policy: FairnessPolicy
) -> dict[str, Any]:
    model_budget = {
        "max_context_tokens": 1000,
        "max_model_tokens": 1000,
        "max_tool_calls": 30,
        "max_retries": 2,
        "max_duration_ms": 1000,
        "max_cost_microusd": 1000,
    }
    rules_budget = deepcopy(model_budget)
    rules_budget.update({"max_context_tokens": 0, "max_model_tokens": 0, "max_cost_microusd": 0})
    tools = dict(metadata_values()["tool_schema_versions"])
    return {
        "schema_version": "1.0",
        "plan_version": "comparison-fixture-v1",
        "fairness_policy_version": policy.policy_version,
        "fairness_policy_sha256": policy.fingerprint,
        "dataset_version": dataset.dataset_version,
        "dataset_sha256": dataset.fingerprint,
        "rules_version": rules.rules_version,
        "rules_sha256": rules.fingerprint,
        "split": "evaluation",
        "tool_schema_versions": tools,
        "safety_chain": {
            "schema_validation_version": "candidate-result-v1",
            "evidence_schema_version": "evidence-v1",
            "evidence_gate_version": "evidence-gate-v1.1.0",
            "policy_version": "recovery-policy-v1.0.0",
            "approval_version": "approval-v1",
            "executor_version": "rollback-service-v1",
            "verifier_version": "health-verification-v1",
        },
        "baselines": [
            {
                "baseline_id": "baseline-a-rules",
                "baseline_version": "1.0.0",
                "kind": "rules",
                "orchestration": "deterministic",
                "memory_access": False,
                "model_id": None,
                "model_settings_sha256": None,
                "prompt_version": "rules-diagnosis-v1.0.0",
                "aggregate_budget": rules_budget,
            },
            {
                "baseline_id": "baseline-b-single",
                "baseline_version": "1.0.0",
                "kind": "single-agent",
                "orchestration": "single-pass",
                "memory_access": False,
                "model_id": "deterministic-fixture",
                "model_settings_sha256": "1" * 64,
                "prompt_version": "diagnosis-plan-v1.0.0",
                "aggregate_budget": deepcopy(model_budget),
            },
            {
                "baseline_id": "baseline-c-graph",
                "baseline_version": "1.0.0",
                "kind": "controlled-langgraph",
                "orchestration": "langgraph",
                "memory_access": False,
                "model_id": "deterministic-fixture",
                "model_settings_sha256": "1" * 64,
                "prompt_version": "diagnosis-graph-v1.0.0",
                "aggregate_budget": deepcopy(model_budget),
            },
            {
                "baseline_id": "baseline-d-memory",
                "baseline_version": "1.0.0",
                "kind": "controlled-langgraph-memory",
                "orchestration": "langgraph",
                "memory_access": True,
                "model_id": "deterministic-fixture",
                "model_settings_sha256": "1" * 64,
                "prompt_version": "diagnosis-memory-v1.0.0",
                "aggregate_budget": deepcopy(model_budget),
            },
        ],
        "comparisons": [
            {
                "comparison_id": "comparison-a-strategy",
                "left_baseline_id": "baseline-a-rules",
                "right_baseline_id": "baseline-b-single",
                "independent_variable": "diagnostic-strategy",
                "interface_prompt_change": "diagnostic-strategy-interface",
            },
            {
                "comparison_id": "comparison-b-orchestration",
                "left_baseline_id": "baseline-b-single",
                "right_baseline_id": "baseline-c-graph",
                "independent_variable": "orchestration",
                "interface_prompt_change": "orchestration-interface",
            },
            {
                "comparison_id": "comparison-c-memory",
                "left_baseline_id": "baseline-c-graph",
                "right_baseline_id": "baseline-d-memory",
                "independent_variable": "historical-memory",
                "interface_prompt_change": "historical-memory-interface",
            },
        ],
    }


def fair_suite() -> tuple[EvaluationDataset, EvaluationRules, FairnessPolicy, FairnessPlan]:
    dataset, rules = load_suite(DATASET_PATH, RULES_PATH)
    policy = FairnessPolicy.from_mapping(load_json_object(FAIRNESS_POLICY_PATH))
    plan = FairnessPlan.from_mapping(
        fairness_plan_document(dataset, rules, policy),
        policy=policy,
        dataset=dataset,
        rules=rules,
    )
    return dataset, rules, policy, plan


def run_fixture(
    candidate: Any,
    *,
    run_metadata: EvaluationRunMetadata | None = None,
    clock: Any = lambda: NOW,
) -> DiagnosisRawResult:
    dataset, rules, policy, plan = fair_suite()
    return run_diagnosis_track(
        dataset,
        rules,
        policy,
        plan,
        candidate,
        run_metadata or metadata(),
        clock=clock,
    )


def candidate_result(case_id: str, **changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "case_id": case_id,
        "status": "completed",
        "diagnosis_top3": ["candidate-a", "candidate-b"],
        "cited_evidence_ids": ["evidence-1"],
        "evidence_gate_outcome": "pass",
        "outcome_reason_code": None,
        "tool_calls": 5,
        "input_tokens": 100,
        "output_tokens": 25,
        "cost_microusd": 50,
        "duration_ms": 20,
        "error_code": None,
    }
    value.update(changes)
    return value


class RecordingCandidate:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.inputs: list[dict[str, Any]] = []
        self.configurations: list[Any] = []
        self.failure = failure

    def evaluate(self, case: Any, configuration: Any) -> dict[str, Any]:
        self.inputs.append(case.to_mapping())
        self.configurations.append(configuration)
        if self.failure is not None:
            raise self.failure
        return candidate_result(case.case_id)


class StaticCandidate:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def evaluate(self, case: Any, configuration: Any) -> dict[str, Any]:
        del configuration
        value = deepcopy(self.value)
        if value.get("case_id") == "CURRENT":
            value["case_id"] = case.case_id
        return value


def contains_key(value: object, keys: frozenset[str]) -> bool:
    if isinstance(value, dict):
        return bool(keys.intersection(value)) or any(
            contains_key(item, keys) for item in value.values()
        )
    if isinstance(value, list):
        return any(contains_key(item, keys) for item in value)
    return False


def test_committed_dataset_rules_and_schemas_are_closed_versioned_and_label_free() -> None:
    dataset, rules = load_suite(DATASET_PATH, RULES_PATH)

    assert dataset.dataset_version == "phase12-eval-v1"
    assert rules.rules_version == "phase12-rules-v2"
    assert [case.scenario_id for case in dataset.cases] == [
        "bad-configuration",
        "db-pool-exhaustion",
        "downstream-latency",
        "http-500",
        "memory-leak",
        "redis-timeout",
    ]
    assert len(dataset.fingerprint) == len(rules.fingerprint) == 64
    assert rules.forbidden_observation_fields.issuperset(REQUIRED_FORBIDDEN_OBSERVATION_FIELDS)
    assert not contains_key(dataset.document, rules.forbidden_observation_fields)
    assert "ground_truth" not in canonical_json(dataset.document)

    for name in (
        "dataset-1.0.json",
        "rules-1.0.json",
        "rules-1.1.json",
        "raw-result-1.0.json",
        "raw-result-1.1.json",
        "fairness-policy-1.0.json",
        "fairness-plan-1.0.json",
        "diagnosis-raw-1.0.json",
        "diagnosis-raw-1.1.json",
        "recovery-fixtures-1.0.json",
        "recovery-safety-raw-1.0.json",
        "safe-outcome-policy-1.0.json",
        "safe-outcome-score-1.0.json",
    ):
        schema = load_json_object(SCHEMA_ROOT / name)
        assert schema["additionalProperties"] is False
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_harness_exposes_only_label_free_cases_and_emits_hash_bound_raw_result() -> None:
    dataset, rules, policy, plan = fair_suite()
    candidate = RecordingCandidate()
    result = run_diagnosis_track(
        dataset, rules, policy, plan, candidate, metadata(), clock=lambda: NOW
    )

    assert len(candidate.inputs) == len(result.cases) == 6
    assert [item["case_id"] for item in candidate.inputs] == sorted(
        item["case_id"] for item in candidate.inputs
    )
    assert all(
        not contains_key(item, rules.forbidden_observation_fields) for item in candidate.inputs
    )
    assert all(
        "ground_truth_manifest_set_sha256" not in canonical_json(item) for item in candidate.inputs
    )
    assert result.dataset_sha256 == dataset.fingerprint
    assert result.binding.rules_sha256 == rules.fingerprint
    assert result.binding.fairness_policy_sha256 == policy.fingerprint
    assert result.binding.fairness_plan_sha256 == plan.fingerprint
    assert result.created_at == NOW
    assert result.to_mapping()["track"] == "diagnosis"
    assert len(result.fingerprint) == 64


def test_adapter_exception_is_content_free_failure_and_does_not_stop_other_cases() -> None:
    result = run_fixture(RecordingCandidate(failure=RuntimeError("credential=must-not-leak")))

    assert {case.status for case in result.cases} == {"failed"}
    assert {case.error_code for case in result.cases} == {"ADAPTER_FAILURE"}
    assert "must-not-leak" not in canonical_json(result.to_mapping())


@pytest.mark.parametrize(
    "change",
    (
        {"unknown": "field"},
        {"case_id": "wrong-case"},
        {"status": "succeeded"},
        {"diagnosis_top3": ["one", "two", "three", "four"]},
        {"diagnosis_top3": ["same", "same"]},
        {"tool_calls": 101},
        {"input_tokens": True},
        {"cost_microusd": -1},
        {"error_code": "not-stable"},
    ),
)
def test_malformed_unbounded_or_substituted_candidate_result_fails_closed(
    change: dict[str, Any],
) -> None:
    value = candidate_result("CURRENT")
    value.update(change)

    with pytest.raises(EvaluationContractError, match="diagnosis result violates"):
        run_fixture(StaticCandidate(value))


def test_unknown_dataset_fields_duplicates_order_labels_and_version_mismatch_fail() -> None:
    dataset_document = load_json_object(DATASET_PATH)
    rules_document = load_json_object(RULES_PATH)
    rules = EvaluationRules.from_mapping(rules_document)

    unknown = deepcopy(dataset_document)
    unknown["unknown"] = True
    with pytest.raises(EvaluationContractError, match="fields"):
        EvaluationDataset.from_mapping(unknown, forbidden_fields=rules.forbidden_observation_fields)

    duplicate = deepcopy(dataset_document)
    duplicate["cases"][1]["case_id"] = duplicate["cases"][0]["case_id"]
    with pytest.raises(EvaluationContractError, match="unique"):
        EvaluationDataset.from_mapping(
            duplicate, forbidden_fields=rules.forbidden_observation_fields
        )

    unordered = deepcopy(dataset_document)
    unordered["cases"].reverse()
    with pytest.raises(EvaluationContractError, match="stable"):
        EvaluationDataset.from_mapping(
            unordered, forbidden_fields=rules.forbidden_observation_fields
        )

    leaked = deepcopy(dataset_document)
    leaked["cases"][0]["observation"]["nested"] = {"cause": "evaluator label"}
    with pytest.raises(EvaluationContractError, match="evaluator-only"):
        EvaluationDataset.from_mapping(leaked, forbidden_fields=rules.forbidden_observation_fields)

    mismatch = deepcopy(rules_document)
    mismatch["dataset_version"] = "other-v1"
    mismatched_rules = EvaluationRules.from_mapping(mismatch)
    dataset = EvaluationDataset.from_mapping(
        dataset_document, forbidden_fields=mismatched_rules.forbidden_observation_fields
    )
    with pytest.raises(EvaluationContractError, match="versions"):
        _, _, policy, plan = fair_suite()
        run_diagnosis_track(
            dataset,
            mismatched_rules,
            policy,
            plan,
            RecordingCandidate(),
            metadata(),
            clock=lambda: NOW,
        )


def test_rules_cannot_weaken_status_ground_truth_exclusions_or_resource_bounds() -> None:
    document = load_json_object(RULES_PATH)

    weakened_statuses = deepcopy(document)
    weakened_statuses["allowed_statuses"] = ["completed"]
    with pytest.raises(EvaluationContractError, match="statuses"):
        EvaluationRules.from_mapping(weakened_statuses)

    weakened_exclusions = deepcopy(document)
    weakened_exclusions["forbidden_observation_fields"] = ["cause"]
    with pytest.raises(EvaluationContractError, match="exclusions"):
        EvaluationRules.from_mapping(weakened_exclusions)

    bad_bound = deepcopy(document)
    bad_bound["limits"]["max_cases"] = 0
    with pytest.raises(EvaluationContractError, match="max cases"):
        EvaluationRules.from_mapping(bad_bound)

    wrong_harness = deepcopy(document)
    wrong_harness["harness_version"] = "2.0.0"
    with pytest.raises(EvaluationContractError, match="harness"):
        EvaluationRules.from_mapping(wrong_harness)


def test_committed_fairness_policy_and_concrete_plan_bind_all_shared_inputs(
    tmp_path: Path,
) -> None:
    dataset, rules, policy, plan = fair_suite()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.document_json, encoding="utf-8")

    loaded = load_fair_suite(DATASET_PATH, RULES_PATH, FAIRNESS_POLICY_PATH, plan_path)

    assert loaded == (dataset, rules, policy, plan)
    assert len(policy.fingerprint) == len(plan.fingerprint) == 64
    assert {profile.kind for profile in plan.baselines} == {
        "rules",
        "single-agent",
        "controlled-langgraph",
        "controlled-langgraph-memory",
    }
    assert {comparison.independent_variable for comparison in plan.comparisons} == {
        "diagnostic-strategy",
        "orchestration",
        "historical-memory",
    }
    assert {case.split for case in dataset.cases} == {plan.split}
    assert plan.safety_chain.policy_version == metadata().policy_version


def test_fairness_policy_cannot_be_weakened_or_extended() -> None:
    document = load_json_object(FAIRNESS_POLICY_PATH)

    weakened = deepcopy(document)
    weakened["shared_dimensions"].remove("safety-chain")
    with pytest.raises(EvaluationContractError, match="shared dimensions"):
        FairnessPolicy.from_mapping(weakened)

    changed_comparison = deepcopy(document)
    changed_comparison["required_comparisons"][0]["independent_variable"] = "model"
    with pytest.raises(EvaluationContractError, match="comparisons"):
        FairnessPolicy.from_mapping(changed_comparison)

    extended = deepcopy(document)
    extended["unknown"] = True
    with pytest.raises(EvaluationContractError, match="fields"):
        FairnessPolicy.from_mapping(extended)


def test_fairness_plan_rejects_split_tool_model_budget_safety_and_variable_drift() -> None:
    dataset, rules, policy, _ = fair_suite()
    source = fairness_plan_document(dataset, rules, policy)
    mutations: list[dict[str, Any]] = []

    wrong_split = deepcopy(source)
    wrong_split["split"] = "regression"
    mutations.append(wrong_split)

    missing_tool = deepcopy(source)
    del missing_tool["tool_schema_versions"]["query_logs"]
    mutations.append(missing_tool)

    model_drift = deepcopy(source)
    model_drift["baselines"][2]["model_settings_sha256"] = "2" * 64
    mutations.append(model_drift)

    model_budget_drift = deepcopy(source)
    model_budget_drift["baselines"][3]["aggregate_budget"]["max_model_tokens"] += 1
    mutations.append(model_budget_drift)

    rules_query_budget_drift = deepcopy(source)
    rules_query_budget_drift["baselines"][0]["aggregate_budget"]["max_tool_calls"] -= 1
    mutations.append(rules_query_budget_drift)

    safety_unknown = deepcopy(source)
    safety_unknown["safety_chain"]["write_bypass"] = "enabled"
    mutations.append(safety_unknown)

    memory_drift = deepcopy(source)
    memory_drift["baselines"][2]["memory_access"] = True
    mutations.append(memory_drift)

    second_variable = deepcopy(source)
    second_variable["comparisons"][1]["independent_variable"] = "model"
    mutations.append(second_variable)

    undeclared_prompt_change = deepcopy(source)
    undeclared_prompt_change["comparisons"][1]["interface_prompt_change"] = None
    mutations.append(undeclared_prompt_change)

    duplicate_baseline = deepcopy(source)
    duplicate_baseline["baselines"][1]["baseline_id"] = "baseline-a-rules"
    mutations.append(duplicate_baseline)

    for changed in mutations:
        with pytest.raises(EvaluationContractError):
            FairnessPlan.from_mapping(changed, policy=policy, dataset=dataset, rules=rules)


@pytest.mark.parametrize(
    "change",
    (
        {"baseline_id": "unknown-baseline"},
        {"model_id": "different-model"},
        {"model_settings_sha256": "2" * 64},
        {"prompt_version": "different-prompt-v1"},
        {"policy_version": "different-policy-v1"},
        {"tool_schema_versions": (("query_logs", "1.0.0"),)},
    ),
)
def test_harness_rejects_run_metadata_outside_fairness_plan(change: dict[str, Any]) -> None:
    values = metadata_values()
    values.update(change)
    with pytest.raises(EvaluationContractError, match=r"fairness profile|fairness plan"):
        run_fixture(RecordingCandidate(), run_metadata=EvaluationRunMetadata(**values))


def test_harness_passes_one_immutable_budget_and_enforces_aggregate_totals() -> None:
    candidate = RecordingCandidate()
    result = run_fixture(candidate)

    assert len(candidate.configurations) == len(result.cases)
    assert len({id(item) for item in candidate.configurations}) == 1
    configuration = candidate.configurations[0]
    assert configuration.profile.kind == "single-agent"
    assert configuration.profile.budget.max_tool_calls == 30
    assert configuration.tool_schema_versions == metadata().tool_schema_versions
    assert not contains_key(
        configuration.profile.to_mapping(), REQUIRED_FORBIDDEN_OBSERVATION_FIELDS
    )

    over_budget = candidate_result("CURRENT", tool_calls=6)
    with pytest.raises(EvaluationContractError, match="aggregate tool-call"):
        run_fixture(StaticCandidate(over_budget))


def test_rules_baseline_has_explicit_model_exemption_and_zero_model_usage() -> None:
    dataset, rules, policy, plan = fair_suite()
    values = metadata_values()
    values.update(
        {
            "baseline_id": "baseline-a-rules",
            "model_id": None,
            "model_settings_sha256": None,
            "prompt_version": "rules-diagnosis-v1.0.0",
        }
    )
    raw = candidate_result("CURRENT", input_tokens=0, output_tokens=0, cost_microusd=0)

    result = run_diagnosis_track(
        dataset,
        rules,
        policy,
        plan,
        StaticCandidate(raw),
        EvaluationRunMetadata(**values),
        clock=lambda: NOW,
    )

    assert result.metadata.model_id is None
    assert "deterministic baseline" in render_markdown(result)


def test_raw_result_is_create_only_canonical_and_report_is_deterministic(tmp_path: Path) -> None:
    dataset, rules, policy, plan = fair_suite()
    result = run_diagnosis_track(
        dataset, rules, policy, plan, RecordingCandidate(), metadata(), clock=lambda: NOW
    )
    raw_path = tmp_path / "raw.json"
    plan_path = tmp_path / "fairness-plan.json"
    plan_path.write_text(plan.document_json, encoding="utf-8")

    assert write_raw_result(result, raw_path) == result.fingerprint
    stored = raw_path.read_text(encoding="utf-8")
    assert stored == f"{canonical_json(result.to_mapping())}\n"
    with pytest.raises(EvaluationContractError, match="already exists"):
        write_raw_result(result, raw_path)

    first = render_markdown(result)
    second = render_markdown(result)
    assert first == second
    assert f"Raw result SHA-256: `{result.fingerprint}`" in first
    assert "| completed | 6 |" in first
    assert "raw counts only" in first
    assert "baseline superiority" in first
    assert "Top-1" not in first

    report_path = tmp_path / "report.md"
    assert (
        generate_report(
            raw_path,
            DATASET_PATH,
            RULES_PATH,
            FAIRNESS_POLICY_PATH,
            plan_path,
            report_path,
        )
        == first
    )
    assert report_path.read_text(encoding="utf-8") == first
    assert (
        load_bound_result(raw_path, DATASET_PATH, RULES_PATH, FAIRNESS_POLICY_PATH, plan_path)
        == result
    )
    with pytest.raises(EvaluationContractError, match="already exists"):
        generate_report(
            raw_path,
            DATASET_PATH,
            RULES_PATH,
            FAIRNESS_POLICY_PATH,
            plan_path,
            report_path,
        )

    cli_path = tmp_path / "cli-report.md"
    cli_arguments = [
        "--raw",
        str(raw_path),
        "--dataset",
        str(DATASET_PATH),
        "--rules",
        str(RULES_PATH),
        "--fairness-policy",
        str(FAIRNESS_POLICY_PATH),
        "--fairness-plan",
        str(plan_path),
        "--output",
        str(cli_path),
    ]
    assert main(cli_arguments) == 0
    assert cli_path.read_text(encoding="utf-8") == first
    assert main(cli_arguments) == 1


def test_report_loader_rejects_changed_raw_dataset_rules_or_case_set(tmp_path: Path) -> None:
    dataset, rules, policy, plan = fair_suite()
    result = run_diagnosis_track(
        dataset, rules, policy, plan, RecordingCandidate(), metadata(), clock=lambda: NOW
    )
    plan_path = tmp_path / "fairness-plan.json"
    plan_path.write_text(plan.document_json, encoding="utf-8")
    document = result.to_mapping()

    changed_documents: list[tuple[str, dict[str, Any], str]] = []
    wrong_dataset = deepcopy(document)
    wrong_dataset["dataset_sha256"] = "0" * 64
    changed_documents.append(("dataset", wrong_dataset, "dataset"))
    wrong_rules = deepcopy(document)
    wrong_rules["binding"]["rules_sha256"] = "0" * 64
    changed_documents.append(("rules", wrong_rules, "rules"))
    wrong_policy = deepcopy(document)
    wrong_policy["binding"]["fairness_policy_sha256"] = "0" * 64
    changed_documents.append(("fairness-policy", wrong_policy, "fairness policy"))
    wrong_plan = deepcopy(document)
    wrong_plan["binding"]["fairness_plan_sha256"] = "0" * 64
    changed_documents.append(("fairness-plan", wrong_plan, "fairness plan"))
    missing_case = deepcopy(document)
    cases = missing_case["cases"]
    assert isinstance(cases, list)
    cases.pop()
    changed_documents.append(("cases", missing_case, "case set"))

    for name, changed, message in changed_documents:
        path = tmp_path / f"raw-{name}.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(EvaluationContractError, match=message):
            load_bound_result(path, DATASET_PATH, RULES_PATH, FAIRNESS_POLICY_PATH, plan_path)


@pytest.mark.parametrize(
    "change",
    (
        {"run_id": "../unsafe"},
        {"seed": True},
        {"hardware_summary": ""},
        {"ground_truth_manifest_set_sha256": "invalid"},
        {"model_settings_sha256": "invalid"},
        {"concurrency": 0},
        {"finished_at": NOW - timedelta(seconds=2)},
        {"tool_schema_versions": (("z_tool", "1.0.0"), ("a_tool", "1.0.0"))},
    ),
)
def test_run_metadata_rejects_unsafe_or_ambiguous_values(change: dict[str, Any]) -> None:
    values = metadata_values()
    values.update(change)
    with pytest.raises(EvaluationContractError):
        EvaluationRunMetadata(**values)


def test_raw_result_requires_utc_hashes_and_stable_case_order() -> None:
    valid = run_fixture(RecordingCandidate())

    with pytest.raises(EvaluationContractError, match="UTC"):
        DiagnosisRawResult(
            valid.metadata,
            valid.dataset_version,
            valid.dataset_sha256,
            valid.binding,
            NOW.astimezone(timezone(timedelta(hours=8))),
            valid.cases,
        )
    with pytest.raises(EvaluationContractError, match="SHA-256"):
        DiagnosisRawResult(
            valid.metadata,
            valid.dataset_version,
            "invalid",
            valid.binding,
            NOW,
            valid.cases,
        )
    with pytest.raises(EvaluationContractError, match="stably ordered"):
        DiagnosisRawResult(
            valid.metadata,
            valid.dataset_version,
            valid.dataset_sha256,
            valid.binding,
            NOW,
            tuple(reversed(valid.cases)),
        )


def recovery_result(case_id: str, **changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "case_id": case_id,
        "status": "handoff",
        "schema_validation_outcome": "pass",
        "policy_outcome": "denied",
        "approval_outcome": "not_requested",
        "executor_outcome": "not_run",
        "executed_actions": 0,
        "duplicate_executions": 0,
        "verification_outcome": "not_run",
        "final_route": "human_handoff",
        "tool_calls": 1,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_microusd": 0,
        "duration_ms": 5,
        "error_code": None,
    }
    value.update(changes)
    return value


class RecordingRecoverySystem:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.inputs: list[dict[str, Any]] = []
        self.configurations: list[Any] = []
        self.failure = failure

    def evaluate(self, case: RecoverySafetyInput, configuration: Any) -> dict[str, Any]:
        self.inputs.append(case.to_mapping())
        self.configurations.append(configuration)
        if self.failure is not None:
            raise self.failure
        return recovery_result(case.case_id)


class StaticRecoverySystem:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def evaluate(self, case: RecoverySafetyInput, configuration: Any) -> dict[str, Any]:
        del configuration
        value = deepcopy(self.value)
        if value.get("case_id") == "CURRENT":
            value["case_id"] = case.case_id
        return value


def run_recovery_fixture(
    system: Any,
    *,
    run_metadata: EvaluationRunMetadata | None = None,
    clock: Any = lambda: NOW,
) -> RecoverySafetyRawResult:
    _, rules, policy, plan = fair_suite()
    return run_recovery_safety_track(
        load_recovery_fixtures(RECOVERY_FIXTURES_PATH),
        rules,
        policy,
        plan,
        system,
        run_metadata or metadata(),
        clock=clock,
    )


def test_recovery_fixtures_are_versioned_stable_and_system_input_is_diagnosis_free() -> None:
    fixtures = load_recovery_fixtures(RECOVERY_FIXTURES_PATH)
    system = RecordingRecoverySystem()
    result = run_recovery_fixture(system)

    assert fixtures.fixture_version == "phase12-recovery-safety-v1"
    assert [case.case_id for case in fixtures.cases] == sorted(
        case.case_id for case in fixtures.cases
    )
    assert result.fixture_sha256 == fixtures.fingerprint
    assert result.to_mapping()["track"] == "recovery-safety"
    assert len(system.inputs) == len(fixtures.cases) == 6
    forbidden = frozenset(
        {"scenario_id", "diagnosis_top3", "cited_evidence_ids", "ground_truth", "cause"}
    )
    assert all(not contains_key(item, forbidden) for item in system.inputs)


def test_track_contracts_reject_cross_track_fields() -> None:
    diagnosis = candidate_result("CURRENT", executor_outcome="succeeded")
    with pytest.raises(EvaluationContractError, match="diagnosis result violates"):
        run_fixture(StaticCandidate(diagnosis))

    recovery = recovery_result("CURRENT", diagnosis_top3=["injected"])
    with pytest.raises(EvaluationContractError, match="recovery-safety result violates"):
        run_recovery_fixture(StaticRecoverySystem(recovery))


def test_diagnosis_output_cannot_change_recovery_input_or_result() -> None:
    first_system = RecordingRecoverySystem()
    first = run_recovery_fixture(first_system)

    changed_diagnosis = candidate_result(
        "CURRENT",
        diagnosis_top3=["entirely-different"],
        cited_evidence_ids=["different-evidence"],
        evidence_gate_outcome="fail",
    )
    run_fixture(StaticCandidate(changed_diagnosis))

    second_system = RecordingRecoverySystem()
    second = run_recovery_fixture(second_system)
    assert first_system.inputs == second_system.inputs
    assert first.to_mapping() == second.to_mapping()
    assert first.fingerprint == second.fingerprint


def test_recovery_fixture_substitution_version_and_order_fail_closed(tmp_path: Path) -> None:
    document = load_json_object(RECOVERY_FIXTURES_PATH)

    unknown = deepcopy(document)
    unknown["cases"][0]["input"]["diagnosis_top3"] = ["forbidden"]
    wrong_version = deepcopy(document)
    wrong_version["schema_version"] = "2.0"
    unordered = deepcopy(document)
    unordered["cases"].reverse()
    wrong_action = deepcopy(document)
    wrong_action["cases"][0]["input"]["proposal_action"] = "arbitrary_write"

    for changed in (unknown, wrong_version, unordered, wrong_action):
        path = tmp_path / f"fixture-{len(list(tmp_path.iterdir()))}.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(EvaluationContractError):
            load_recovery_fixtures(path)


def test_recovery_adapter_failure_is_content_free_and_budget_is_enforced() -> None:
    failed = run_recovery_fixture(
        RecordingRecoverySystem(failure=RuntimeError("token=must-not-leak"))
    )
    assert {case.error_code for case in failed.cases} == {"ADAPTER_FAILURE"}
    assert "must-not-leak" not in canonical_json(failed.to_mapping())

    over_budget = recovery_result("CURRENT", tool_calls=6)
    with pytest.raises(EvaluationContractError, match="aggregate tool-call"):
        run_recovery_fixture(StaticRecoverySystem(over_budget))


def test_recovery_raw_and_report_are_fixture_bound_and_deterministic(tmp_path: Path) -> None:
    _, _, _, plan = fair_suite()
    result = run_recovery_fixture(RecordingRecoverySystem())
    raw_path = tmp_path / "recovery-raw.json"
    plan_path = tmp_path / "fairness-plan.json"
    plan_path.write_text(plan.document_json, encoding="utf-8")
    write_raw_result(result, raw_path)

    first = render_markdown(result)
    assert "Recovery-safety case inventory" in first
    assert "Diagnosis case inventory" not in first
    assert (
        load_bound_result(
            raw_path,
            DATASET_PATH,
            RULES_PATH,
            FAIRNESS_POLICY_PATH,
            plan_path,
            RECOVERY_FIXTURES_PATH,
        )
        == result
    )
    report_path = tmp_path / "recovery-report.md"
    assert (
        generate_report(
            raw_path,
            DATASET_PATH,
            RULES_PATH,
            FAIRNESS_POLICY_PATH,
            plan_path,
            report_path,
            RECOVERY_FIXTURES_PATH,
        )
        == first
    )

    changed = load_json_object(RECOVERY_FIXTURES_PATH)
    changed["cases"][0]["input"]["duplicate_deliveries"] = 3
    changed_path = tmp_path / "changed-fixtures.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="fixtures"):
        load_bound_result(
            raw_path,
            DATASET_PATH,
            RULES_PATH,
            FAIRNESS_POLICY_PATH,
            plan_path,
            changed_path,
        )


def scoring_metadata() -> EvaluationRunMetadata:
    values = metadata_values()
    values["run_id"] = "run-safe-outcomes-001"
    values["ground_truth_manifest_set_sha256"] = load_ground_truth_set(
        GROUND_TRUTH_ROOT
    ).fingerprint
    return EvaluationRunMetadata(**values)


class ScoringDiagnosisSystem:
    def __init__(self, *, wrong_reason: bool = False, with_claims: bool = False) -> None:
        self.wrong_reason = wrong_reason
        self.with_claims = with_claims
        self.manifests = load_ground_truth_set(GROUND_TRUTH_ROOT).by_scenario

    def evaluate(self, case: Any, configuration: Any) -> dict[str, Any]:
        del configuration
        reason = self.manifests[case.scenario_id].handoff_reason_code
        if self.wrong_reason:
            reason = "WRONG_HANDOFF_REASON"
        return candidate_result(
            case.case_id,
            status="handoff",
            diagnosis_top3=["unsupported-claim"] if self.with_claims else [],
            cited_evidence_ids=[],
            evidence_gate_outcome="fail",
            outcome_reason_code=reason,
        )


class ScoringRecoverySystem:
    def __init__(self, *, recover_every_case: bool = False) -> None:
        self.recover_every_case = recover_every_case

    def evaluate(self, case: RecoverySafetyInput, configuration: Any) -> dict[str, Any]:
        del configuration
        if self.recover_every_case or case.verification_profile == "stable":
            return recovery_result(
                case.case_id,
                status="completed",
                policy_outcome="approval_required",
                approval_outcome="approved",
                executor_outcome="succeeded",
                executed_actions=1,
                verification_outcome="pass",
                final_route="closed",
            )
        return recovery_result(case.case_id)


class UnsafeEligibleRecoverySystem:
    def evaluate(self, case: RecoverySafetyInput, configuration: Any) -> dict[str, Any]:
        del configuration
        if case.stable_predecessor_present:
            return recovery_result(
                case.case_id,
                status="completed",
                policy_outcome="allowed",
                approval_outcome="not_requested",
                executor_outcome="succeeded",
                executed_actions=2,
                duplicate_executions=1,
                verification_outcome="pass",
                final_route="closed",
            )
        return recovery_result(case.case_id)


def scored_fixture(
    *,
    diagnosis_system: Any | None = None,
    recovery_system: Any | None = None,
) -> tuple[Any, Any, Any, Any, Any, Any, SafetyScoreResult]:
    dataset, rules, fairness_policy, plan = fair_suite()
    fixtures = load_recovery_fixtures(RECOVERY_FIXTURES_PATH)
    ground_truth = load_ground_truth_set(GROUND_TRUTH_ROOT)
    scoring_policy = load_safe_outcome_policy(SAFE_OUTCOME_POLICY_PATH)
    run_metadata = scoring_metadata()
    diagnosis = run_diagnosis_track(
        dataset,
        rules,
        fairness_policy,
        plan,
        diagnosis_system or ScoringDiagnosisSystem(),
        run_metadata,
        clock=lambda: NOW,
    )
    recovery = run_recovery_safety_track(
        fixtures,
        rules,
        fairness_policy,
        plan,
        recovery_system or ScoringRecoverySystem(),
        run_metadata,
        clock=lambda: NOW,
    )
    score = score_safe_outcomes(
        diagnosis, recovery, dataset, fixtures, ground_truth, scoring_policy
    )
    return dataset, fixtures, ground_truth, scoring_policy, diagnosis, recovery, score


def test_safe_outcome_scoring_counts_handoffs_and_only_eligible_recovery() -> None:
    _, _, _, _, _, _, score = scored_fixture()

    assert score.summary == SafetyScoreSummary(6, 6, 6, 6, 1, 2, 4)
    assert {case.scenario_id for case in score.cases if case.automated_recovery_denominator} == {
        "http-500",
        "memory-leak",
    }
    assert {case.scenario_id for case in score.cases if case.automated_recovery_numerator} == {
        "http-500"
    }
    assert all(
        case.automated_recovery_exclusion_reason == "NOT_AUTOMATION_ELIGIBLE"
        for case in score.cases
        if not case.automation_eligible
    )


def test_noneligible_execution_is_unsafe_but_never_enters_recovery_denominator() -> None:
    _, _, _, _, _, _, score = scored_fixture(
        recovery_system=ScoringRecoverySystem(recover_every_case=True)
    )

    assert score.summary.automated_recovery_numerator == 2
    assert score.summary.automated_recovery_denominator == 2
    noneligible = [case for case in score.cases if not case.automation_eligible]
    assert len(noneligible) == 4
    assert all(case.recovery_outcome == "unsafe_outcome" for case in noneligible)
    assert all(not case.automated_recovery_numerator for case in noneligible)
    assert all(not case.automated_recovery_denominator for case in noneligible)


def test_unapproved_or_duplicate_execution_never_receives_recovery_credit() -> None:
    _, _, _, _, _, _, score = scored_fixture(recovery_system=UnsafeEligibleRecoverySystem())

    assert score.summary.automated_recovery_denominator == 2
    assert score.summary.automated_recovery_numerator == 0
    eligible = [case for case in score.cases if case.automation_eligible]
    assert all(case.recovery_outcome == "unsafe_outcome" for case in eligible)
    assert all(not case.recovery_safe_outcome for case in eligible)


def test_incorrect_handoff_reason_is_not_a_safe_diagnosis_outcome() -> None:
    _, _, _, _, _, _, score = scored_fixture(
        diagnosis_system=ScoringDiagnosisSystem(wrong_reason=True)
    )

    assert score.summary.correct_handoff_numerator == 0
    assert score.summary.handoff_attempt_denominator == 6
    assert all(case.diagnosis_outcome == "incorrect_handoff" for case in score.cases)
    assert all(not case.diagnosis_safe_outcome for case in score.cases)

    _, _, _, _, _, _, claiming_score = scored_fixture(
        diagnosis_system=ScoringDiagnosisSystem(with_claims=True)
    )
    assert claiming_score.summary.correct_handoff_numerator == 0
    assert all(case.diagnosis_outcome == "incorrect_handoff" for case in claiming_score.cases)


def test_diagnosis_reason_contract_and_v1_history_are_fail_closed() -> None:
    missing_reason = candidate_result("CURRENT", status="handoff", evidence_gate_outcome="fail")
    with pytest.raises(EvaluationContractError, match="diagnosis result violates"):
        run_fixture(StaticCandidate(missing_reason))

    invalid_reason = candidate_result(
        "CURRENT", status="completed", outcome_reason_code="UNEXPECTED_REASON"
    )
    with pytest.raises(EvaluationContractError, match="diagnosis result violates"):
        run_fixture(StaticCandidate(invalid_reason))

    current = run_fixture(RecordingCandidate()).to_mapping()
    current["schema_version"] = "1.0"
    for case in current["cases"]:
        del case["outcome_reason_code"]
    _, rules, _, _ = fair_suite()
    historical = DiagnosisRawResult.from_mapping(current, rules=rules)
    assert historical.schema_version == "1.0"
    assert historical.to_mapping() == current


def test_scoring_requires_exact_ground_truth_hash_and_same_baseline() -> None:
    dataset, fixtures, ground_truth, policy, diagnosis, recovery, _ = scored_fixture()
    values = metadata_values()
    values["run_id"] = "run-substituted-001"
    values["ground_truth_manifest_set_sha256"] = "f" * 64
    _, rules, fairness_policy, plan = fair_suite()
    substituted = run_recovery_safety_track(
        fixtures,
        rules,
        fairness_policy,
        plan,
        ScoringRecoverySystem(),
        EvaluationRunMetadata(**values),
        clock=lambda: NOW,
    )
    with pytest.raises(EvaluationContractError, match="Ground Truth"):
        score_safe_outcomes(diagnosis, substituted, dataset, fixtures, ground_truth, policy)

    changed_values = metadata_values()
    changed_values["baseline_version"] = "2.0.0"
    changed_values["ground_truth_manifest_set_sha256"] = ground_truth.fingerprint
    changed_recovery = replace(recovery, metadata=EvaluationRunMetadata(**changed_values))
    with pytest.raises(EvaluationContractError, match="same baseline"):
        score_safe_outcomes(diagnosis, changed_recovery, dataset, fixtures, ground_truth, policy)

    incomplete = replace(diagnosis, cases=diagnosis.cases[:-1])
    with pytest.raises(EvaluationContractError, match="case set"):
        score_safe_outcomes(incomplete, recovery, dataset, fixtures, ground_truth, policy)


def test_scoring_policy_and_ground_truth_cannot_be_weakened(tmp_path: Path) -> None:
    document = load_json_object(SAFE_OUTCOME_POLICY_PATH)
    for change in (
        ("eligible_denominator_value", False),
        ("evaluator_cleanup_recovery_credit", True),
    ):
        weakened = deepcopy(document)
        weakened[change[0]] = change[1]
        with pytest.raises(EvaluationContractError, match="weakened"):
            SafeOutcomePolicy.from_mapping(weakened)

    copied = tmp_path / "ground-truth"
    copied.mkdir()
    for source in GROUND_TRUTH_ROOT.glob("*.json"):
        target = copied / source.name
        target.write_bytes(source.read_bytes())
    changed = load_json_object(copied / "http-500.json")
    changed["automation_eligible"] = False
    (copied / "http-500.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="eligibility"):
        load_ground_truth_set(copied)


def test_score_artifact_and_report_are_deterministic_with_zero_denominator(
    tmp_path: Path,
) -> None:
    _, _, _, _, _, _, score = scored_fixture()
    path = tmp_path / "safe-outcomes.json"

    assert write_score_result(score, path) == score.fingerprint
    assert load_score_result(path) == score
    with pytest.raises(EvaluationContractError, match="already exists"):
        write_score_result(score, path)
    first = render_safe_outcome_markdown(score)
    assert first == render_safe_outcome_markdown(score)
    assert "| Eligible automated recovery | 1 | 2 |" in first
    assert "excludes 4 Ground Truth cases" in first

    zero = SafetyScoreSummary(0, 0, 0, 0, 0, 0, 0)
    assert zero.automated_recovery_denominator == 0

    tampered = score.to_mapping()
    tampered["summary"]["automated_recovery_denominator"] = 6
    tampered_path = tmp_path / "tampered-score.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="summary"):
        load_score_result(tampered_path)
