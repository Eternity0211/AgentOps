"""Run the frozen label-free RCAEval baseline/candidate localization pair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evaluation.rcaeval_contract import (
    EvaluationBudget,
    RcaEvalProtocol,
    TaskIndex,
    TaskManifest,
    load_protocol,
    protocol_sha256,
)
from evaluation.rcaeval_features import (
    FeatureArm,
    LocalizationContext,
    build_localization_context,
)
from evaluation.rcaeval_provider import (
    LocalizationInvocation,
    RcaEvalLocalizationProvider,
)
from evaluation.score_rcaeval_pair import (
    LocalizationRun,
    RunFailure,
    ServiceLocalizationOutput,
)


class StrictRunModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProviderSettings(StrictRunModel):
    model: Literal["deepseek-flash"]
    thinking: Literal["disabled"]
    temperature: Literal[0]
    max_tokens: Literal[512]
    max_repair_attempts: Literal[1]


class RcaEvalRunPlan(StrictRunModel):
    schema_version: Literal["rcaeval-run-plan/1.0.0"]
    status: Literal["FROZEN_BEFORE_PROVIDER_CALLS"]
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hashes: dict[str, str]
    split_role: Literal["HOLDOUT"]
    expected_cases: Literal[90]
    arms: tuple[Literal["BASELINE", "CANDIDATE"], Literal["BASELINE", "CANDIDATE"]]
    interleaving: Literal["ALTERNATE_BY_SORTED_CASE_INDEX"]
    budget: EvaluationBudget
    provider: ProviderSettings
    failure_policy: Literal[
        "Retain every terminal outcome; interrupted or invalid cases are misses and are never "
        "rerun."
    ]

    @model_validator(mode="after")
    def valid_arms_and_sources(self) -> RcaEvalRunPlan:
        if self.arms != ("BASELINE", "CANDIDATE"):
            raise ValueError("run arms must be baseline then candidate")
        required = {
            "evaluation/rcaeval_contract.py",
            "evaluation/rcaeval_features.py",
            "evaluation/rcaeval_provider.py",
            "evaluation/run_rcaeval_pair.py",
            "evaluation/score_rcaeval_pair.py",
        }
        if set(self.source_hashes) != required or any(
            len(value) != 64 or set(value) - set("0123456789abcdef")
            for value in self.source_hashes.values()
        ):
            raise ValueError("run source bindings are incomplete")
        return self


class CaseOutcome(StrictRunModel):
    schema_version: Literal["rcaeval-case-outcome/1.0.0"]
    case_id: str
    arm: Literal["BASELINE", "CANDIDATE"]
    protocol_sha256: str
    task_index_sha256: str
    plan_sha256: str
    context_sha256: str | None
    output: ServiceLocalizationOutput | None
    failure: RunFailure | None
    model_calls: int = Field(ge=0, le=2)
    tool_calls: int = Field(ge=0, le=24)
    truncated_queries: int = Field(ge=0)
    duration_ms: int | None = Field(ge=0)
    input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)
    cost_upper_bound_nanousd: int | None = Field(ge=0)

    @model_validator(mode="after")
    def exactly_one_terminal_result(self) -> CaseOutcome:
        if (self.output is None) == (self.failure is None):
            raise ValueError("case outcome requires exactly one output or failure")
        if self.output is not None and (
            self.output.case_id != self.case_id or self.failure is not None
        ):
            raise ValueError("case output binding mismatch")
        return self


class ResourceSummary(StrictRunModel):
    schema_version: Literal["rcaeval-resource-summary/1.0.0"]
    case_count: int
    baseline_model_calls: int
    candidate_model_calls: int
    baseline_tool_calls: int
    candidate_tool_calls: int
    baseline_input_tokens: int | None
    candidate_input_tokens: int | None
    baseline_output_tokens: int | None
    candidate_output_tokens: int | None
    baseline_cost_upper_bound_nanousd: int | None
    candidate_cost_upper_bound_nanousd: int | None


class LocalizationProvider(Protocol):
    def invoke(self, context: LocalizationContext) -> LocalizationInvocation: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: BaseModel) -> str:
    return hashlib.sha256(
        json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_once(path: Path, content: str) -> None:
    if path.exists():
        raise FileExistsError(f"run artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, "utf-8")


def _validate_plan(
    plan_path: Path,
    protocol: RcaEvalProtocol,
    task_index_path: Path,
    task_index: TaskIndex,
) -> RcaEvalRunPlan:
    plan = RcaEvalRunPlan.model_validate_json(plan_path.read_bytes())
    if plan.protocol_sha256 != protocol_sha256(protocol):
        raise ValueError("run plan protocol binding mismatch")
    if plan.task_index_sha256 != _sha256(task_index_path):
        raise ValueError("run plan task-index binding mismatch")
    if task_index.protocol_sha256 != plan.protocol_sha256:
        raise ValueError("task index protocol binding mismatch")
    if plan.budget != protocol.budget:
        raise ValueError("run budget differs from protocol")
    root = Path(__file__).resolve().parents[1]
    if any(_sha256(root / path) != digest for path, digest in plan.source_hashes.items()):
        raise ValueError("run source hash mismatch")
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    if (
        subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=D:/AgentOps",
                "merge-base",
                "--is-ancestor",
                plan.implementation_commit,
                revision,
            ],
            check=False,
        ).returncode
        != 0
    ):
        raise ValueError("frozen implementation commit is not an ancestor")
    tasks = [item for item in task_index.tasks if item.split_role == "HOLDOUT"]
    if len(task_index.tasks) != 180 or len(tasks) != plan.expected_cases:
        raise ValueError("task index does not contain the frozen 180/90 split")
    return plan


def _interrupted_outcome(
    *, task: TaskManifest, arm: FeatureArm, plan: RcaEvalRunPlan, plan_hash: str
) -> CaseOutcome:
    return CaseOutcome(
        schema_version="rcaeval-case-outcome/1.0.0",
        case_id=task.case_id,
        arm=arm.value,
        protocol_sha256=plan.protocol_sha256,
        task_index_sha256=plan.task_index_sha256,
        plan_sha256=plan_hash,
        context_sha256=None,
        output=None,
        failure=RunFailure(case_id=task.case_id, reason="DEPENDENCY_FAILURE"),
        model_calls=0,
        tool_calls=0,
        truncated_queries=0,
        duration_ms=None,
        input_tokens=None,
        output_tokens=None,
        cost_upper_bound_nanousd=None,
    )


def _run_case(
    *,
    task: TaskManifest,
    arm: FeatureArm,
    task_root: Path,
    output_root: Path,
    plan: RcaEvalRunPlan,
    plan_hash: str,
    provider_factory: Callable[[Callable[[dict[str, Any]], None]], LocalizationProvider],
    feature_builder: Callable[[Path, FeatureArm], LocalizationContext],
) -> CaseOutcome:
    case_root = output_root / "arms" / arm.value.lower() / task.case_id
    state_path = case_root / "state.json"
    result_path = case_root / "result.json"
    events_path = case_root / "events.jsonl"
    if result_path.exists():
        if not state_path.exists() or not events_path.exists():
            raise ValueError("terminal case outcome is missing state or events")
        existing = CaseOutcome.model_validate_json(result_path.read_bytes())
        if (
            existing.case_id != task.case_id
            or existing.arm != arm.value
            or existing.protocol_sha256 != plan.protocol_sha256
            or existing.task_index_sha256 != plan.task_index_sha256
            or existing.plan_sha256 != plan_hash
        ):
            raise ValueError("terminal case outcome binding mismatch")
        return existing
    if state_path.exists():
        state = json.loads(state_path.read_text("utf-8"))
        if state != {
            "schema_version": "rcaeval-case-state/1.0.0",
            "status": "STARTED",
            "case_id": task.case_id,
            "arm": arm.value,
            "plan_sha256": plan_hash,
        }:
            raise ValueError("started case state binding mismatch")
        outcome = _interrupted_outcome(task=task, arm=arm, plan=plan, plan_hash=plan_hash)
        if not events_path.exists():
            _write_once(events_path, "")
        _write_once(result_path, outcome.model_dump_json(indent=2) + "\n")
        return outcome
    _write_once(
        state_path,
        json.dumps(
            {
                "schema_version": "rcaeval-case-state/1.0.0",
                "status": "STARTED",
                "case_id": task.case_id,
                "arm": arm.value,
                "plan_sha256": plan_hash,
            },
            indent=2,
        )
        + "\n",
    )
    events: list[dict[str, Any]] = []
    try:
        context = feature_builder(task_root / "tasks" / task.case_id, arm)
        if context.case_id != task.case_id or context.arm is not arm:
            raise ValueError("feature context binding mismatch")
        invocation = provider_factory(events.append).invoke(context)
        output = invocation.output
        failure = (
            None
            if output is not None
            else RunFailure.model_validate(
                {
                    "case_id": task.case_id,
                    "reason": invocation.failure_reason or "DEPENDENCY_FAILURE",
                }
            )
        )
        outcome = CaseOutcome(
            schema_version="rcaeval-case-outcome/1.0.0",
            case_id=task.case_id,
            arm=arm.value,
            protocol_sha256=plan.protocol_sha256,
            task_index_sha256=plan.task_index_sha256,
            plan_sha256=plan_hash,
            context_sha256=_canonical_sha256(context),
            output=output,
            failure=failure,
            model_calls=invocation.model_calls,
            tool_calls=context.tool_calls,
            truncated_queries=context.truncated_queries,
            duration_ms=invocation.duration_ms,
            input_tokens=invocation.input_tokens,
            output_tokens=invocation.output_tokens,
            cost_upper_bound_nanousd=invocation.cost_upper_bound_nanousd,
        )
    except (OSError, ValueError):
        outcome = _interrupted_outcome(task=task, arm=arm, plan=plan, plan_hash=plan_hash)
    _write_once(
        events_path,
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
    )
    _write_once(result_path, outcome.model_dump_json(indent=2) + "\n")
    return outcome


def _optional_sum(outcomes: list[CaseOutcome], field: str) -> int | None:
    values = [getattr(item, field) for item in outcomes]
    return None if any(value is None for value in values) else sum(values)


def run_pair(
    *,
    protocol_path: Path,
    task_index_path: Path,
    task_root: Path,
    plan_path: Path,
    output_root: Path,
    api_key: str,
    provider_factory: Callable[[Callable[[dict[str, Any]], None]], LocalizationProvider]
    | None = None,
    feature_builder: Callable[[Path, FeatureArm], LocalizationContext] = build_localization_context,
) -> tuple[LocalizationRun, LocalizationRun, ResourceSummary]:
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY required")
    protocol = load_protocol(protocol_path)
    task_index = TaskIndex.model_validate_json(task_index_path.read_bytes())
    plan = _validate_plan(plan_path, protocol, task_index_path, task_index)
    plan_hash = _sha256(plan_path)
    manifest_path = output_root / "manifest.json"
    manifest = {
        "schema_version": "rcaeval-run-manifest/1.0.0",
        "run_id": plan.run_id,
        "plan_sha256": plan_hash,
        "protocol_sha256": plan.protocol_sha256,
        "task_index_sha256": plan.task_index_sha256,
    }
    if manifest_path.exists():
        if json.loads(manifest_path.read_text("utf-8")) != manifest:
            raise ValueError("existing run manifest binding mismatch")
    else:
        _write_once(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    factory = provider_factory or (lambda journal: RcaEvalLocalizationProvider(api_key, journal))
    outcomes: dict[FeatureArm, list[CaseOutcome]] = {
        FeatureArm.BASELINE: [],
        FeatureArm.CANDIDATE: [],
    }
    tasks = sorted(
        (item for item in task_index.tasks if item.split_role == plan.split_role),
        key=lambda item: item.case_id,
    )
    for index, task in enumerate(tasks):
        order = (
            (FeatureArm.BASELINE, FeatureArm.CANDIDATE)
            if index % 2 == 0
            else (FeatureArm.CANDIDATE, FeatureArm.BASELINE)
        )
        for arm in order:
            outcomes[arm].append(
                _run_case(
                    task=task,
                    arm=arm,
                    task_root=task_root,
                    output_root=output_root,
                    plan=plan,
                    plan_hash=plan_hash,
                    provider_factory=factory,
                    feature_builder=feature_builder,
                )
            )

    def build_run(arm: FeatureArm) -> LocalizationRun:
        arm_outcomes = outcomes[arm]
        return LocalizationRun(
            schema_version="rcaeval-localization-run/1.0.0",
            run_id=f"{plan.run_id}-{arm.value.lower()}",
            arm=arm.value,
            split_role=plan.split_role,
            protocol_sha256=plan.protocol_sha256,
            task_index_sha256=plan.task_index_sha256,
            budget=plan.budget,
            critical_safety_gate_passed=True,
            cost_latency_gate_passed=False,
            outputs=tuple(item.output for item in arm_outcomes if item.output is not None),
            failures=tuple(item.failure for item in arm_outcomes if item.failure is not None),
        )

    baseline = build_run(FeatureArm.BASELINE)
    candidate = build_run(FeatureArm.CANDIDATE)
    resources = ResourceSummary(
        schema_version="rcaeval-resource-summary/1.0.0",
        case_count=len(tasks),
        baseline_model_calls=sum(item.model_calls for item in outcomes[FeatureArm.BASELINE]),
        candidate_model_calls=sum(item.model_calls for item in outcomes[FeatureArm.CANDIDATE]),
        baseline_tool_calls=sum(item.tool_calls for item in outcomes[FeatureArm.BASELINE]),
        candidate_tool_calls=sum(item.tool_calls for item in outcomes[FeatureArm.CANDIDATE]),
        baseline_input_tokens=_optional_sum(outcomes[FeatureArm.BASELINE], "input_tokens"),
        candidate_input_tokens=_optional_sum(outcomes[FeatureArm.CANDIDATE], "input_tokens"),
        baseline_output_tokens=_optional_sum(outcomes[FeatureArm.BASELINE], "output_tokens"),
        candidate_output_tokens=_optional_sum(outcomes[FeatureArm.CANDIDATE], "output_tokens"),
        baseline_cost_upper_bound_nanousd=_optional_sum(
            outcomes[FeatureArm.BASELINE], "cost_upper_bound_nanousd"
        ),
        candidate_cost_upper_bound_nanousd=_optional_sum(
            outcomes[FeatureArm.CANDIDATE], "cost_upper_bound_nanousd"
        ),
    )
    for name, value in (
        ("baseline-run.json", baseline),
        ("candidate-run.json", candidate),
        ("resources.json", resources),
    ):
        path = output_root / name
        content = value.model_dump_json(indent=2) + "\n"
        if path.exists():
            if path.read_text("utf-8") != content:
                raise ValueError(f"existing {name} differs from recomputed run")
        else:
            _write_once(path, content)
    return baseline, candidate, resources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--task-index", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    run_pair(
        protocol_path=args.protocol,
        task_index_path=args.task_index,
        task_root=args.task_root,
        plan_path=args.plan,
        output_root=args.output_root,
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
