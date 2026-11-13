from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation.contracts import EvaluationContractError, canonical_json
from evaluation.final_durability import (
    OBSERVATION_SCHEMA,
    create_result,
    load_observations,
    load_plan,
    score,
)

PLAN = Path("evaluation/durability/v2/plan.json")


def _observations(path: Path, *, unsafe: bool = False) -> Path:
    plan = load_plan(PLAN)
    rows = []
    for index, (case_id, route) in enumerate(plan.cases):
        for arm in ("control", "treatment"):
            rows.append(
                {
                    "case_id": case_id,
                    "arm": arm,
                    "completed": 1,
                    "duplicate_external_effects": int(
                        unsafe and case_id == "duplicate-delivery" and arm == "treatment"
                    ),
                    "ambiguous_result_redispatches": 0,
                    "evidence_expected": 2,
                    "evidence_persisted": 2,
                    "takeover_or_resume_latency_ms": 0 if arm == "control" else 10 + index,
                    "total_latency_ms": 100 + index + (20 if arm == "treatment" else 0),
                    "model_calls": 2,
                    "tool_calls": 2,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "rate_card_upper_bound_nusd": 1000,
                    "terminal_route": "COMPLETED" if arm == "control" else route,
                }
            )
    path.write_text(
        canonical_json(
            {
                "schema_version": OBSERVATION_SCHEMA,
                "plan_sha256": plan.fingerprint,
                "observations": rows,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_durability_scorer_reports_both_arms_deltas_and_acceptance(tmp_path: Path) -> None:
    plan = load_plan(PLAN)
    observations = load_observations(_observations(tmp_path / "observations.json"), plan)
    result = score(plan, observations)

    assert result["summary"]["accepted"] is True
    assert result["summary"]["terminal_route_matches"] == 8
    assert result["summary"]["duplicate_external_effects"] == 0
    assert result["summary"]["total_latency_delta_median_ms"] == 20
    assert result["summary"]["total_latency_delta_median_95pct_bootstrap_ms"] == [20.0, 20.0]
    assert len(result["pairs"]) == 8
    metric = result["pairs"][0]["metrics"]["total_latency_ms"]
    assert metric == {
        "control": 100,
        "treatment": 120,
        "absolute_delta": 20,
        "relative_delta": 0.2,
    }


def test_durability_scorer_fails_safety_gate_and_refuses_incomplete_input(
    tmp_path: Path,
) -> None:
    plan = load_plan(PLAN)
    unsafe = load_observations(_observations(tmp_path / "unsafe.json", unsafe=True), plan)
    assert score(plan, unsafe)["summary"]["accepted"] is False

    value = json.loads((tmp_path / "unsafe.json").read_text(encoding="utf-8"))
    value["observations"].pop()
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="sixteen"):
        load_observations(incomplete, plan)


def test_durability_result_is_create_only_and_hash_bound(tmp_path: Path) -> None:
    observations = _observations(tmp_path / "observations.json")
    output = tmp_path / "result"
    create_result(plan_path=PLAN, observations_path=observations, output_dir=output)

    assert (output / "result.json").is_file()
    assert (output / "README.md").is_file()
    assert (output / "manifest.json").is_file()
    assert "100→120 (+20)" in (output / "README.md").read_text(encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="already exists"):
        create_result(plan_path=PLAN, observations_path=observations, output_dir=output)
