"""Create-only execution support shared by the four predeclared evaluation baselines."""

from __future__ import annotations

import os
import platform
import re
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from evaluation.contracts import EvaluationCase, EvaluationContractError, EvaluationRunMetadata
from evaluation.fairness import CandidateExecutionConfig
from evaluation.harness import (
    DiagnosisEvaluationSystem,
    RecoverySafetySystem,
    load_fair_suite,
    load_recovery_fixtures,
    run_diagnosis_track,
    run_recovery_safety_track,
    write_raw_result,
)
from evaluation.report import generate_report
from evaluation.tracks import RecoverySafetyInput

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation" / "datasets" / "v1" / "dataset.json"
DEFAULT_RULES = ROOT / "evaluation" / "rules" / "v2" / "rules.json"
DEFAULT_FAIRNESS_POLICY = ROOT / "evaluation" / "fairness" / "v1" / "policy.json"
DEFAULT_FAIRNESS_PLAN = ROOT / "evaluation" / "plans" / "v1" / "comparison.json"
DEFAULT_RECOVERY_FIXTURES = ROOT / "evaluation" / "recovery" / "v1" / "fixtures.json"
DEFAULT_GROUND_TRUTH = ROOT / "evaluation" / "ground_truth" / "v1"
DEFAULT_SCORING_POLICY = ROOT / "evaluation" / "scoring" / "v1" / "safe-outcomes.json"
_REVISION = re.compile(r"^[0-9a-f]{40}$")


class _DiagnosisReplay:
    def __init__(self, outputs: Mapping[str, Mapping[str, Any]]) -> None:
        self._outputs = outputs

    def evaluate(
        self, case: EvaluationCase, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        del configuration
        return self._outputs[case.case_id]


class _RecoveryReplay:
    def __init__(self, outputs: Mapping[str, Mapping[str, Any]]) -> None:
        self._outputs = outputs

    def evaluate(
        self, case: RecoverySafetyInput, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        del configuration
        return self._outputs[case.case_id]


def _timed_output(
    operation: Callable[[], Mapping[str, Any]], clock_ns: Callable[[], int]
) -> dict[str, Any]:
    started = clock_ns()
    output = dict(operation())
    output["duration_ms"] = max(0, clock_ns() - started) // 1_000_000
    return output


def _write_text_create_only(path: Path, content: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    except FileExistsError as error:
        raise EvaluationContractError("evaluation artifact already exists") from error
    except OSError as error:
        raise EvaluationContractError("evaluation artifact cannot be persisted") from error


def execute_predeclared_baseline(
    *,
    output_dir: Path,
    code_revision: str,
    run_id: str,
    baseline_kind: str,
    diagnosis_system: DiagnosisEvaluationSystem,
    recovery_system: RecoverySafetySystem,
    seed: int = 7,
    dataset_path: Path = DEFAULT_DATASET,
    rules_path: Path = DEFAULT_RULES,
    fairness_policy_path: Path = DEFAULT_FAIRNESS_POLICY,
    fairness_plan_path: Path = DEFAULT_FAIRNESS_PLAN,
    recovery_fixtures_path: Path = DEFAULT_RECOVERY_FIXTURES,
    ground_truth_root: Path = DEFAULT_GROUND_TRUTH,
    scoring_policy_path: Path = DEFAULT_SCORING_POLICY,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    duration_clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> tuple[str, str, str]:
    """Run blind systems first, then persist and score their immutable outputs."""
    if _REVISION.fullmatch(code_revision) is None:
        raise EvaluationContractError("code revision must be a full lowercase Git SHA")
    dataset, rules, fairness_policy, fairness_plan = load_fair_suite(
        dataset_path, rules_path, fairness_policy_path, fairness_plan_path
    )
    fixtures = load_recovery_fixtures(recovery_fixtures_path)
    profiles = tuple(item for item in fairness_plan.baselines if item.kind == baseline_kind)
    if len(profiles) != 1:
        raise EvaluationContractError("fairness plan must contain one requested baseline profile")
    profile = profiles[0]
    configuration = CandidateExecutionConfig(profile, fairness_plan.tool_schema_versions)

    started_at = wall_clock()
    diagnosis_outputs = {
        case.case_id: _timed_output(
            partial(diagnosis_system.evaluate, case, configuration), duration_clock_ns
        )
        for case in dataset.cases
    }
    recovery_outputs = {
        case.case_id: _timed_output(
            partial(recovery_system.evaluate, case.system_input, configuration),
            duration_clock_ns,
        )
        for case in fixtures.cases
    }
    finished_at = wall_clock()

    # Labels enter only after both candidate systems have finished and are never supplied to
    # either replay adapter or execution configuration.
    from evaluation.scoring import (
        load_ground_truth_set,
        load_safe_outcome_policy,
        render_safe_outcome_markdown,
        score_safe_outcomes,
        write_score_result,
    )

    ground_truth = load_ground_truth_set(ground_truth_root)
    metadata = EvaluationRunMetadata(
        run_id=run_id,
        baseline_id=profile.baseline_id,
        baseline_version=profile.baseline_version,
        code_revision=code_revision,
        scenario_version="fault-behavior/1.0.0",
        ground_truth_manifest_set_sha256=ground_truth.fingerprint,
        model_id=profile.model_id,
        model_settings_sha256=profile.model_settings_sha256,
        prompt_version=profile.prompt_version,
        policy_version=fairness_plan.safety_chain.policy_version,
        tool_schema_versions=fairness_plan.tool_schema_versions,
        python_version=platform.python_version(),
        platform=f"{sys.platform}-{platform.machine().lower() or 'unknown'}",
        hardware_summary=(
            f"machine={platform.machine() or 'unknown'};logical_cpu_count={os.cpu_count() or 1}"
        ),
        concurrency=1,
        seed=seed,
        started_at=started_at,
        finished_at=finished_at,
    )
    diagnosis = run_diagnosis_track(
        dataset,
        rules,
        fairness_policy,
        fairness_plan,
        _DiagnosisReplay(diagnosis_outputs),
        metadata,
        clock=wall_clock,
    )
    recovery = run_recovery_safety_track(
        fixtures,
        rules,
        fairness_policy,
        fairness_plan,
        _RecoveryReplay(recovery_outputs),
        metadata,
        clock=wall_clock,
    )

    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise EvaluationContractError("baseline output directory already exists") from error
    except OSError as error:
        raise EvaluationContractError("baseline output directory cannot be created") from error

    diagnosis_path = output_dir / "diagnosis-raw.json"
    recovery_path = output_dir / "recovery-safety-raw.json"
    diagnosis_sha = write_raw_result(diagnosis, diagnosis_path)
    recovery_sha = write_raw_result(recovery, recovery_path)
    generate_report(
        diagnosis_path,
        dataset_path,
        rules_path,
        fairness_policy_path,
        fairness_plan_path,
        output_dir / "diagnosis-report.md",
    )
    generate_report(
        recovery_path,
        dataset_path,
        rules_path,
        fairness_policy_path,
        fairness_plan_path,
        output_dir / "recovery-safety-report.md",
        recovery_fixtures_path,
    )
    score = score_safe_outcomes(
        diagnosis,
        recovery,
        dataset,
        fixtures,
        ground_truth,
        load_safe_outcome_policy(scoring_policy_path),
    )
    score_sha = write_score_result(score, output_dir / "safe-outcomes.json")
    _write_text_create_only(output_dir / "safe-outcomes.md", render_safe_outcome_markdown(score))
    return diagnosis_sha, recovery_sha, score_sha
