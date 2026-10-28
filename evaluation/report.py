"""Reproducible report rendering from a validated raw evaluation result."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from evaluation.contracts import (
    EvaluationContractError,
    EvaluationDataset,
    EvaluationRules,
    RawEvaluationResult,
    load_json_object,
)
from evaluation.fairness import FairnessPlan, FairnessPolicy
from evaluation.harness import load_fair_suite


def render_markdown(result: RawEvaluationResult) -> str:
    """Render only raw inventory and distributions; scoring is a later versioned phase."""
    statuses = Counter(case.status for case in result.cases)
    lines = [
        "# AgentOps raw evaluation run",
        "",
        f"- Run: `{result.metadata.run_id}`",
        (f"- Baseline: `{result.metadata.baseline_id}` (`{result.metadata.baseline_version}`)"),
        f"- Code revision: `{result.metadata.code_revision}`",
        f"- Scenario version: `{result.metadata.scenario_version}`",
        (
            "- Ground Truth manifest-set SHA-256: "
            f"`{result.metadata.ground_truth_manifest_set_sha256}`"
        ),
        _model_line(result),
        f"- Prompt/policy: `{result.metadata.prompt_version}` / `{result.metadata.policy_version}`",
        f"- Concurrency/seed: {result.metadata.concurrency} / {result.metadata.seed}",
        (
            f"- Run window: {result.metadata.started_at.isoformat()} to "
            f"{result.metadata.finished_at.isoformat()}"
        ),
        f"- Dataset: `{result.dataset_version}` (`{result.dataset_sha256}`)",
        f"- Rules: `{result.rules_version}` (`{result.rules_sha256}`)",
        (
            f"- Fairness policy: `{result.fairness_policy_version}` "
            f"(`{result.fairness_policy_sha256}`)"
        ),
        (f"- Fairness plan: `{result.fairness_plan_version}` (`{result.fairness_plan_sha256}`)"),
        f"- Raw result SHA-256: `{result.fingerprint}`",
        f"- Cases: {len(result.cases)}",
        "",
        "## Raw status distribution",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    for status in ("completed", "handoff", "refused", "failed"):
        lines.append(f"| {status} | {statuses[status]} |")
    lines.extend(
        [
            "",
            "## Case inventory",
            "",
            "| Case | Status | Tool calls | Tokens | Cost (micro-USD) | Duration (ms) |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for case in result.cases:
        lines.append(
            f"| `{case.case_id}` | {case.status} | {case.tool_calls} | "
            f"{case.input_tokens + case.output_tokens} | {case.cost_microusd} | "
            f"{case.duration_ms} |"
        )
    lines.extend(
        [
            "",
            "> This foundation report contains raw counts only. It does not claim diagnosis "
            "quality, recovery safety, latency improvement, or baseline superiority until the "
            "versioned scoring tracks and denominators are applied.",
            "",
        ]
    )
    return "\n".join(lines)


def _model_line(result: RawEvaluationResult) -> str:
    if result.metadata.model_id is None:
        return "- Model/settings: not applicable (deterministic baseline)"
    return (
        f"- Model/settings: `{result.metadata.model_id}` "
        f"(`{result.metadata.model_settings_sha256}`)"
    )


def load_bound_result(
    raw_path: Path,
    dataset_path: Path,
    rules_path: Path,
    fairness_policy_path: Path,
    fairness_plan_path: Path,
) -> RawEvaluationResult:
    """Load a raw result only with its exact dataset, rules, policy, and plan."""
    dataset, rules, policy, plan = load_fair_suite(
        dataset_path, rules_path, fairness_policy_path, fairness_plan_path
    )
    result = RawEvaluationResult.from_mapping(
        load_json_object(raw_path),
        rules=rules,
        fairness_policy_version=policy.policy_version,
        fairness_policy_sha256=policy.fingerprint,
        fairness_plan_version=plan.plan_version,
        fairness_plan_sha256=plan.fingerprint,
    )
    _verify_bindings(result, dataset, rules, policy, plan)
    return result


def _verify_bindings(
    result: RawEvaluationResult,
    dataset: EvaluationDataset,
    rules: EvaluationRules,
    policy: FairnessPolicy,
    plan: FairnessPlan,
) -> None:
    if (
        result.dataset_version != dataset.dataset_version
        or result.dataset_sha256 != dataset.fingerprint
    ):
        raise EvaluationContractError("raw result is not bound to the supplied dataset")
    if result.rules_version != rules.rules_version or result.rules_sha256 != rules.fingerprint:
        raise EvaluationContractError("raw result is not bound to the supplied rules")
    if (
        result.fairness_policy_version != policy.policy_version
        or result.fairness_policy_sha256 != policy.fingerprint
    ):
        raise EvaluationContractError("raw result is not bound to the supplied fairness policy")
    if (
        result.fairness_plan_version != plan.plan_version
        or result.fairness_plan_sha256 != plan.fingerprint
    ):
        raise EvaluationContractError("raw result is not bound to the supplied fairness plan")
    if tuple(case.case_id for case in result.cases) != tuple(
        case.case_id for case in dataset.cases
    ):
        raise EvaluationContractError("raw result case set does not match the supplied dataset")


def generate_report(
    raw_path: Path,
    dataset_path: Path,
    rules_path: Path,
    fairness_policy_path: Path,
    fairness_plan_path: Path,
    output_path: Path,
) -> str:
    """Create, never overwrite, a deterministic Markdown report from a bound raw artifact."""
    report = render_markdown(
        load_bound_result(
            raw_path,
            dataset_path,
            rules_path,
            fairness_policy_path,
            fairness_plan_path,
        )
    )
    try:
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(report)
    except FileExistsError as error:
        raise EvaluationContractError("evaluation report already exists") from error
    except OSError as error:
        raise EvaluationContractError("evaluation report cannot be persisted") from error
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the bounded standalone report command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--fairness-policy", required=True, type=Path)
    parser.add_argument("--fairness-plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate one report without echoing raw or Ground Truth content."""
    arguments = build_parser().parse_args(argv)
    try:
        generate_report(
            arguments.raw,
            arguments.dataset,
            arguments.rules,
            arguments.fairness_policy,
            arguments.fairness_plan,
            arguments.output,
        )
    except EvaluationContractError as error:
        print(f"[evaluation] report failed: {error}", file=sys.stderr)
        return 1
    print(f"[evaluation] report generated file={arguments.output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
