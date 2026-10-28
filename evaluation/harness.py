"""Deterministic, Ground-Truth-blind, track-separated evaluation harness."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from evaluation.contracts import (
    EvaluationCase,
    EvaluationContractError,
    EvaluationDataset,
    EvaluationRules,
    EvaluationRunMetadata,
    canonical_json,
    ensure_dataset_rules_compatible,
    load_json_object,
)
from evaluation.fairness import CandidateExecutionConfig, FairnessPlan, FairnessPolicy
from evaluation.tracks import (
    DiagnosisCaseResult,
    DiagnosisRawResult,
    RecoverySafetyCaseResult,
    RecoverySafetyFixtureSet,
    RecoverySafetyInput,
    RecoverySafetyRawResult,
    TrackBinding,
    TrackRawResult,
    utc_now,
)


class DiagnosisEvaluationSystem(Protocol):
    """One baseline diagnosis implementation evaluated on label-free observations."""

    def evaluate(
        self, case: EvaluationCase, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        """Return diagnosis output only; recovery fields are rejected."""
        ...


class RecoverySafetySystem(Protocol):
    """One safety-chain implementation evaluated independently of diagnosis output."""

    def evaluate(
        self, case: RecoverySafetyInput, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        """Return deterministic recovery-safety output only."""
        ...


def load_suite(dataset_path: Path, rules_path: Path) -> tuple[EvaluationDataset, EvaluationRules]:
    """Load and cross-bind one versioned diagnosis dataset/rules pair."""
    rules = EvaluationRules.from_mapping(load_json_object(rules_path))
    dataset = EvaluationDataset.from_mapping(
        load_json_object(dataset_path), forbidden_fields=rules.forbidden_observation_fields
    )
    ensure_dataset_rules_compatible(dataset, rules)
    return dataset, rules


def load_recovery_fixtures(path: Path) -> RecoverySafetyFixtureSet:
    """Load one closed, versioned set of evaluator-owned recovery inputs."""
    return RecoverySafetyFixtureSet.from_mapping(load_json_object(path))


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


def _validate_shared_inputs(
    rules: EvaluationRules,
    fairness_policy: FairnessPolicy,
    fairness_plan: FairnessPlan,
) -> None:
    if (
        fairness_plan.fairness_policy_version != fairness_policy.policy_version
        or fairness_plan.fairness_policy_sha256 != fairness_policy.fingerprint
        or fairness_plan.rules_version != rules.rules_version
        or fairness_plan.rules_sha256 != rules.fingerprint
    ):
        raise EvaluationContractError("evaluation inputs differ from the fairness plan")


def _binding(
    rules: EvaluationRules,
    fairness_policy: FairnessPolicy,
    fairness_plan: FairnessPlan,
) -> TrackBinding:
    return TrackBinding(
        rules.rules_version,
        rules.fingerprint,
        fairness_policy.policy_version,
        fairness_policy.fingerprint,
        fairness_plan.plan_version,
        fairness_plan.fingerprint,
    )


def run_diagnosis_track(
    dataset: EvaluationDataset,
    rules: EvaluationRules,
    fairness_policy: FairnessPolicy,
    fairness_plan: FairnessPlan,
    system: DiagnosisEvaluationSystem,
    metadata: EvaluationRunMetadata,
    *,
    clock: Callable[[], datetime] | None = None,
) -> DiagnosisRawResult:
    """Run diagnosis without admitting proposal, execution, or verification fields."""
    ensure_dataset_rules_compatible(dataset, rules)
    _validate_shared_inputs(rules, fairness_policy, fairness_plan)
    if (
        fairness_plan.dataset_version != dataset.dataset_version
        or fairness_plan.dataset_sha256 != dataset.fingerprint
    ):
        raise EvaluationContractError("diagnosis dataset differs from the fairness plan")
    configuration = fairness_plan.execution_config(metadata)
    results: list[DiagnosisCaseResult] = []
    for case in dataset.cases:
        try:
            raw = system.evaluate(case, configuration)
        except Exception:
            results.append(DiagnosisCaseResult.adapter_failure(case.case_id))
            continue
        try:
            results.append(
                DiagnosisCaseResult.from_mapping(raw, case_id=case.case_id, limits=rules.limits)
            )
        except EvaluationContractError as error:
            raise EvaluationContractError(
                f"diagnosis result violates the contract for case {case.case_id}"
            ) from error
    result_tuple = tuple(results)
    fairness_plan.enforce_aggregate_budget(configuration.profile, result_tuple)
    return DiagnosisRawResult(
        metadata,
        dataset.dataset_version,
        dataset.fingerprint,
        _binding(rules, fairness_policy, fairness_plan),
        (clock or utc_now)(),
        result_tuple,
    )


def run_recovery_safety_track(
    fixtures: RecoverySafetyFixtureSet,
    rules: EvaluationRules,
    fairness_policy: FairnessPolicy,
    fairness_plan: FairnessPlan,
    system: RecoverySafetySystem,
    metadata: EvaluationRunMetadata,
    *,
    clock: Callable[[], datetime] | None = None,
) -> RecoverySafetyRawResult:
    """Run fixed safety inputs without reading or accepting a diagnosis result."""
    _validate_shared_inputs(rules, fairness_policy, fairness_plan)
    configuration = fairness_plan.execution_config(metadata)
    results: list[RecoverySafetyCaseResult] = []
    for fixture in fixtures.cases:
        try:
            raw = system.evaluate(fixture.system_input, configuration)
        except Exception:
            results.append(RecoverySafetyCaseResult.adapter_failure(fixture.case_id))
            continue
        try:
            results.append(
                RecoverySafetyCaseResult.from_mapping(
                    raw, case_id=fixture.case_id, limits=rules.limits
                )
            )
        except EvaluationContractError as error:
            raise EvaluationContractError(
                f"recovery-safety result violates the contract for case {fixture.case_id}"
            ) from error
    result_tuple = tuple(results)
    fairness_plan.enforce_aggregate_budget(configuration.profile, result_tuple)
    return RecoverySafetyRawResult(
        metadata,
        fixtures.fixture_version,
        fixtures.fingerprint,
        _binding(rules, fairness_policy, fairness_plan),
        (clock or utc_now)(),
        result_tuple,
    )


def write_raw_result(result: TrackRawResult, path: Path) -> str:
    """Create, never overwrite, one canonical track artifact and return its hash."""
    payload = f"{canonical_json(result.to_mapping())}\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except FileExistsError as error:
        raise EvaluationContractError("raw evaluation result already exists") from error
    except OSError as error:
        raise EvaluationContractError("raw evaluation result cannot be persisted") from error
    return result.fingerprint
