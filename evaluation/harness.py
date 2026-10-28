"""Deterministic, Ground-Truth-blind evaluation harness."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from evaluation.contracts import (
    CandidateCaseResult,
    EvaluationCase,
    EvaluationContractError,
    EvaluationDataset,
    EvaluationRules,
    EvaluationRunMetadata,
    RawEvaluationResult,
    canonical_json,
    ensure_dataset_rules_compatible,
    load_json_object,
)
from evaluation.fairness import (
    CandidateExecutionConfig,
    FairnessPlan,
    FairnessPolicy,
)


class EvaluationCandidate(Protocol):
    """One explicitly versioned baseline implementation under evaluation."""

    def evaluate(
        self, case: EvaluationCase, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        """Evaluate one label-free case and return the strict candidate result."""
        ...


def load_suite(dataset_path: Path, rules_path: Path) -> tuple[EvaluationDataset, EvaluationRules]:
    """Load and cross-bind one versioned dataset/rules pair."""
    rules = EvaluationRules.from_mapping(load_json_object(rules_path))
    dataset = EvaluationDataset.from_mapping(
        load_json_object(dataset_path), forbidden_fields=rules.forbidden_observation_fields
    )
    ensure_dataset_rules_compatible(dataset, rules)
    return dataset, rules


def load_fair_suite(
    dataset_path: Path,
    rules_path: Path,
    fairness_policy_path: Path,
    fairness_plan_path: Path,
) -> tuple[EvaluationDataset, EvaluationRules, FairnessPolicy, FairnessPlan]:
    """Load and cross-bind one dataset, rules, fairness policy, and concrete plan."""
    dataset, rules = load_suite(dataset_path, rules_path)
    policy = FairnessPolicy.from_mapping(load_json_object(fairness_policy_path))
    plan = FairnessPlan.from_mapping(
        load_json_object(fairness_plan_path), policy=policy, dataset=dataset, rules=rules
    )
    return dataset, rules, policy, plan


def run_evaluation(
    dataset: EvaluationDataset,
    rules: EvaluationRules,
    fairness_policy: FairnessPolicy,
    fairness_plan: FairnessPlan,
    candidate: EvaluationCandidate,
    metadata: EvaluationRunMetadata,
    *,
    clock: Callable[[], datetime] | None = None,
) -> RawEvaluationResult:
    """Run every case in stable order without loading evaluator-only Ground Truth."""
    ensure_dataset_rules_compatible(dataset, rules)
    if (
        fairness_plan.fairness_policy_version != fairness_policy.policy_version
        or fairness_plan.fairness_policy_sha256 != fairness_policy.fingerprint
        or fairness_plan.dataset_sha256 != dataset.fingerprint
        or fairness_plan.rules_sha256 != rules.fingerprint
    ):
        raise EvaluationContractError("evaluation inputs differ from the fairness plan")
    configuration = fairness_plan.execution_config(metadata)
    now = (clock or (lambda: datetime.now(UTC)))()
    results: list[CandidateCaseResult] = []
    for case in dataset.cases:
        try:
            raw = candidate.evaluate(case, configuration)
        except Exception:
            results.append(CandidateCaseResult.adapter_failure(case.case_id))
            continue
        try:
            results.append(
                CandidateCaseResult.from_mapping(raw, case_id=case.case_id, limits=rules.limits)
            )
        except EvaluationContractError as error:
            raise EvaluationContractError(
                f"candidate result violates the contract for case {case.case_id}"
            ) from error
    result_tuple = tuple(results)
    fairness_plan.enforce_aggregate_budget(configuration.profile, result_tuple)
    return RawEvaluationResult(
        metadata,
        dataset.dataset_version,
        dataset.fingerprint,
        rules.rules_version,
        rules.fingerprint,
        fairness_policy.policy_version,
        fairness_policy.fingerprint,
        fairness_plan.plan_version,
        fairness_plan.fingerprint,
        now,
        result_tuple,
    )


def write_raw_result(result: RawEvaluationResult, path: Path) -> str:
    """Create, never overwrite, one canonical raw-result artifact and return its hash."""
    payload = f"{canonical_json(result.to_mapping())}\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except FileExistsError as error:
        raise EvaluationContractError("raw evaluation result already exists") from error
    except OSError as error:
        raise EvaluationContractError("raw evaluation result cannot be persisted") from error
    return result.fingerprint
