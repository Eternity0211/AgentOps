"""Safety mapping refuses absent coverage and does not credit skipped or failed tests."""

import json
from pathlib import Path

import pytest
from evaluation.safety_matrix_report import build


@pytest.mark.parametrize("state", ["", "<failure/>", "<skipped/>", "<error/>"])
def test_safety_matrix_credits_only_actual_passing_cases(tmp_path: Path, state: str) -> None:
    junit, plan = tmp_path / "junit.xml", tmp_path / "plan.json"
    junit.write_text(
        '<testsuite><testcase classname="tests.x" name="test_one[param]">'
        + state
        + "</testcase></testsuite>",
        encoding="utf-8",
    )
    plan.write_text(
        json.dumps(
            {
                "scope": "test",
                "unmeasured": ["human"],
                "groups": [
                    {
                        "id": "one",
                        "requirement": "requirement",
                        "modules": ["tests.x"],
                        "names": ["test_one"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = build(junit, plan)
    assert result["groups"][0]["passed"] == int(not state)
    assert result["all_cases_passed"] == (not state)
    assert result["groups"][0]["status"] == ("VERIFIED_TESTS" if not state else "NOT_VERIFIED")
    value = json.loads(plan.read_text(encoding="utf-8"))
    value["groups"][0]["names"] = ["absent"]
    plan.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="missing test coverage"):
        build(junit, plan)
