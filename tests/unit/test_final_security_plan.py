from __future__ import annotations

import json
from pathlib import Path

PLAN = Path("evaluation/security/v2/plan.json")


def test_final_security_plan_is_frozen_complete_and_has_control() -> None:
    value = json.loads(PLAN.read_text(encoding="utf-8"))

    assert value["schema_version"] == "final-security-plan/1.0.0"
    assert value["status"] == "FROZEN_BEFORE_CANDIDATE_RUN"
    assert len(value["cases"]) == 13
    assert len({item["case_id"] for item in value["cases"]}) == 13
    assert {item["class"] for item in value["cases"]} == {
        "attack",
        "safe-handoff",
        "normal-control",
    }
    assert sum(item["class"] == "normal-control" for item in value["cases"]) == 1
    assert value["acceptance"]["critical_failures"] == 0
