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


class EvaluationCandidate(Protocol):
    """One explicitly versioned baseline implementation under evaluation."""

    def evaluate(self, case: EvaluationCase) -> Mapping[str, Any]:
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


def run_evaluation(
    dataset: EvaluationDataset,
    rules: EvaluationRules,
    candidate: EvaluationCandidate,
    metadata: EvaluationRunMetadata,
    *,
    clock: Callable[[], datetime] | None = None,
) -> RawEvaluationResult:
    """Run every case in stable order without loading evaluator-only Ground Truth."""
    ensure_dataset_rules_compatible(dataset, rules)
    now = (clock or (lambda: datetime.now(UTC)))()
    results: list[CandidateCaseResult] = []
    for case in dataset.cases:
        try:
            raw = candidate.evaluate(case)
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
    return RawEvaluationResult(
        metadata,
        dataset.dataset_version,
        dataset.fingerprint,
        rules.rules_version,
        rules.fingerprint,
        now,
        tuple(results),
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
