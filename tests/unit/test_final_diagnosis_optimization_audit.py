from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from evaluation.audit_final_diagnosis_optimization import audit

PLAN = Path("evaluation/final_diagnosis_optimization/v1/audit-plan.json")
RESULT = Path("evaluation/results/final-diagnosis-optimization/v1/audit-001/audit.json")


def test_frozen_optimization_audit_is_bound_to_historical_git_bytes() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    published = json.loads(RESULT.read_text(encoding="utf-8"))
    serialized_plan = PLAN.read_text(encoding="utf-8")
    publication_commit = subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", PLAN.as_posix()], text=True
    ).strip()

    for path, expected in plan["source_hashes"].items():
        committed = subprocess.check_output(["git", "show", f"{publication_commit}:{path}"])
        assert hashlib.sha256(committed).hexdigest() == expected
    assert published["label_access"] == "NONE"
    assert "final-diagnosis-comparison" not in serialized_plan
    assert "evaluator_labels" not in serialized_plan


def test_optimization_audit_reproduces_terminal_failure_and_resource_shape() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    failure = result["terminal_failure_fixture"]
    resources = result["development_resource_audit"]

    assert failure == {
        "cost_upper_bound_nanousd": 300000,
        "failure_code": "INVALID_RESPONSE",
        "input_tokens": 200,
        "model_calls": 2,
        "output_tokens": 200,
        "repair_attempts": 1,
        "terminal_valid_output": False,
    }
    assert resources["pair_count"] == 27
    assert resources["metrics"]["duration_ms"] == {
        "controlled_graph_median": 4438,
        "controlled_graph_p95": 5047,
        "median_delta": 16,
        "p95_delta": 31,
        "single_agent_median": 4422,
        "single_agent_p95": 5016,
    }
    assert resources["metrics"]["input_tokens"]["median_delta"] == 0
    assert resources["metrics"]["input_tokens"]["p95_delta"] == -3
    assert resources["metrics"]["model_calls"]["p95_delta"] == 0
    assert resources["metrics"]["tool_calls"]["p95_delta"] == 0


def test_optimization_audit_refuses_source_drift(tmp_path: Path) -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    plan["source_hashes"]["evaluation/structured_model.py"] = "0" * 64
    changed = tmp_path / "changed-plan.json"
    changed.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="source drift"):
        audit(changed)
