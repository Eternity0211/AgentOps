"""Tests for versioned evaluation data, raw contracts, harness isolation, and reporting."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from evaluation.contracts import (
    HARNESS_VERSION,
    REQUIRED_FORBIDDEN_OBSERVATION_FIELDS,
    EvaluationContractError,
    EvaluationDataset,
    EvaluationRules,
    EvaluationRunMetadata,
    RawEvaluationResult,
    canonical_json,
    load_json_object,
)
from evaluation.harness import load_suite, run_evaluation, write_raw_result
from evaluation.report import generate_report, load_bound_result, main, render_markdown

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "evaluation" / "datasets" / "v1" / "dataset.json"
RULES_PATH = ROOT / "evaluation" / "rules" / "v1" / "rules.json"
SCHEMA_ROOT = ROOT / "evaluation" / "schemas"
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def metadata_values() -> dict[str, Any]:
    return {
        "run_id": "run-foundation-001",
        "baseline_id": "contract-fixture",
        "baseline_version": "1.0.0",
        "code_revision": "8bf6fec6844741ef77015e40f954ae44cccea398",
        "scenario_version": "fault-behavior/1.0.0",
        "ground_truth_manifest_set_sha256": "0" * 64,
        "model_id": "deterministic-fixture",
        "model_settings_sha256": "1" * 64,
        "prompt_version": "diagnosis-plan/1.0.0",
        "policy_version": "recovery-policy/1.0.0",
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


def candidate_result(case_id: str, **changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "case_id": case_id,
        "status": "completed",
        "diagnosis_top3": ["candidate-a", "candidate-b"],
        "cited_evidence_ids": ["evidence-1"],
        "proposed_action": None,
        "executed_actions": 0,
        "verification_outcome": "not_run",
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
        self.failure = failure

    def evaluate(self, case: Any) -> dict[str, Any]:
        self.inputs.append(case.to_mapping())
        if self.failure is not None:
            raise self.failure
        return candidate_result(case.case_id)


class StaticCandidate:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def evaluate(self, case: Any) -> dict[str, Any]:
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
    assert rules.rules_version == "phase12-rules-v1"
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

    for name in ("dataset-1.0.json", "rules-1.0.json", "raw-result-1.0.json"):
        schema = load_json_object(SCHEMA_ROOT / name)
        assert schema["additionalProperties"] is False
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_harness_exposes_only_label_free_cases_and_emits_hash_bound_raw_result() -> None:
    dataset, rules = load_suite(DATASET_PATH, RULES_PATH)
    candidate = RecordingCandidate()
    result = run_evaluation(dataset, rules, candidate, metadata(), clock=lambda: NOW)

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
    assert result.rules_sha256 == rules.fingerprint
    assert result.created_at == NOW
    assert result.to_mapping()["harness_version"] == HARNESS_VERSION
    assert len(result.fingerprint) == 64


def test_adapter_exception_is_content_free_failure_and_does_not_stop_other_cases() -> None:
    dataset, rules = load_suite(DATASET_PATH, RULES_PATH)
    result = run_evaluation(
        dataset,
        rules,
        RecordingCandidate(failure=RuntimeError("credential=must-not-leak")),
        metadata(),
        clock=lambda: NOW,
    )

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
    dataset, rules = load_suite(DATASET_PATH, RULES_PATH)
    value = candidate_result("CURRENT")
    value.update(change)

    with pytest.raises(EvaluationContractError, match="candidate result violates"):
        run_evaluation(dataset, rules, StaticCandidate(value), metadata(), clock=lambda: NOW)


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
        run_evaluation(
            dataset, mismatched_rules, RecordingCandidate(), metadata(), clock=lambda: NOW
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


def test_raw_result_is_create_only_canonical_and_report_is_deterministic(tmp_path: Path) -> None:
    dataset, rules = load_suite(DATASET_PATH, RULES_PATH)
    result = run_evaluation(dataset, rules, RecordingCandidate(), metadata(), clock=lambda: NOW)
    raw_path = tmp_path / "raw.json"

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
    assert generate_report(raw_path, DATASET_PATH, RULES_PATH, report_path) == first
    assert report_path.read_text(encoding="utf-8") == first
    assert load_bound_result(raw_path, DATASET_PATH, RULES_PATH) == result
    with pytest.raises(EvaluationContractError, match="already exists"):
        generate_report(raw_path, DATASET_PATH, RULES_PATH, report_path)

    cli_path = tmp_path / "cli-report.md"
    cli_arguments = [
        "--raw",
        str(raw_path),
        "--dataset",
        str(DATASET_PATH),
        "--rules",
        str(RULES_PATH),
        "--output",
        str(cli_path),
    ]
    assert main(cli_arguments) == 0
    assert cli_path.read_text(encoding="utf-8") == first
    assert main(cli_arguments) == 1


def test_report_loader_rejects_changed_raw_dataset_rules_or_case_set(tmp_path: Path) -> None:
    dataset, rules = load_suite(DATASET_PATH, RULES_PATH)
    result = run_evaluation(dataset, rules, RecordingCandidate(), metadata(), clock=lambda: NOW)
    document = result.to_mapping()

    changed_documents: list[tuple[str, dict[str, Any], str]] = []
    wrong_dataset = deepcopy(document)
    wrong_dataset["dataset_sha256"] = "0" * 64
    changed_documents.append(("dataset", wrong_dataset, "dataset"))
    wrong_rules = deepcopy(document)
    wrong_rules["rules_sha256"] = "0" * 64
    changed_documents.append(("rules", wrong_rules, "rules"))
    missing_case = deepcopy(document)
    cases = missing_case["cases"]
    assert isinstance(cases, list)
    cases.pop()
    changed_documents.append(("cases", missing_case, "case set"))

    for name, changed, message in changed_documents:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(EvaluationContractError, match=message):
            load_bound_result(path, DATASET_PATH, RULES_PATH)


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
    dataset, rules = load_suite(DATASET_PATH, RULES_PATH)
    valid = run_evaluation(dataset, rules, RecordingCandidate(), metadata(), clock=lambda: NOW)

    with pytest.raises(EvaluationContractError, match="UTC"):
        RawEvaluationResult(
            valid.metadata,
            valid.dataset_version,
            valid.dataset_sha256,
            valid.rules_version,
            valid.rules_sha256,
            NOW.astimezone(timezone(timedelta(hours=8))),
            valid.cases,
        )
    with pytest.raises(EvaluationContractError, match="SHA-256"):
        RawEvaluationResult(
            valid.metadata,
            valid.dataset_version,
            "invalid",
            valid.rules_version,
            valid.rules_sha256,
            NOW,
            valid.cases,
        )
    with pytest.raises(EvaluationContractError, match="stably ordered"):
        RawEvaluationResult(
            valid.metadata,
            valid.dataset_version,
            valid.dataset_sha256,
            valid.rules_version,
            valid.rules_sha256,
            NOW,
            tuple(reversed(valid.cases)),
        )
