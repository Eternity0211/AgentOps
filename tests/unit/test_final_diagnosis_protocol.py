from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from evaluation.run_final_diagnosis_comparison import (
    BOUND_SOURCES,
    EXECUTION_ORDER,
    FAILURE_POLICY,
    MODES,
    PROVIDER,
    RULES_QUERIES,
    check_plan,
)

PLAN = Path("evaluation/final_diagnosis_comparison/v1/plan.json")
DATASET = Path("evaluation/datasets/lab-holdout-v1")
FREEZE_MANIFEST = Path("evaluation/lab_holdout/v1/evaluator_only/freeze-manifest.json")
LABELS = Path("evaluation/lab_holdout/v1/evaluator_only/labels.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(PLAN.read_text(encoding="utf-8")))


def test_final_diagnosis_protocol_binds_implementation_dataset_and_power() -> None:
    plan = _plan()
    manifest = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    power_path = Path(plan["power_analysis"])
    power = json.loads(power_path.read_text(encoding="utf-8"))

    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "c700481973d3f1ca3239aaa3e1cdf5dc5fd2e6f6"
    assert tuple(plan["modes"]) == MODES
    assert plan["expected_cases"] == 160
    assert plan["expected_outcomes"] == 480
    assert plan["execution_order"] == EXECUTION_ORDER
    assert plan["failure_policy"] == FAILURE_POLICY
    assert plan["provider"] == PROVIDER
    assert tuple(plan["rules_queries"]) == RULES_QUERIES
    assert _sha256(DATASET / "index.json") == plan["dataset_index_sha256"]
    assert _sha256(Path(plan["dataset_plan"])) == plan["dataset_plan_sha256"]
    assert _sha256(FREEZE_MANIFEST) == plan["freeze_manifest_sha256"]
    assert _sha256(power_path) == plan["power_analysis_sha256"]
    assert manifest["files"]["evaluator/labels.json"] == plan["evaluator_labels_sha256"]
    assert power["minimum_relevant_absolute_delta"] == 0.15
    assert power["required_fault_pairs"] == 103
    assert power["frozen_fault_pairs"] == 120
    assert (
        plan["paired_scorer"]["binary_metrics"]["top1"]["minimum_relevant_effect"]
        == power["minimum_relevant_absolute_delta"]
    )


def test_final_diagnosis_protocol_source_hashes_match_implementation_commit() -> None:
    plan = _plan()
    assert set(plan["source_hashes"]) == BOUND_SOURCES
    for name, digest in plan["source_hashes"].items():
        committed = subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=D:/AgentOps",
                "show",
                f"{plan['implementation_commit']}:{name}",
            ]
        )
        assert hashlib.sha256(committed).hexdigest() == digest


def test_final_diagnosis_preflight_never_opens_evaluator_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    original = Path.read_bytes

    def guarded(path: Path) -> bytes:
        if path.resolve() == LABELS.resolve():
            raise AssertionError("runtime preflight opened evaluator labels")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)

    check_plan(plan, revision, DATASET)


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("provider", {**PROVIDER, "temperature": 0.1}, "configuration"),
        ("execution_order", "BASELINE_FIRST", "scorer"),
        ("source_hashes", {}, "source hash"),
    ],
)
def test_final_diagnosis_protocol_refuses_frozen_contract_drift(
    field: str, replacement: object, reason: str
) -> None:
    plan = copy.deepcopy(_plan())
    plan[field] = replacement
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()

    with pytest.raises(ValueError, match=reason):
        check_plan(plan, revision, DATASET)
