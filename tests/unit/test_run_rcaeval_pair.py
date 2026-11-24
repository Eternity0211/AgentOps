from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evaluation.rcaeval_contract import (
    Answer,
    AnswerSet,
    FileBinding,
    Modality,
    TaskIndex,
    TaskManifest,
    load_protocol,
    protocol_sha256,
)
from evaluation.rcaeval_features import FeatureArm, LocalizationContext, ServiceFeature
from evaluation.rcaeval_provider import LocalizationInvocation
from evaluation.run_rcaeval_pair import run_pair
from evaluation.score_rcaeval_confirmation import score_confirmation
from evaluation.score_rcaeval_pair import ServiceLocalizationOutput

SOURCES = (
    "evaluation/rcaeval_contract.py",
    "evaluation/rcaeval_features.py",
    "evaluation/rcaeval_provider.py",
    "evaluation/run_rcaeval_pair.py",
    "evaluation/score_rcaeval_confirmation.py",
    "evaluation/score_rcaeval_pair.py",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _missing_files() -> tuple[FileBinding, ...]:
    return tuple(
        FileBinding(
            modality=modality,
            file_name=f"{modality.value}.parquet",
            sha256="0" * 64,
            size_bytes=0,
            available=False,
        )
        for modality in Modality
    )


def _task(
    index: int, *, role: str, protocol_hash: str, candidates: tuple[str, ...]
) -> TaskManifest:
    system = "ob" if role == "DEVELOPMENT" else "tt"
    return TaskManifest.model_validate(
        {
            "schema_version": "rcaeval-task/1.0.0",
            "protocol_id": "agentops-rcaeval-re2-service-localization-v1",
            "protocol_sha256": protocol_hash,
            "case_id": f"re2-{system}-{index:016x}",
            "split_role": role,
            "system": "ONLINE_BOUTIQUE" if role == "DEVELOPMENT" else "TRAIN_TICKET",
            "observation_start_unix_s": 100,
            "injection_time_unix_s": 110,
            "observation_end_unix_s": 120,
            "candidate_services": candidates,
            "files": _missing_files(),
        }
    )


def _files(tmp_path: Path) -> tuple[Path, Path, Path, tuple[TaskManifest, ...]]:
    protocol_path = Path("evaluation/rcaeval/v1/protocol.json")
    protocol = load_protocol(protocol_path)
    protocol_hash = protocol_sha256(protocol)
    tasks = tuple(
        [
            _task(
                index,
                role="DEVELOPMENT",
                protocol_hash=protocol_hash,
                candidates=protocol.splits[0].candidate_services,
            )
            for index in range(90)
        ]
        + [
            _task(
                index,
                role="HOLDOUT",
                protocol_hash=protocol_hash,
                candidates=protocol.splits[1].candidate_services,
            )
            for index in range(90)
        ]
    )
    task_index = TaskIndex(
        schema_version="rcaeval-task-index/1.0.0",
        protocol_sha256=protocol_hash,
        source_index_sha256=protocol.source.index_sha256,
        tasks=tasks,
    )
    task_index_path = tmp_path / "task-index.json"
    task_index_path.write_text(task_index.model_dump_json(indent=2) + "\n", "utf-8")
    plan_path = tmp_path / "plan.json"
    plan = {
        "schema_version": "rcaeval-run-plan/1.0.0",
        "status": "FROZEN_BEFORE_PROVIDER_CALLS",
        "run_id": "unit-run",
        "implementation_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "protocol_sha256": protocol_hash,
        "task_index_sha256": _digest(task_index_path),
        "source_hashes": {path: _digest(Path(path)) for path in SOURCES},
        "split_role": "HOLDOUT",
        "expected_cases": 90,
        "arms": ["BASELINE", "CANDIDATE"],
        "interleaving": "ALTERNATE_BY_SORTED_CASE_INDEX",
        "budget": protocol.budget.model_dump(mode="json"),
        "provider": {
            "model": "deepseek-flash",
            "thinking": "disabled",
            "temperature": 0,
            "max_tokens": 512,
            "max_repair_attempts": 1,
        },
        "resource_ceilings": {
            "maximum_candidate_failures": 0,
            "duration_median_increase_ms": 1000.0,
            "duration_p95_increase_ms": 3000.0,
            "input_tokens_median_increase": 1000.0,
            "input_tokens_p95_increase": 2000.0,
            "output_tokens_median_increase": 500.0,
            "output_tokens_p95_increase": 1000.0,
            "cost_median_increase_nanousd": 1000000.0,
            "cost_p95_increase_nanousd": 2000000.0,
        },
        "failure_policy": (
            "Retain every terminal outcome; interrupted or invalid cases are misses and are "
            "never rerun."
        ),
    }
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", "utf-8")
    return protocol_path, task_index_path, plan_path, tasks


def _context(_: Path, arm: FeatureArm, case_id: str) -> LocalizationContext:
    services = (
        "ts-auth-service",
        "ts-order-service",
        "ts-route-service",
        "ts-train-service",
        "ts-travel-service",
    )
    return LocalizationContext(
        case_id=case_id,
        arm=arm,
        candidate_services=services,
        features=tuple(
            ServiceFeature(
                service=service,
                metric_after_mean=1.0,
                metric_delta=1.0 if arm is FeatureArm.CANDIDATE else None,
                log_after_count=0,
                log_delta=0 if arm is FeatureArm.CANDIDATE else None,
                trace_after_count=0,
                trace_delta=0 if arm is FeatureArm.CANDIDATE else None,
                error_after_count=0,
                error_delta=0 if arm is FeatureArm.CANDIDATE else None,
                duration_after_mean=None,
                duration_delta=None,
            )
            for service in services
        ),
        missing_modalities=(Modality.LOGS, Modality.TRACES),
        truncated_queries=0,
        tool_calls=10,
    )


class FakeProvider:
    def __init__(self, order: list[tuple[str, str]]) -> None:
        self._order = order

    def invoke(self, context: LocalizationContext) -> LocalizationInvocation:
        self._order.append((context.case_id, context.arm.value))
        return LocalizationInvocation(
            output=ServiceLocalizationOutput(
                schema_version="service-localization-output/1.0.0",
                case_id=context.case_id,
                ranked_services=context.candidate_services[:3],
            ),
            failure_reason=None,
            model_calls=1,
            duration_ms=5,
            input_tokens=100,
            output_tokens=10,
            cost_upper_bound_nanousd=42_000,
        )


def test_runner_interleaves_create_once_outcomes_and_resumes_without_calls(
    tmp_path: Path,
) -> None:
    protocol, task_index, plan, _ = _files(tmp_path)
    order: list[tuple[str, str]] = []

    def feature_builder(path: Path, arm: FeatureArm) -> LocalizationContext:
        return _context(path, arm, path.name)

    def factory(_: Callable[[dict[str, Any]], None]) -> FakeProvider:
        return FakeProvider(order)

    output = tmp_path / "run"

    baseline, candidate, resources = run_pair(
        protocol_path=protocol,
        task_index_path=task_index,
        task_root=tmp_path,
        plan_path=plan,
        output_root=output,
        api_key="test-key",
        provider_factory=factory,
        feature_builder=feature_builder,
    )

    assert len(baseline.outputs) == len(candidate.outputs) == 90
    assert not baseline.failures and not candidate.failures
    assert baseline.critical_safety_gate_passed and candidate.critical_safety_gate_passed
    assert not baseline.cost_latency_gate_passed and not candidate.cost_latency_gate_passed
    assert [arm for _, arm in order[:4]] == ["BASELINE", "CANDIDATE", "CANDIDATE", "BASELINE"]
    assert resources.baseline_model_calls == resources.candidate_model_calls == 90
    assert resources.baseline_tool_calls == resources.candidate_tool_calls == 900
    assert resources.baseline_input_tokens == resources.candidate_input_tokens == 9_000
    order.clear()

    resumed = run_pair(
        protocol_path=protocol,
        task_index_path=task_index,
        task_root=tmp_path,
        plan_path=plan,
        output_root=output,
        api_key="test-key",
        provider_factory=factory,
        feature_builder=feature_builder,
    )
    assert order == []
    assert resumed == (baseline, candidate, resources)


def test_runner_turns_started_case_into_retained_failure_without_rerun(tmp_path: Path) -> None:
    protocol, task_index, plan, tasks = _files(tmp_path)
    holdout = sorted(
        (task for task in tasks if task.split_role == "HOLDOUT"), key=lambda item: item.case_id
    )[0]
    plan_hash = _digest(plan)
    state = tmp_path / "run/arms/baseline" / holdout.case_id / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema_version": "rcaeval-case-state/1.0.0",
                "status": "STARTED",
                "case_id": holdout.case_id,
                "arm": "BASELINE",
                "plan_sha256": plan_hash,
            },
            indent=2,
        )
        + "\n",
        "utf-8",
    )
    order: list[tuple[str, str]] = []

    def feature_builder(path: Path, arm: FeatureArm) -> LocalizationContext:
        return _context(path, arm, path.name)

    baseline, _, resources = run_pair(
        protocol_path=protocol,
        task_index_path=task_index,
        task_root=tmp_path,
        plan_path=plan,
        output_root=tmp_path / "run",
        api_key="test-key",
        provider_factory=lambda _: FakeProvider(order),
        feature_builder=feature_builder,
    )

    assert len(baseline.failures) == 1
    assert baseline.failures[0].case_id == holdout.case_id
    assert baseline.failures[0].reason == "DEPENDENCY_FAILURE"
    assert (holdout.case_id, "BASELINE") not in order
    assert resources.baseline_input_tokens is None


def test_runner_rejects_task_index_hash_drift_before_any_call(tmp_path: Path) -> None:
    protocol, task_index, plan, _ = _files(tmp_path)
    task_index.write_text(task_index.read_text("utf-8") + " ", "utf-8")
    order: list[tuple[str, str]] = []
    try:
        run_pair(
            protocol_path=protocol,
            task_index_path=task_index,
            task_root=tmp_path,
            plan_path=plan,
            output_root=tmp_path / "run",
            api_key="test-key",
            provider_factory=lambda _: FakeProvider(order),
            feature_builder=lambda path, arm: _context(path, arm, path.name),
        )
    except ValueError as error:
        assert "task-index binding" in str(error)
    else:  # pragma: no cover
        raise AssertionError("task-index drift was accepted")
    assert order == []


def test_final_scorer_reports_quality_resources_and_fail_closed_missing_values(
    tmp_path: Path,
) -> None:
    protocol, task_index, plan, tasks = _files(tmp_path)
    run_root = tmp_path / "run"
    order: list[tuple[str, str]] = []
    run_pair(
        protocol_path=protocol,
        task_index_path=task_index,
        task_root=tmp_path,
        plan_path=plan,
        output_root=run_root,
        api_key="test-key",
        provider_factory=lambda _: FakeProvider(order),
        feature_builder=lambda path, arm: _context(path, arm, path.name),
    )
    protocol_model = load_protocol(protocol)
    answers = AnswerSet(
        schema_version="rcaeval-answers/1.0.0",
        protocol_sha256=protocol_sha256(protocol_model),
        answers=tuple(
            Answer(
                case_id=task.case_id,
                source_case=f"source-{task.case_id}",
                root_cause_service=task.candidate_services[0],
                fault="fixture",
            )
            for task in tasks
            if task.split_role == "HOLDOUT"
        ),
    )
    answers_path = tmp_path / "answers.json"
    answers_path.write_text(answers.model_dump_json(indent=2), "utf-8")

    result = score_confirmation(
        protocol_path=protocol,
        task_index_path=task_index,
        answers_path=answers_path,
        plan_path=plan,
        run_root=run_root,
    )

    assert result.complete_case_pairs == 90
    assert result.critical_safety_gate_passed
    assert result.resource_gate_passed
    assert result.quality.baseline.top_1_correct == result.quality.candidate.top_1_correct == 90
    assert not any(result.resource_missing_pairs.values())
    assert result.resource_comparison is not None
    assert len(result.resource_comparison.metrics) == 4

    candidate_result = next((run_root / "arms/candidate").glob("*/result.json"))
    payload = json.loads(candidate_result.read_text("utf-8"))
    payload["input_tokens"] = None
    candidate_result.write_text(json.dumps(payload, indent=2) + "\n", "utf-8")
    missing = score_confirmation(
        protocol_path=protocol,
        task_index_path=task_index,
        answers_path=answers_path,
        plan_path=plan,
        run_root=run_root,
    )
    assert not missing.resource_gate_passed
    assert missing.resource_missing_pairs["input_tokens"] == 1
    assert not missing.quality.comparison.cost_latency_gate_passed
