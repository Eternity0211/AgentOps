from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation.safety_matrix_v2 import build

PLAN = Path("evaluation/safety_matrix/v2/plan.json")


def test_committed_ne2_plan_freezes_required_categories_and_acceptance() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    cases = plan["cases"]
    identifiers = {item["case_id"] for item in cases}
    reasons = {code for item in cases for code in item["expected_gate_reason_codes"]}
    prohibited = {value for item in cases for value in item["prohibited_outcomes"]}

    assert plan["status"] == "FROZEN_BEFORE_MEASURED_RUN"
    assert len(cases) == len(identifiers) == 13
    assert {
        "reference-fabrication",
        "incident-ownership-mismatch",
        "stale-missing-counter-quality-sources",
        "prompt-injection",
        "approval-expiry-invalidation",
        "approval-material-mutation",
        "execution-replay",
        "concurrent-approval",
        "concurrent-duplicate-delivery",
        "failed-verification-closure",
    }.issubset(identifiers)
    assert {
        "EVIDENCE_NOT_FOUND",
        "ARTIFACT_UNRESOLVABLE",
        "INCIDENT_OWNERSHIP_MISMATCH",
        "EVIDENCE_STALE",
        "MISSING_EVIDENCE_DECLARED",
        "UNRESOLVED_COUNTER_EVIDENCE",
    }.issubset(reasons)
    assert {"unapproved_execution", "duplicate_execution", "false_recovery_closure"}.issubset(
        prohibited
    )


def _write_plan(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "ne2-safety-plan/1.0.0",
                "scope": "deterministic fixtures",
                "cases": [
                    {
                        "case_id": "attack",
                        "class": "attack",
                        "junit_classname": "tests.x",
                        "junit_name": "test_attack",
                        "expected_gate_reason_codes": ["EVIDENCE_STALE"],
                        "prohibited_outcomes": ["unapproved_execution"],
                    },
                    {
                        "case_id": "control",
                        "class": "normal-control",
                        "junit_classname": "tests.x",
                        "junit_name": "test_control",
                        "expected_gate_reason_codes": [],
                        "prohibited_outcomes": ["valid_evidence_false_block"],
                    },
                ],
                "unmeasured": ["production rate"],
            }
        ),
        encoding="utf-8",
    )


def test_safety_matrix_reports_verified_zero_only_when_all_bound_members_pass(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan.json"
    junit = tmp_path / "junit.xml"
    _write_plan(plan)
    junit.write_text(
        '<testsuite tests="3">'
        '<testcase classname="tests.x" name="test_attack[first]" time="0.1"/>'
        '<testcase classname="tests.x" name="test_attack[second]" time="0.2"/>'
        '<testcase classname="tests.x" name="test_control" time="0.1"/>'
        "</testsuite>",
        encoding="utf-8",
    )

    result = build(junit, plan)

    assert result["semantic_cases"] == 2
    assert result["all_cases_verified"]
    assert result["acceptance_passed"]
    assert result["prohibited_outcomes"]["unapproved_execution"] == {
        "denominator": 1,
        "observed": 0,
        "status": "VERIFIED_ZERO",
    }
    assert result["gate_reason_code_coverage"] == ["EVIDENCE_STALE"]


@pytest.mark.parametrize("state", ["<failure/>", "<error/>", "<skipped/>"])
def test_safety_matrix_never_turns_nonpassing_cases_into_zero(tmp_path: Path, state: str) -> None:
    plan = tmp_path / "plan.json"
    junit = tmp_path / "junit.xml"
    _write_plan(plan)
    junit.write_text(
        '<testsuite tests="2">'
        f'<testcase classname="tests.x" name="test_attack">{state}</testcase>'
        '<testcase classname="tests.x" name="test_control"/>'
        "</testsuite>",
        encoding="utf-8",
    )

    result = build(junit, plan)

    assert not result["all_cases_verified"]
    assert not result["acceptance_passed"]
    assert result["prohibited_outcomes"]["unapproved_execution"]["observed"] is None
    assert result["prohibited_outcomes"]["unapproved_execution"]["status"] == "NOT_VERIFIED"


def test_safety_matrix_rejects_missing_mapping_and_unknown_schema(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    junit = tmp_path / "junit.xml"
    _write_plan(plan)
    junit.write_text('<testsuite><testcase classname="tests.y" name="test_other"/></testsuite>')
    with pytest.raises(ValueError, match="missing test coverage"):
        build(junit, plan)

    value = json.loads(plan.read_text(encoding="utf-8"))
    value["schema_version"] = "unknown"
    plan.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        build(junit, plan)
