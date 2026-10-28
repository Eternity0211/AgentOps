"""Reproducible, track-specific reports from validated raw evaluation results."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from evaluation.contracts import EvaluationContractError, load_json_object
from evaluation.fairness import FairnessPlan, FairnessPolicy
from evaluation.harness import load_fair_suite, load_recovery_fixtures
from evaluation.tracks import (
    DIAGNOSIS_TRACK,
    RECOVERY_SAFETY_TRACK,
    DiagnosisRawResult,
    RecoverySafetyFixtureSet,
    RecoverySafetyRawResult,
    TrackRawResult,
    raw_track,
)


def render_markdown(result: TrackRawResult) -> str:
    """Render raw inventory only; versioned scoring remains a later phase."""
    statuses = Counter(case.status for case in result.cases)
    lines = [
        f"# AgentOps {result.to_mapping()['track']} raw evaluation run",
        "",
        f"- Run: `{result.metadata.run_id}`",
        f"- Baseline: `{result.metadata.baseline_id}` (`{result.metadata.baseline_version}`)",
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
    ]
    if isinstance(result, DiagnosisRawResult):
        lines.append(f"- Diagnosis dataset: `{result.dataset_version}` (`{result.dataset_sha256}`)")
    else:
        lines.append(f"- Recovery fixtures: `{result.fixture_version}` (`{result.fixture_sha256}`)")
    lines.extend(
        [
            f"- Rules: `{result.binding.rules_version}` (`{result.binding.rules_sha256}`)",
            (
                f"- Fairness policy: `{result.binding.fairness_policy_version}` "
                f"(`{result.binding.fairness_policy_sha256}`)"
            ),
            (
                f"- Fairness plan: `{result.binding.fairness_plan_version}` "
                f"(`{result.binding.fairness_plan_sha256}`)"
            ),
            f"- Raw result SHA-256: `{result.fingerprint}`",
            f"- Cases: {len(result.cases)}",
            "",
            "## Raw status distribution",
            "",
            "| Status | Count |",
            "| --- | ---: |",
        ]
    )
    for status in ("completed", "handoff", "refused", "failed"):
        lines.append(f"| {status} | {statuses[status]} |")
    if isinstance(result, DiagnosisRawResult):
        lines.extend(_diagnosis_inventory(result))
    else:
        lines.extend(_recovery_inventory(result))
    lines.extend(
        [
            "",
            "> This track report contains raw counts only. It does not claim diagnosis quality, "
            "recovery safety, latency improvement, or baseline superiority until the versioned "
            "scoring rules and denominators are applied.",
            "",
        ]
    )
    return "\n".join(lines)


def _diagnosis_inventory(result: DiagnosisRawResult) -> list[str]:
    lines = [
        "",
        "## Diagnosis case inventory",
        "",
        "| Case | Status | Evidence Gate | Tool calls | Tokens | Cost (micro-USD) | "
        "Duration (ms) |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for case in result.cases:
        lines.append(
            f"| `{case.case_id}` | {case.status} | {case.evidence_gate_outcome} | "
            f"{case.tool_calls} | {case.input_tokens + case.output_tokens} | "
            f"{case.cost_microusd} | {case.duration_ms} |"
        )
    return lines


def _recovery_inventory(result: RecoverySafetyRawResult) -> list[str]:
    lines = [
        "",
        "## Recovery-safety case inventory",
        "",
        "| Case | Status | Schema | Policy | Approval | Executor | Verifier | Route | "
        "Executions/duplicates |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for case in result.cases:
        lines.append(
            f"| `{case.case_id}` | {case.status} | {case.schema_validation_outcome} | "
            f"{case.policy_outcome} | {case.approval_outcome} | {case.executor_outcome} | "
            f"{case.verification_outcome} | {case.final_route} | "
            f"{case.executed_actions}/{case.duplicate_executions} |"
        )
    return lines


def _model_line(result: TrackRawResult) -> str:
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
    recovery_fixtures_path: Path | None = None,
) -> TrackRawResult:
    """Load a track result only with every exact source binding."""
    dataset, rules, policy, plan = load_fair_suite(
        dataset_path, rules_path, fairness_policy_path, fairness_plan_path
    )
    document = load_json_object(raw_path)
    track = raw_track(document)
    result: TrackRawResult
    if track == DIAGNOSIS_TRACK:
        if recovery_fixtures_path is not None:
            raise EvaluationContractError("diagnosis reports do not accept recovery fixtures")
        result = DiagnosisRawResult.from_mapping(document, rules=rules)
        if (
            result.dataset_version != dataset.dataset_version
            or result.dataset_sha256 != dataset.fingerprint
        ):
            raise EvaluationContractError("diagnosis raw result is not bound to the dataset")
        expected_case_ids = tuple(case.case_id for case in dataset.cases)
    elif track == RECOVERY_SAFETY_TRACK:
        if recovery_fixtures_path is None:
            raise EvaluationContractError("recovery-safety reports require recovery fixtures")
        fixtures = load_recovery_fixtures(recovery_fixtures_path)
        result = RecoverySafetyRawResult.from_mapping(document, rules=rules)
        _verify_fixture_binding(result, fixtures)
        expected_case_ids = tuple(case.case_id for case in fixtures.cases)
    else:  # pragma: no cover - raw_track is closed
        raise EvaluationContractError("unsupported evaluation track")
    _verify_shared_bindings(result, policy, plan)
    if tuple(case.case_id for case in result.cases) != expected_case_ids:
        raise EvaluationContractError("raw result case set does not match its track input")
    return result


def _verify_fixture_binding(
    result: RecoverySafetyRawResult, fixtures: RecoverySafetyFixtureSet
) -> None:
    if (
        result.fixture_version != fixtures.fixture_version
        or result.fixture_sha256 != fixtures.fingerprint
    ):
        raise EvaluationContractError("recovery raw result is not bound to the supplied fixtures")


def _verify_shared_bindings(
    result: TrackRawResult, policy: FairnessPolicy, plan: FairnessPlan
) -> None:
    if (
        result.binding.fairness_policy_version != policy.policy_version
        or result.binding.fairness_policy_sha256 != policy.fingerprint
    ):
        raise EvaluationContractError("raw result is not bound to the supplied fairness policy")
    if (
        result.binding.fairness_plan_version != plan.plan_version
        or result.binding.fairness_plan_sha256 != plan.fingerprint
    ):
        raise EvaluationContractError("raw result is not bound to the supplied fairness plan")


def generate_report(
    raw_path: Path,
    dataset_path: Path,
    rules_path: Path,
    fairness_policy_path: Path,
    fairness_plan_path: Path,
    output_path: Path,
    recovery_fixtures_path: Path | None = None,
) -> str:
    """Create, never overwrite, one deterministic track-specific report."""
    report = render_markdown(
        load_bound_result(
            raw_path,
            dataset_path,
            rules_path,
            fairness_policy_path,
            fairness_plan_path,
            recovery_fixtures_path,
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
    parser.add_argument("--recovery-fixtures", type=Path)
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
            arguments.recovery_fixtures,
        )
    except EvaluationContractError as error:
        print(f"[evaluation] report failed: {error}", file=sys.stderr)
        return 1
    print(f"[evaluation] report generated file={arguments.output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
