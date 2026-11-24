"""Final quality, safety, and resource scoring for a frozen RCAEval pair."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from pydantic import Field

from evaluation.paired_comparison import (
    ComparisonSuiteRequest,
    ComparisonSuiteResult,
    ImprovementDirection,
    MetricComparisonRequest,
    MetricKind,
    PairedValue,
    score_suite,
)
from evaluation.rcaeval_contract import AnswerSet, StrictModel, TaskIndex, load_protocol
from evaluation.run_rcaeval_pair import CaseOutcome, _sha256, _validate_plan
from evaluation.score_rcaeval_pair import (
    LocalizationRun,
    RcaEvalPairResult,
    score_pair,
)

RESOURCE_FIELDS = (
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "cost_upper_bound_nanousd",
)


class RcaEvalConfirmationResult(StrictModel):
    schema_version: Literal["rcaeval-confirmation-result/1.0.0"]
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    critical_safety_gate_passed: bool
    resource_gate_passed: bool
    complete_case_pairs: int = Field(ge=0)
    quality: RcaEvalPairResult
    resource_comparison: ComparisonSuiteResult | None
    resource_missing_pairs: dict[str, int]
    resource_ceilings: dict[str, float | int]


def _load_outcomes(run_root: Path, arm: str, plan_hash: str) -> dict[str, CaseOutcome]:
    roots = sorted((run_root / "arms" / arm).glob("*/result.json"))
    outcomes: dict[str, CaseOutcome] = {}
    for path in roots:
        outcome = CaseOutcome.model_validate_json(path.read_bytes())
        if outcome.arm.lower() != arm or outcome.plan_sha256 != plan_hash:
            raise ValueError("case outcome arm or plan binding mismatch")
        if outcome.case_id in outcomes:
            raise ValueError("duplicate case outcome")
        outcomes[outcome.case_id] = outcome
    return outcomes


def _estimate_delta(result: ComparisonSuiteResult, metric: str, statistic: str) -> float:
    scored = next(item for item in result.metrics if item.metric_id == metric)
    return next(item.absolute_delta for item in scored.estimates if item.statistic == statistic)


def score_confirmation(
    *,
    protocol_path: Path,
    task_index_path: Path,
    answers_path: Path,
    plan_path: Path,
    run_root: Path,
) -> RcaEvalConfirmationResult:
    protocol = load_protocol(protocol_path)
    task_index = TaskIndex.model_validate_json(task_index_path.read_bytes())
    plan = _validate_plan(plan_path, protocol, task_index_path, task_index)
    plan_hash = _sha256(plan_path)
    baseline_run = LocalizationRun.model_validate_json(
        (run_root / "baseline-run.json").read_bytes()
    )
    candidate_run = LocalizationRun.model_validate_json(
        (run_root / "candidate-run.json").read_bytes()
    )
    baseline_outcomes = _load_outcomes(run_root, "baseline", plan_hash)
    candidate_outcomes = _load_outcomes(run_root, "candidate", plan_hash)
    holdout_ids = {task.case_id for task in task_index.tasks if task.split_role == plan.split_role}
    if set(baseline_outcomes) != holdout_ids or set(candidate_outcomes) != holdout_ids:
        raise ValueError("run does not contain exactly one outcome per holdout arm")
    critical_safety = (
        baseline_run.critical_safety_gate_passed
        and candidate_run.critical_safety_gate_passed
        and len(candidate_run.failures) <= plan.resource_ceilings.maximum_candidate_failures
    )
    requests = []
    missing: dict[str, int] = {}
    for offset, field in enumerate(RESOURCE_FIELDS):
        pairs = []
        for case_id in sorted(holdout_ids):
            left = getattr(baseline_outcomes[case_id], field)
            right = getattr(candidate_outcomes[case_id], field)
            if left is not None and right is not None:
                pairs.append(PairedValue(pair_id=case_id, baseline=left, candidate=right))
        missing[field] = len(holdout_ids) - len(pairs)
        if len(pairs) >= 2:
            requests.append(
                MetricComparisonRequest(
                    metric_id=field,
                    kind=MetricKind.CONTINUOUS,
                    direction=ImprovementDirection.LOWER,
                    minimum_relevant_effect=1.0,
                    failure_policy=(
                        "Unknown resource values remain missing, are reported, and fail the "
                        "resource gate; they are not imputed."
                    ),
                    pairs=tuple(pairs),
                    bootstrap_iterations=protocol.scoring.bootstrap_iterations,
                    seed=protocol.scoring.bootstrap_seed + 100 + offset,
                )
            )
    resource_result = (
        score_suite(
            ComparisonSuiteRequest(
                schema_version="paired-comparison-request/1.0.0",
                suite_id=f"rcaeval-{plan.run_id}-resources",
                confidence_level=0.95,
                critical_safety_gate_passed=critical_safety,
                cost_latency_gate_passed=True,
                metrics=tuple(requests),
            )
        )
        if requests
        else None
    )
    ceilings = plan.resource_ceilings
    gate_checks: list[bool] = []
    if resource_result is not None and not any(missing.values()):
        for field, median_limit, p95_limit in (
            (
                "duration_ms",
                ceilings.duration_median_increase_ms,
                ceilings.duration_p95_increase_ms,
            ),
            (
                "input_tokens",
                ceilings.input_tokens_median_increase,
                ceilings.input_tokens_p95_increase,
            ),
            (
                "output_tokens",
                ceilings.output_tokens_median_increase,
                ceilings.output_tokens_p95_increase,
            ),
            (
                "cost_upper_bound_nanousd",
                ceilings.cost_median_increase_nanousd,
                ceilings.cost_p95_increase_nanousd,
            ),
        ):
            gate_checks.extend(
                (
                    _estimate_delta(resource_result, field, "median") <= median_limit,
                    _estimate_delta(resource_result, field, "p95") <= p95_limit,
                )
            )
    resource_gate = bool(gate_checks) and all(gate_checks)
    baseline_for_score = baseline_run.model_copy(update={"cost_latency_gate_passed": resource_gate})
    candidate_for_score = candidate_run.model_copy(
        update={"cost_latency_gate_passed": resource_gate}
    )
    quality = score_pair(
        protocol=protocol,
        task_index=task_index,
        task_index_hash=_sha256(task_index_path),
        answers=AnswerSet.model_validate_json(answers_path.read_bytes()),
        baseline=baseline_for_score,
        candidate=candidate_for_score,
    )
    return RcaEvalConfirmationResult(
        schema_version="rcaeval-confirmation-result/1.0.0",
        plan_sha256=plan_hash,
        critical_safety_gate_passed=critical_safety,
        resource_gate_passed=resource_gate,
        complete_case_pairs=len(holdout_ids),
        quality=quality,
        resource_comparison=resource_result,
        resource_missing_pairs=missing,
        resource_ceilings=ceilings.model_dump(mode="json"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--task-index", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("confirmation score already exists")
    result = score_confirmation(
        protocol_path=args.protocol,
        task_index_path=args.task_index,
        answers_path=args.answers,
        plan_path=args.plan,
        run_root=args.run_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", "utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
