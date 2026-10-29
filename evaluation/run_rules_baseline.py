"""Run and persist the predeclared deterministic rules baseline."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from evaluation.baseline_runner import (
    DEFAULT_DATASET,
    DEFAULT_FAIRNESS_PLAN,
    DEFAULT_FAIRNESS_POLICY,
    DEFAULT_GROUND_TRUTH,
    DEFAULT_RECOVERY_FIXTURES,
    DEFAULT_RULES,
    DEFAULT_SCORING_POLICY,
    execute_predeclared_baseline,
)
from evaluation.baselines.recovery import DeterministicRecoverySafetySystem
from evaluation.baselines.rules import RulesDiagnosisSystem
from evaluation.contracts import EvaluationContractError


def execute_rules_baseline(
    *,
    output_dir: Path,
    code_revision: str,
    run_id: str,
    dataset_path: Path = DEFAULT_DATASET,
    rules_path: Path = DEFAULT_RULES,
    fairness_policy_path: Path = DEFAULT_FAIRNESS_POLICY,
    fairness_plan_path: Path = DEFAULT_FAIRNESS_PLAN,
    recovery_fixtures_path: Path = DEFAULT_RECOVERY_FIXTURES,
    ground_truth_root: Path = DEFAULT_GROUND_TRUTH,
    scoring_policy_path: Path = DEFAULT_SCORING_POLICY,
    wall_clock: Callable[[], datetime] | None = None,
    duration_clock_ns: Callable[[], int] | None = None,
) -> tuple[str, str, str]:
    """Execute the no-model rules profile through the shared evaluation runner."""
    return execute_predeclared_baseline(
        output_dir=output_dir,
        code_revision=code_revision,
        run_id=run_id,
        baseline_kind="rules",
        diagnosis_system=RulesDiagnosisSystem(),
        recovery_system=DeterministicRecoverySafetySystem(),
        dataset_path=dataset_path,
        rules_path=rules_path,
        fairness_policy_path=fairness_policy_path,
        fairness_plan_path=fairness_plan_path,
        recovery_fixtures_path=recovery_fixtures_path,
        ground_truth_root=ground_truth_root,
        scoring_policy_path=scoring_policy_path,
        wall_clock=wall_clock or (lambda: datetime.now(UTC)),
        duration_clock_ns=duration_clock_ns or time.perf_counter_ns,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        diagnosis_sha, recovery_sha, score_sha = execute_rules_baseline(
            output_dir=arguments.output_dir,
            code_revision=arguments.code_revision,
            run_id=arguments.run_id,
        )
    except EvaluationContractError as error:
        print(f"[evaluation] rules baseline failed: {error}", file=sys.stderr)
        return 1
    print(
        "[evaluation] rules baseline complete "
        f"diagnosis_sha256={diagnosis_sha} recovery_sha256={recovery_sha} "
        f"score_sha256={score_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
