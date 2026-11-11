from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from evaluation.run_diagnosis_generalization import (
    _archive_observations,
    _synthetic_observations,
)
from evaluation.structured_model import StructuredModelFailure


def test_frozen_archive_resolves_all_v5_memory_evidence() -> None:
    plan = json.loads(
        Path("evaluation/real_protocol/v3/diagnosis-generalization-plan.json").read_text(
            encoding="utf-8"
        )
    )

    observations = _archive_observations(plan["cases"][0])

    assert len(observations) == 8
    assert {item["source"] for item in observations} == {
        "metrics",
        "logs",
        "traces",
        "deployments",
        "topology",
    }
    assert len({item["id"] for item in observations}) == 8


def test_synthetic_cases_are_deterministic_and_label_isolated() -> None:
    plan = json.loads(
        Path("evaluation/real_protocol/v3/diagnosis-generalization-plan.json").read_text(
            encoding="utf-8"
        )
    )
    cases = plan["cases"][1:]

    assert [_synthetic_observations(case) for case in cases] == [
        _synthetic_observations(case) for case in cases
    ]
    assert "expected_top1" not in json.dumps(plan)
    assert [len(json.loads(_synthetic_observations(case)[0]["summary"])) for case in cases] == [
        0,
        2,
        0,
        3,
    ]


def test_frozen_implementation_must_be_an_ancestor(tmp_path: Path) -> None:
    from evaluation.run_diagnosis_generalization import run

    plan = {
        "implementation_commit": "a" * 40,
        "provider": {},
        "cases": [],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with (
        patch(
            "evaluation.run_diagnosis_generalization.subprocess.check_output",
            return_value="b" * 40,
        ),
        patch(
            "evaluation.run_diagnosis_generalization.subprocess.run",
            return_value=Mock(returncode=1),
        ),
        pytest.raises(ValueError, match="frozen implementation commit is not an ancestor"),
    ):
        run(plan_path, tmp_path / "output", key="key")


def test_provider_failure_is_persisted_and_next_case_runs(tmp_path: Path) -> None:
    from evaluation.run_diagnosis_generalization import run

    cases = [
        {
            "case_id": f"case-{index}",
            "incident_id": f"incident-{index}",
            "source": "FROZEN_SYNTHETIC",
            "alert": "bounded alert",
            "retained_bytes": [],
            "deployment": False,
        }
        for index in range(2)
    ]
    plan = {
        "implementation_commit": "a" * 40,
        "provider": {},
        "cases": cases,
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with (
        patch(
            "evaluation.run_diagnosis_generalization.subprocess.check_output",
            return_value="b" * 40,
        ),
        patch(
            "evaluation.run_diagnosis_generalization.subprocess.run",
            return_value=Mock(returncode=0),
        ),
        patch(
            "evaluation.run_diagnosis_generalization.StructuredEvaluationModel.invoke",
            side_effect=StructuredModelFailure("INVALID_RESPONSE"),
        ) as invoke,
    ):
        run(plan_path, tmp_path / "output", key="key")

    result = json.loads((tmp_path / "output" / "results.json").read_text(encoding="utf-8"))
    assert invoke.call_count == 2
    assert [item["status"] for item in result["outcomes"]] == ["FAILED", "FAILED"]
    assert all(item["error_code"] == "INVALID_RESPONSE" for item in result["outcomes"])
    assert len((tmp_path / "output" / "outcomes.jsonl").read_text().splitlines()) == 2
