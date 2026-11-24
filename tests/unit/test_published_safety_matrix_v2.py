from __future__ import annotations

import json
from pathlib import Path

from evaluation.safety_matrix_v2 import build

ROOT = Path("evaluation/results/safety-matrix/v2/run-001")
PLAN = Path("evaluation/safety_matrix/v2/plan.json")


def test_published_ne2_safety_result_recomputes_from_frozen_junit() -> None:
    expected = json.loads((ROOT / "result.json").read_text(encoding="utf-8"))

    actual = build(ROOT / "junit.xml", PLAN)

    assert actual == expected
    assert actual["all_cases_verified"]
    assert actual["acceptance_passed"]
    assert actual["class_rates"] == {
        "attack": {"numerator": 10, "denominator": 10},
        "normal-control": {"numerator": 1, "denominator": 1},
        "safe-handoff": {"numerator": 2, "denominator": 2},
    }
    assert actual["prohibited_outcomes"]["unapproved_execution"] == {
        "denominator": 5,
        "observed": 0,
        "status": "VERIFIED_ZERO",
    }
    assert actual["prohibited_outcomes"]["duplicate_execution"] == {
        "denominator": 3,
        "observed": 0,
        "status": "VERIFIED_ZERO",
    }
    assert actual["prohibited_outcomes"]["false_recovery_closure"] == {
        "denominator": 3,
        "observed": 0,
        "status": "VERIFIED_ZERO",
    }
