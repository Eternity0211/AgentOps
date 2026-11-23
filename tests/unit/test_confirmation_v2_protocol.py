from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from evaluation import run_confirmation_v2 as runner
from evaluation.real_scoring import Outcome
from evaluation.score_confirmation_v2 import score
from evaluation.structured_model import StructuredTransportProfile


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _draft_plan() -> dict[str, Any]:
    plan: dict[str, Any] = json.loads(
        Path("evaluation/final_diagnosis_comparison/v1/plan.json").read_text(encoding="utf-8")
    )
    cohort = Path("evaluation/lab_holdout/v2")
    dataset = Path("evaluation/datasets/lab-holdout-v2")
    plan.update(
        schema_version="confirmation-v2-comparison/1.0.0",
        implementation_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        dataset=dataset.as_posix(),
        dataset_index_sha256=_sha256(dataset / "index.json"),
        dataset_plan=(cohort / "plan.json").as_posix(),
        dataset_plan_sha256=_sha256(cohort / "plan.json"),
        freeze_manifest=(cohort / "evaluator_only/freeze-manifest.json").as_posix(),
        freeze_manifest_sha256=_sha256(cohort / "evaluator_only/freeze-manifest.json"),
        power_analysis=(cohort / "evaluator_only/power.json").as_posix(),
        power_analysis_sha256=_sha256(cohort / "evaluator_only/power.json"),
        evaluator_labels=(cohort / "evaluator_only/labels.json").as_posix(),
        evaluator_labels_sha256=_sha256(cohort / "evaluator_only/labels.json"),
        transport_profile=StructuredTransportProfile.CANDIDATE_1_12.value,
        source_hashes={name: _sha256(Path(name)) for name in runner.BOUND_SOURCES},
    )
    return plan


def test_confirmation_preflight_binds_cohort_profile_and_sources_without_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _draft_plan()
    labels = Path(plan["evaluator_labels"]).resolve()
    original = Path.read_bytes

    def guard(path: Path) -> bytes:
        if path.resolve() == labels:
            raise AssertionError("runtime opened evaluator labels")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guard)
    runner.check_plan(plan, plan["implementation_commit"], Path(plan["dataset"]))
    plan["transport_profile"] = StructuredTransportProfile.CANDIDATE_1_11.value
    with pytest.raises(ValueError, match="configuration mismatch"):
        runner.check_plan(plan, plan["implementation_commit"], Path(plan["dataset"]))


def test_confirmation_runner_passes_frozen_112_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _draft_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def rules_case(*args: Any, **kwargs: Any) -> Outcome:
        return Outcome(
            instance_id=Path(args[0]).stem,
            mode="rules-only",
            protocol_hash=args[3],
            input_hash=args[1],
            status="SUCCEEDED",
        )

    def model_case(*args: Any, **kwargs: Any) -> Outcome:
        assert kwargs["profile"] is StructuredTransportProfile.CANDIDATE_1_12
        raise RuntimeError("profile observed")

    monkeypatch.setattr(runner, "run_rules_case", rules_case)
    monkeypatch.setattr(runner, "run_snapshot", model_case)
    monkeypatch.setattr(runner, "verify_committed_protocol", lambda *_: None)
    with pytest.raises(RuntimeError, match="profile observed"):
        runner.run(Path(plan["dataset"]), plan_path, tmp_path / "results", key="test-only")


def test_confirmation_scorer_refuses_incomplete_outcomes_before_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _draft_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    labels = Path(plan["evaluator_labels"]).resolve()
    original = Path.read_bytes

    def guard(path: Path) -> bytes:
        if path.resolve() == labels:
            raise AssertionError("incomplete score opened evaluator labels")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guard)
    monkeypatch.setattr(
        "evaluation.score_confirmation_v2.verify_committed_protocol", lambda *_: None
    )
    with pytest.raises(ValueError, match="outcome count mismatch"):
        score(plan_path, tmp_path / "missing-results", tmp_path / "score")


def test_confirmation_refuses_uncommitted_protocol(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="outside repository"):
        runner.verify_committed_protocol(plan, plan.read_bytes())


def test_frozen_confirmation_plan_binds_inputs_labels_and_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path("evaluation/confirmation_v2/plan.json")
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["dataset"] == "evaluation/datasets/lab-holdout-v2"
    assert plan["transport_profile"] == StructuredTransportProfile.CANDIDATE_1_12.value
    assert plan["expected_cases"] == 160
    assert plan["expected_outcomes"] == 480
    assert plan["power_contract"]["required_fault_pairs"] == 103
    assert plan["power_contract"]["frozen_fault_pairs"] == 120
    assert plan["paired_scorer"]["binary_metrics"]["top1"]["minimum_relevant_effect"] == 0.15
    assert _sha256(Path(plan["evaluator_labels"])) == plan["evaluator_labels_sha256"]
    for name, digest in plan["source_hashes"].items():
        committed = subprocess.check_output(
            ["git", "show", f"{plan['implementation_commit']}:{name}"]
        )
        assert hashlib.sha256(committed).hexdigest() == digest
    labels = Path(plan["evaluator_labels"]).resolve()
    original = Path.read_bytes

    def guard(candidate: Path) -> bytes:
        if candidate.resolve() == labels:
            raise AssertionError("preflight opened evaluator labels")
        return original(candidate)

    monkeypatch.setattr(Path, "read_bytes", guard)
    runner.check_plan(plan, plan["implementation_commit"], Path(plan["dataset"]))
