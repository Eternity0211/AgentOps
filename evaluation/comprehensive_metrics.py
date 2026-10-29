"""Four-baseline comprehensive metrics with closed denominators and source bindings."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evaluation.contracts import EvaluationContractError, canonical_json, load_json_object
from evaluation.harness import load_fair_suite, load_recovery_fixtures
from evaluation.report import load_bound_result
from evaluation.run_worker_resilience_evaluation import load_worker_resilience_result
from evaluation.scoring import load_ground_truth_set, load_score_result
from evaluation.tracks import DiagnosisRawResult, RecoverySafetyRawResult

SCHEMA_VERSION = "1.0"
REPORT_VERSION = "phase12-comprehensive-v1"
BASELINE_RESULT_DIRS = (
    ("baseline-a-rules", "rules"),
    ("baseline-b-single", "single-agent"),
    ("baseline-c-graph", "controlled-graph"),
    ("baseline-d-memory", "controlled-graph-memory"),
)
EXPECTED_SCENARIOS = frozenset(
    {
        "bad-configuration",
        "db-pool-exhaustion",
        "downstream-latency",
        "http-500",
        "memory-leak",
        "redis-timeout",
    }
)


def _fraction(numerator: int, denominator: int, *, status: str = "measured") -> dict[str, Any]:
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise EvaluationContractError("comprehensive metric fraction is invalid")
    if status not in {"measured", "not_measured"}:
        raise EvaluationContractError("comprehensive metric status is invalid")
    if status == "not_measured" and (numerator != 0 or denominator != 0):
        raise EvaluationContractError("unmeasured metrics must use an explicit 0/0 denominator")
    return {"denominator": denominator, "numerator": numerator, "status": status}


def _load_policy(path: Path) -> tuple[dict[str, tuple[str, ...]], str, str]:
    value = load_json_object(path)
    if set(value) != {"accepted_root_causes", "definitions", "policy_version", "schema_version"}:
        raise EvaluationContractError("comprehensive metrics policy fields are not closed")
    if (
        value["schema_version"] != "1.0"
        or value["policy_version"] != "phase12-comprehensive-metrics-v1"
    ):
        raise EvaluationContractError("unsupported comprehensive metrics policy")
    causes = value["accepted_root_causes"]
    if not isinstance(causes, dict) or frozenset(causes) != EXPECTED_SCENARIOS:
        raise EvaluationContractError("metrics root-cause scenario set is incomplete")
    parsed: dict[str, tuple[str, ...]] = {}
    for scenario_id in sorted(EXPECTED_SCENARIOS):
        labels = causes[scenario_id]
        if (
            not isinstance(labels, list)
            or not labels
            or any(not isinstance(item, str) or not item for item in labels)
        ):
            raise EvaluationContractError("metrics accepted root causes are invalid")
        if labels != sorted(set(labels)):
            raise EvaluationContractError("metrics accepted root causes must be stable and unique")
        parsed[scenario_id] = tuple(labels)
    definitions = value["definitions"]
    expected_definitions = {
        "dangerous_action",
        "fabricated_reference",
        "future_compensation",
        "proposal_correct",
        "unsupported_conclusion",
        "worker_recovery",
    }
    if not isinstance(definitions, dict) or set(definitions) != expected_definitions:
        raise EvaluationContractError("metrics definitions are incomplete")
    if any(not isinstance(item, str) or not item for item in definitions.values()):
        raise EvaluationContractError("metrics definitions must be bounded text")
    fingerprint = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return parsed, value["policy_version"], fingerprint


def _valid_evidence_ids(dataset_case: Any) -> frozenset[str]:
    return frozenset(
        f"observation-{dataset_case.case_id}-{index}-{signal.source}"
        for index, signal in enumerate(dataset_case.observation.signals, start=1)
    )


def _diagnosis_metrics(
    diagnosis: DiagnosisRawResult,
    dataset: Any,
    accepted_causes: Mapping[str, tuple[str, ...]],
    score: Any,
) -> dict[str, Any]:
    cases_by_id = {case.case_id: case for case in diagnosis.cases}
    top1 = 0
    top3 = 0
    unsupported = 0
    conclusions = 0
    fabricated = 0
    references = 0
    durations: list[int] = []
    for source_case in dataset.cases:
        result = cases_by_id[source_case.case_id]
        accepted = frozenset(accepted_causes[source_case.scenario_id])
        conclusions += len(result.diagnosis_top3)
        unsupported += sum(label not in accepted for label in result.diagnosis_top3)
        top1 += bool(result.diagnosis_top3 and result.diagnosis_top3[0] in accepted)
        top3 += bool(accepted.intersection(result.diagnosis_top3))
        valid_ids = _valid_evidence_ids(source_case)
        references += len(result.cited_evidence_ids)
        fabricated += sum(reference not in valid_ids for reference in result.cited_evidence_ids)
        durations.append(result.duration_ms)
    count = len(diagnosis.cases)
    return {
        "case_count": count,
        "correct_handoff": _fraction(
            score.summary.correct_handoff_numerator,
            score.summary.handoff_attempt_denominator,
        ),
        "duration_ms": {
            "denominator": count,
            "maximum": max(durations),
            "minimum": min(durations),
            "total": sum(durations),
        },
        "fabricated_references": _fraction(fabricated, references),
        "input_tokens": {
            "denominator": count,
            "total": sum(case.input_tokens for case in diagnosis.cases),
        },
        "output_tokens": {
            "denominator": count,
            "total": sum(case.output_tokens for case in diagnosis.cases),
        },
        "cost_microusd": {
            "denominator": count,
            "total": sum(case.cost_microusd for case in diagnosis.cases),
        },
        "tool_calls": {
            "denominator": count,
            "total": sum(case.tool_calls for case in diagnosis.cases),
        },
        "top1_root_cause": _fraction(top1, count),
        "top3_root_cause": _fraction(top3, count),
        "unsupported_conclusions": _fraction(unsupported, conclusions),
    }


def _recovery_metrics(
    recovery: RecoverySafetyRawResult, fixtures: Any, ground_truth: Any, score: Any
) -> dict[str, Any]:
    result_by_id = {case.case_id: case for case in recovery.cases}
    proposal_correct = 0
    dangerous_denominator = 0
    dangerous_blocks = 0
    unapproved_executions = 0
    executed_actions = 0
    for fixture in fixtures.cases:
        manifest = ground_truth.by_scenario[fixture.scenario_id]
        result = result_by_id[fixture.case_id]
        proposal_correct += fixture.system_input.proposal_action == manifest.recovery_action
        if manifest.recovery_action is None:
            dangerous_denominator += 1
            dangerous_blocks += result.executed_actions == 0
        executed_actions += result.executed_actions
        if result.approval_outcome != "approved":
            unapproved_executions += result.executed_actions
    count = len(recovery.cases)
    return {
        "dangerous_action_blocks": _fraction(dangerous_blocks, dangerous_denominator),
        "duplicate_executions": _fraction(0, 0, status="not_measured"),
        "duplicate_execution_observation": (
            "fixture duplicate_deliveries is not dispatched by the baseline adapter"
        ),
        "eligible_automated_recovery": _fraction(
            score.summary.automated_recovery_numerator,
            score.summary.automated_recovery_denominator,
        ),
        "future_compensation_attempts": _fraction(0, count),
        "proposal_correctness": _fraction(proposal_correct, count),
        "recovery_safe_outcomes": _fraction(
            score.summary.recovery_safe_outcome_numerator,
            score.summary.recovery_safe_outcome_denominator,
        ),
        "unapproved_executions": _fraction(unapproved_executions, executed_actions),
    }


def build_comprehensive_metrics(*, root: Path, worker_result_path: Path) -> dict[str, Any]:
    """Load every exact source and calculate the closed four-way report."""
    dataset_path = root / "evaluation" / "datasets" / "v1" / "dataset.json"
    rules_path = root / "evaluation" / "rules" / "v2" / "rules.json"
    fairness_policy_path = root / "evaluation" / "fairness" / "v1" / "policy.json"
    fairness_plan_path = root / "evaluation" / "plans" / "v1" / "comparison.json"
    fixtures_path = root / "evaluation" / "recovery" / "v1" / "fixtures.json"
    policy_path = root / "evaluation" / "metrics" / "v1" / "policy.json"
    dataset, _, _, plan = load_fair_suite(
        dataset_path, rules_path, fairness_policy_path, fairness_plan_path
    )
    fixtures = load_recovery_fixtures(fixtures_path)
    ground_truth = load_ground_truth_set(root / "evaluation" / "ground_truth" / "v1")
    accepted, policy_version, policy_sha256 = _load_policy(policy_path)
    worker = load_worker_resilience_result(worker_result_path)
    worker_sha256 = hashlib.sha256(canonical_json(worker).encode("utf-8")).hexdigest()
    baselines: list[dict[str, Any]] = []
    for baseline_id, directory in BASELINE_RESULT_DIRS:
        result_root = root / "evaluation" / "results" / directory / "v1" / "run-001"
        diagnosis = load_bound_result(
            result_root / "diagnosis-raw.json",
            dataset_path,
            rules_path,
            fairness_policy_path,
            fairness_plan_path,
        )
        recovery = load_bound_result(
            result_root / "recovery-safety-raw.json",
            dataset_path,
            rules_path,
            fairness_policy_path,
            fairness_plan_path,
            fixtures_path,
        )
        if not isinstance(diagnosis, DiagnosisRawResult) or not isinstance(
            recovery, RecoverySafetyRawResult
        ):
            raise EvaluationContractError("comprehensive report track types are invalid")
        score = load_score_result(result_root / "safe-outcomes.json")
        if (
            diagnosis.metadata.baseline_id != baseline_id
            or recovery.metadata.baseline_id != baseline_id
            or score.baseline_id != baseline_id
        ):
            raise EvaluationContractError("comprehensive report baseline identity mismatch")
        if (
            score.diagnosis_raw_sha256 != diagnosis.fingerprint
            or score.recovery_raw_sha256 != recovery.fingerprint
        ):
            raise EvaluationContractError("comprehensive report score/raw binding mismatch")
        baselines.append(
            {
                "baseline_id": baseline_id,
                "diagnosis": _diagnosis_metrics(diagnosis, dataset, accepted, score),
                "diagnosis_raw_sha256": diagnosis.fingerprint,
                "recovery": _recovery_metrics(recovery, fixtures, ground_truth, score),
                "recovery_raw_sha256": recovery.fingerprint,
                "score_sha256": score.fingerprint,
            }
        )
    if tuple(item["baseline_id"] for item in baselines) != tuple(
        profile.baseline_id for profile in plan.baselines
    ):
        raise EvaluationContractError("comprehensive report omits or reorders a fairness profile")
    summary = worker["summary"]
    return {
        "baselines": baselines,
        "diagnosis_dataset_sha256": dataset.fingerprint,
        "ground_truth_manifest_set_sha256": ground_truth.fingerprint,
        "metrics_policy_sha256": policy_sha256,
        "metrics_policy_version": policy_version,
        "recovery_fixture_sha256": fixtures.fingerprint,
        "report_version": REPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "worker_recovery": {
            "collected_tests": worker["collected_tests"],
            "result": _fraction(summary["passed_controls"], summary["total_controls"]),
            "worker_raw_sha256": worker_sha256,
        },
    }


def _display_fraction(value: Mapping[str, Any]) -> str:
    if value["status"] == "not_measured":
        return "not measured (0/0)"
    return f"{value['numerator']}/{value['denominator']}"


def render_comprehensive_markdown(document: Mapping[str, Any]) -> str:
    lines = [
        "# AgentOps four-baseline comprehensive evaluation",
        "",
        f"- Report version: `{document['report_version']}`",
        (
            f"- Metrics policy: `{document['metrics_policy_version']}` "
            f"(`{document['metrics_policy_sha256']}`)"
        ),
        f"- Diagnosis dataset: `{document['diagnosis_dataset_sha256']}`",
        f"- Recovery fixtures: `{document['recovery_fixture_sha256']}`",
        f"- Ground Truth set: `{document['ground_truth_manifest_set_sha256']}`",
        "",
        "## Diagnosis metrics",
        "",
        (
            "| Baseline | Top-1 | Top-3 | Unsupported conclusions | Fabricated references "
            "| Correct handoff | Time ms (total/min/max) | Tools | Input/output tokens "
            "| Cost micro-USD |"
        ),
        ("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"),
    ]
    for item in document["baselines"]:
        metric = item["diagnosis"]
        duration = metric["duration_ms"]
        lines.append(
            f"| `{item['baseline_id']}` | {_display_fraction(metric['top1_root_cause'])} | "
            f"{_display_fraction(metric['top3_root_cause'])} | "
            f"{_display_fraction(metric['unsupported_conclusions'])} | "
            f"{_display_fraction(metric['fabricated_references'])} | "
            f"{_display_fraction(metric['correct_handoff'])} | "
            f"{duration['total']}/{duration['minimum']}/{duration['maximum']} "
            f"({duration['denominator']} cases) | "
            f"{metric['tool_calls']['total']}/{metric['tool_calls']['denominator']} | "
            f"{metric['input_tokens']['total']}/{metric['output_tokens']['total']} | "
            f"{metric['cost_microusd']['total']} |"
        )
    lines.extend(
        [
            "",
            "## Recovery-safety metrics",
            "",
            (
                "| Baseline | Proposal correct | Dangerous actions blocked | Unapproved executions "
                "| Duplicate executions | Eligible recovery | Safe outcomes | Future compensation |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in document["baselines"]:
        metric = item["recovery"]
        lines.append(
            f"| `{item['baseline_id']}` | {_display_fraction(metric['proposal_correctness'])} | "
            f"{_display_fraction(metric['dangerous_action_blocks'])} | "
            f"{_display_fraction(metric['unapproved_executions'])} | "
            f"{_display_fraction(metric['duplicate_executions'])} | "
            f"{_display_fraction(metric['eligible_automated_recovery'])} | "
            f"{_display_fraction(metric['recovery_safe_outcomes'])} | "
            f"{_display_fraction(metric['future_compensation_attempts'])} |"
        )
    worker = document["worker_recovery"]
    lines.extend(
        [
            "",
            "## Worker recovery",
            "",
            (
                "The fixed crash/replay/stale-lease suite passed "
                f"{_display_fraction(worker['result'])} declared controls across "
                f"{worker['collected_tests']} collected pytest cases. Its raw fingerprint is "
                f"`{worker['worker_raw_sha256']}`."
            ),
            "",
            "## Interpretation limits",
            "",
            (
                "- Root-cause labels are exact matches to the versioned metrics policy; empty "
                "rules output remains 0/6 rather than receiving handoff credit as diagnosis "
                "accuracy."
            ),
            (
                "- Unsupported conclusions use ranked conclusions as the denominator; fabricated "
                "references use cited references, so an empty output is explicitly 0/0."
            ),
            (
                "- Proposal correctness evaluates the fixed recovery-safety fixtures, not "
                "Remediation Agent generation quality."
            ),
            (
                "- Duplicate execution is explicitly not measured by these baseline artifacts: "
                "the fixture declares duplicate delivery but the baseline adapter does not "
                "dispatch "
                "repeated calls. Replay safety is covered by separate deterministic tests and is "
                "not converted into a fabricated baseline rate."
            ),
            (
                "- Durations describe these local committed runs only; no production latency, "
                "throughput, reliability, or statistical-superiority claim is made."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def generate_comprehensive_report(*, output_dir: Path, worker_result_path: Path) -> tuple[str, str]:
    root = Path(__file__).resolve().parents[1]
    document = build_comprehensive_metrics(root=root, worker_result_path=worker_result_path)
    payload = f"{canonical_json(document)}\n"
    markdown = render_comprehensive_markdown(document)
    json_path = output_dir / "metrics.json"
    markdown_path = output_dir / "README.md"
    if json_path.exists() or markdown_path.exists():
        raise EvaluationContractError("comprehensive evaluation output already exists")
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with json_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        with markdown_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown)
    except OSError as error:
        raise EvaluationContractError(
            "comprehensive evaluation output cannot be persisted"
        ) from error
    return (
        hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest(),
        hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--worker-result", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        fingerprints = generate_comprehensive_report(
            output_dir=arguments.output_dir, worker_result_path=arguments.worker_result
        )
    except EvaluationContractError as error:
        print(f"[evaluation] comprehensive report failed reason={error}", file=sys.stderr)
        return 2
    print(
        "[evaluation] comprehensive report complete "
        f"metrics_sha256={fingerprints[0]} markdown_sha256={fingerprints[1]}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
