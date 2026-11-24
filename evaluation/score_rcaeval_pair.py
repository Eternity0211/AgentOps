"""Paired service-localization scorer for the frozen RCAEval protocol."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from evaluation.paired_comparison import (
    ComparisonSuiteRequest,
    ComparisonSuiteResult,
    ImprovementDirection,
    MetricComparisonRequest,
    MetricKind,
    PairedValue,
    score_suite,
)
from evaluation.rcaeval_contract import (
    AnswerSet,
    EvaluationBudget,
    RcaEvalProtocol,
    StrictModel,
    TaskIndex,
    load_protocol,
    protocol_sha256,
)


class ServiceLocalizationOutput(StrictModel):
    schema_version: Literal["service-localization-output/1.0.0"]
    case_id: str = Field(pattern=r"^re2-(ob|tt)-[0-9a-f]{16}$")
    ranked_services: tuple[str, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_services(self) -> ServiceLocalizationOutput:
        if len(set(self.ranked_services)) != len(self.ranked_services):
            raise ValueError("ranked services must be unique")
        return self


class RunFailure(StrictModel):
    case_id: str
    reason: Literal["TIMEOUT", "REFUSAL", "INVALID_OUTPUT", "DEPENDENCY_FAILURE"]


class LocalizationRun(StrictModel):
    schema_version: Literal["rcaeval-localization-run/1.0.0"]
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    arm: Literal["BASELINE", "CANDIDATE"]
    split_role: Literal["DEVELOPMENT", "HOLDOUT"]
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: EvaluationBudget
    critical_safety_gate_passed: bool
    cost_latency_gate_passed: bool
    outputs: tuple[ServiceLocalizationOutput, ...]
    failures: tuple[RunFailure, ...]

    @model_validator(mode="after")
    def unique_outcomes(self) -> LocalizationRun:
        identifiers = [item.case_id for item in self.outputs] + [
            item.case_id for item in self.failures
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("case outcomes must be unique across outputs and failures")
        return self


class LocalizationSummary(StrictModel):
    total_cases: int = Field(gt=0)
    valid_outputs: int = Field(ge=0)
    failures: int = Field(ge=0)
    missing: int = Field(ge=0)
    top_1_correct: int = Field(ge=0)
    top_3_correct: int = Field(ge=0)


class RcaEvalPairResult(StrictModel):
    schema_version: Literal["rcaeval-paired-result/1.0.0"]
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_role: Literal["DEVELOPMENT", "HOLDOUT"]
    baseline_run_id: str
    candidate_run_id: str
    baseline: LocalizationSummary
    candidate: LocalizationSummary
    comparison: ComparisonSuiteResult


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _outcome_map(run: LocalizationRun) -> dict[str, ServiceLocalizationOutput]:
    return {item.case_id: item for item in run.outputs}


def score_pair(
    *,
    protocol: RcaEvalProtocol,
    task_index: TaskIndex,
    task_index_hash: str,
    answers: AnswerSet,
    baseline: LocalizationRun,
    candidate: LocalizationRun,
) -> RcaEvalPairResult:
    expected_protocol_hash = protocol_sha256(protocol)
    bindings = {
        task_index.protocol_sha256,
        answers.protocol_sha256,
        baseline.protocol_sha256,
        candidate.protocol_sha256,
    }
    if bindings != {expected_protocol_hash}:
        raise ValueError("protocol binding mismatch")
    if (
        baseline.task_index_sha256 != task_index_hash
        or candidate.task_index_sha256 != task_index_hash
    ):
        raise ValueError("task-index binding mismatch")
    if baseline.arm != "BASELINE" or candidate.arm != "CANDIDATE":
        raise ValueError("run arms are not a baseline/candidate pair")
    if baseline.split_role != candidate.split_role:
        raise ValueError("run split roles differ")
    if baseline.budget != protocol.budget or candidate.budget != protocol.budget:
        raise ValueError("run budgets differ from the frozen protocol")
    tasks = {
        item.case_id: item for item in task_index.tasks if item.split_role == baseline.split_role
    }
    labels = {item.case_id: item.root_cause_service for item in answers.answers}
    if set(tasks) != set(labels).intersection(tasks):
        raise ValueError("answer set does not cover the selected task split")
    known = set(tasks)
    for run in (baseline, candidate):
        observed = {item.case_id for item in run.outputs} | {item.case_id for item in run.failures}
        unknown = observed - known
        if unknown:
            raise ValueError("run contains an unknown case")
        for output in run.outputs:
            candidates = set(tasks[output.case_id].candidate_services)
            if not set(output.ranked_services).issubset(candidates):
                raise ValueError("run ranks a service outside the frozen candidate set")

    baseline_outputs = _outcome_map(baseline)
    candidate_outputs = _outcome_map(candidate)
    pair_values: dict[str, list[PairedValue]] = {"service_top_1": [], "service_top_3": []}
    counts: dict[str, dict[str, int]] = {
        "BASELINE": {"top1": 0, "top3": 0},
        "CANDIDATE": {"top1": 0, "top3": 0},
    }
    for case_id in sorted(known):
        label = labels[case_id]
        left = baseline_outputs.get(case_id)
        right = candidate_outputs.get(case_id)
        left_top1 = int(left is not None and left.ranked_services[0] == label)
        right_top1 = int(right is not None and right.ranked_services[0] == label)
        left_top3 = int(left is not None and label in left.ranked_services[:3])
        right_top3 = int(right is not None and label in right.ranked_services[:3])
        counts["BASELINE"]["top1"] += left_top1
        counts["BASELINE"]["top3"] += left_top3
        counts["CANDIDATE"]["top1"] += right_top1
        counts["CANDIDATE"]["top3"] += right_top3
        pair_values["service_top_1"].append(
            PairedValue(pair_id=case_id, baseline=left_top1, candidate=right_top1)
        )
        pair_values["service_top_3"].append(
            PairedValue(pair_id=case_id, baseline=left_top3, candidate=right_top3)
        )
    metrics = tuple(
        MetricComparisonRequest(
            metric_id=metric_id,
            kind=MetricKind.BINARY,
            direction=ImprovementDirection.HIGHER,
            minimum_relevant_effect=protocol.scoring.minimum_relevant_effect,
            failure_policy=(
                "Missing, failed, and invalid cases are scored as service-localization misses."
            ),
            pairs=tuple(pair_values[metric_id]),
            bootstrap_iterations=protocol.scoring.bootstrap_iterations,
            seed=protocol.scoring.bootstrap_seed + offset,
        )
        for offset, metric_id in enumerate(protocol.scoring.primary_metrics)
    )
    comparison = score_suite(
        ComparisonSuiteRequest(
            schema_version="paired-comparison-request/1.0.0",
            suite_id=f"rcaeval-{baseline.split_role.lower()}-{baseline.run_id}-{candidate.run_id}",
            confidence_level=0.95,
            critical_safety_gate_passed=(
                baseline.critical_safety_gate_passed and candidate.critical_safety_gate_passed
            ),
            cost_latency_gate_passed=(
                baseline.cost_latency_gate_passed and candidate.cost_latency_gate_passed
            ),
            metrics=metrics,
        )
    )

    def summary(run: LocalizationRun, arm: Literal["BASELINE", "CANDIDATE"]) -> LocalizationSummary:
        return LocalizationSummary(
            total_cases=len(known),
            valid_outputs=len(run.outputs),
            failures=len(run.failures),
            missing=len(known) - len(run.outputs) - len(run.failures),
            top_1_correct=counts[arm]["top1"],
            top_3_correct=counts[arm]["top3"],
        )

    return RcaEvalPairResult(
        schema_version="rcaeval-paired-result/1.0.0",
        protocol_sha256=expected_protocol_hash,
        task_index_sha256=task_index_hash,
        split_role=baseline.split_role,
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        baseline=summary(baseline, "BASELINE"),
        candidate=summary(candidate, "CANDIDATE"),
        comparison=comparison,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--task-index", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("score output already exists")
    result = score_pair(
        protocol=load_protocol(args.protocol),
        task_index=TaskIndex.model_validate_json(args.task_index.read_bytes()),
        task_index_hash=_file_sha256(args.task_index),
        answers=AnswerSet.model_validate_json(args.answers.read_bytes()),
        baseline=LocalizationRun.model_validate_json(args.baseline.read_bytes()),
        candidate=LocalizationRun.model_validate_json(args.candidate.read_bytes()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
