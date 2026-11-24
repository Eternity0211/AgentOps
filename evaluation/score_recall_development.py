"""Score label-isolated evidence-readiness recall development pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evaluation.memory_evidence import GcPhase, MemoryPattern, MemorySample, assess_memory_series
from evaluation.paired_comparison import (
    ComparisonSuiteRequest,
    ImprovementDirection,
    MetricComparisonRequest,
    MetricKind,
    PairedValue,
    score_suite,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Observation(StrictModel):
    evidence_id: str = Field(pattern=r"^ev-[a-z0-9-]+$")
    source: Literal["logs", "metrics", "traces", "deployments"]
    current: bool
    quality_basis_points: int = Field(ge=0, le=10_000)
    supports_candidate: bool
    unresolved_counter: bool = False


class ArmInput(StrictModel):
    observations: tuple[Observation, ...] = Field(max_length=16)
    material_missing: tuple[str, ...] = Field(max_length=16)
    optional_unknowns: tuple[str, ...] = Field(max_length=16)
    memory_samples: tuple[tuple[int, int, int, int, int | None, str | None], ...] = ()


class DevelopmentCase(StrictModel):
    case_id: str = Field(pattern=r"^ne3-[a-z0-9-]+$")
    candidate_id: str = Field(min_length=1, max_length=128)
    baseline: ArmInput
    candidate: ArmInput


class DevelopmentInputs(StrictModel):
    schema_version: Literal["recall-development-inputs/1.0.0"]
    retention_limit_bytes: int = Field(gt=0)
    cases: tuple[DevelopmentCase, ...] = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def unique_cases(self) -> DevelopmentInputs:
        identifiers = [case.case_id for case in self.cases]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("case IDs must be unique")
        return self


class CaseLabel(StrictModel):
    target_positive: bool
    category: Literal[
        "DECISIVE_EVIDENCE",
        "CHRONOLOGICAL_MEMORY",
        "PAIRED_NEGATIVE_CONTROL",
    ]


class DevelopmentLabels(StrictModel):
    schema_version: Literal["recall-development-labels/1.0.0"]
    labels: dict[str, CaseLabel]


def _memory_pattern(arm: ArmInput, limit: int) -> MemoryPattern | None:
    if not arm.memory_samples:
        return None
    samples = tuple(
        MemorySample(
            second * 1_000_000_000,
            retained,
            allocations,
            releases,
            limit,
            (f"memory-{index}",),
            cycle,
            None if phase is None else GcPhase(phase),
        )
        for index, (second, retained, allocations, releases, cycle, phase) in enumerate(
            arm.memory_samples
        )
    )
    return assess_memory_series(samples).pattern


def evidence_ready(arm: ArmInput, limit: int) -> tuple[bool, tuple[str, ...]]:
    """Apply unchanged Gate prerequisites without invoking a model or a write path."""
    reasons: list[str] = []
    supporting = tuple(item for item in arm.observations if item.supports_candidate)
    if arm.material_missing:
        reasons.append("MISSING_EVIDENCE_DECLARED")
    if any(not item.current for item in supporting):
        reasons.append("EVIDENCE_STALE")
    if any(item.quality_basis_points < 7_000 for item in supporting):
        reasons.append("QUALITY_BELOW_FLOOR")
    if len({item.source for item in supporting if item.current}) < 2:
        reasons.append("INSUFFICIENT_INDEPENDENT_SOURCES")
    if any(item.unresolved_counter for item in arm.observations):
        reasons.append("UNRESOLVED_COUNTER_EVIDENCE")
    memory_pattern = _memory_pattern(arm, limit)
    if arm.memory_samples and memory_pattern is not MemoryPattern.SUSTAINED_RETENTION:
        reasons.append(f"MEMORY_{memory_pattern or MemoryPattern.INSUFFICIENT}")
    return not reasons, tuple(dict.fromkeys(reasons))


def _rates(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    tp = sum(row["target_positive"] and row[arm] for row in rows)
    fp = sum(not row["target_positive"] and row[arm] for row in rows)
    fn = sum(row["target_positive"] and not row[arm] for row in rows)
    tn = sum(not row["target_positive"] and not row[arm] for row in rows)
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": None if tp + fp == 0 else tp / (tp + fp),
        "recall": tp / (tp + fn),
        "negative_control_safety": tn / (tn + fp),
    }


def score(inputs_path: Path, labels_path: Path, plan_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text("utf-8"))
    for path, key in ((inputs_path, "inputs_sha256"), (labels_path, "labels_sha256")):
        if hashlib.sha256(path.read_bytes()).hexdigest() != plan[key]:
            raise ValueError(f"{path.name} hash mismatch")
    inputs = DevelopmentInputs.model_validate_json(inputs_path.read_text("utf-8"))
    labels = DevelopmentLabels.model_validate_json(labels_path.read_text("utf-8"))
    if set(labels.labels) != {case.case_id for case in inputs.cases}:
        raise ValueError("input and label case IDs differ")
    rows: list[dict[str, Any]] = []
    for case in inputs.cases:
        baseline, baseline_reasons = evidence_ready(case.baseline, inputs.retention_limit_bytes)
        candidate, candidate_reasons = evidence_ready(case.candidate, inputs.retention_limit_bytes)
        rows.append(
            {
                "case_id": case.case_id,
                "category": labels.labels[case.case_id].category,
                "target_positive": labels.labels[case.case_id].target_positive,
                "baseline": baseline,
                "candidate": candidate,
                "baseline_reasons": baseline_reasons,
                "candidate_reasons": candidate_reasons,
                "baseline_observations": len(case.baseline.observations),
                "candidate_observations": len(case.candidate.observations),
            }
        )
    pairs = tuple(
        PairedValue(
            pair_id=row["case_id"],
            baseline=float(row["baseline"] == row["target_positive"]),
            candidate=float(row["candidate"] == row["target_positive"]),
        )
        for row in rows
    )
    paired = score_suite(
        ComparisonSuiteRequest(
            schema_version="paired-comparison-request/1.0.0",
            suite_id="ne3-recall-development-v1",
            confidence_level=0.95,
            critical_safety_gate_passed=all(
                not row["candidate"] for row in rows if not row["target_positive"]
            ),
            cost_latency_gate_passed=True,
            metrics=(
                MetricComparisonRequest(
                    metric_id="classification_correct",
                    kind=MetricKind.BINARY,
                    direction=ImprovementDirection.HIGHER,
                    minimum_relevant_effect=0.1,
                    failure_policy=(
                        "Every missing or invalid case is incorrect; no selective exclusion."
                    ),
                    pairs=pairs,
                    bootstrap_iterations=5_000,
                    seed=2026112403,
                ),
            ),
        )
    )
    return {
        "schema_version": "recall-development-result/1.0.0",
        "scope": "deterministic evidence-readiness development; not model diagnosis accuracy",
        "gate_rules": {
            "minimum_quality_basis_points": 7_000,
            "minimum_independent_sources": 2,
            "fail_on_declared_missing_evidence": True,
            "require_counter_evidence_resolution": True,
        },
        "baseline": _rates(rows, "baseline"),
        "candidate": _rates(rows, "candidate"),
        "failures": [row for row in rows if row["candidate"] != row["target_positive"]],
        "cases": rows,
        "resources": {
            "model_calls": 0,
            "write_calls": 0,
            "baseline_observations": sum(row["baseline_observations"] for row in rows),
            "candidate_observations": sum(row["candidate_observations"] for row in rows),
        },
        "paired": paired.model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("recall development output already exists")
    result = score(args.inputs, args.labels, args.plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", "utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
