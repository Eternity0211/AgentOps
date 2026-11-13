from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from evaluation.contracts import load_json_object
from evaluation.run_final_security import compare

PLAN = Path("evaluation/security/v2/plan.json")


def _junit(path: Path, names: list[str], *, fail: str | None = None) -> Path:
    suite = ET.Element("testsuite")
    for name in names:
        case = ET.SubElement(suite, "testcase", name=name, time="0.001")
        if name == fail:
            ET.SubElement(case, "failure")
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_final_security_comparison_reports_both_arms_and_deltas(tmp_path: Path) -> None:
    plan = load_json_object(PLAN)
    names = [item["junit_name"] for item in plan["cases"]]
    baseline = _junit(tmp_path / "baseline.xml", names)
    candidate = _junit(tmp_path / "candidate.xml", names)
    result = compare(plan, baseline, candidate)

    assert result["accepted"] is True
    assert result["metrics"]["baseline"]["route_correctness"] == [13, 13]
    assert result["metrics"]["candidate"]["route_correctness"] == [13, 13]
    assert result["deltas"]["route_correctness"]["absolute_rate_delta"] == 0

    failed = compare(plan, baseline, _junit(tmp_path / "failed.xml", names, fail=names[0]))
    assert failed["accepted"] is False
    assert failed["metrics"]["candidate"]["critical_failures"] == 1
