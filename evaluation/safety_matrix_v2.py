"""Build the frozen NE2 safety matrix from exact JUnit case bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


def _status(case: ET.Element) -> str:
    if case.find("failure") is not None or case.find("error") is not None:
        return "FAILED"
    if case.find("skipped") is not None:
        return "SKIPPED"
    return "PASSED"


def build(junit: Path, plan: Path) -> dict[str, Any]:
    specification = json.loads(plan.read_text(encoding="utf-8"))
    if specification.get("schema_version") != "ne2-safety-plan/1.0.0":
        raise ValueError("unsupported NE2 safety plan")
    root = ET.fromstring(junit.read_bytes())
    collected = list(root.iter("testcase"))
    if not collected:
        raise ValueError("NE2 safety matrix requires collected cases")
    results = []
    for case in specification["cases"]:
        selected = [
            item
            for item in collected
            if item.get("classname") == case["junit_classname"]
            and item.get("name", "").split("[")[0] == case["junit_name"]
        ]
        if not selected:
            raise ValueError("NE2 safety mapping has missing test coverage: " + case["case_id"])
        members = [
            {
                "id": item.get("classname", "") + "::" + item.get("name", ""),
                "status": _status(item),
                "duration_seconds": item.get("time"),
            }
            for item in selected
        ]
        results.append(
            {
                "case_id": case["case_id"],
                "class": case["class"],
                "status": (
                    "VERIFIED_SAFE"
                    if all(item["status"] == "PASSED" for item in members)
                    else "NOT_VERIFIED"
                ),
                "members": members,
                "expected_gate_reason_codes": case["expected_gate_reason_codes"],
                "prohibited_outcomes": case["prohibited_outcomes"],
            }
        )
    if len({item["case_id"] for item in results}) != len(results):
        raise ValueError("NE2 safety case IDs must be unique")

    class_totals: Counter[str] = Counter(item["class"] for item in results)
    class_passed: Counter[str] = Counter(
        item["class"] for item in results if item["status"] == "VERIFIED_SAFE"
    )
    prohibited = sorted({outcome for case in results for outcome in case["prohibited_outcomes"]})
    prohibited_metrics = {}
    for outcome in prohibited:
        relevant = [item for item in results if outcome in item["prohibited_outcomes"]]
        verified = all(item["status"] == "VERIFIED_SAFE" for item in relevant)
        prohibited_metrics[outcome] = {
            "denominator": len(relevant),
            "observed": 0 if verified else None,
            "status": "VERIFIED_ZERO" if verified else "NOT_VERIFIED",
        }
    all_verified = all(item["status"] == "VERIFIED_SAFE" for item in results)
    return {
        "schema_version": "ne2-safety-result/1.0.0",
        "scope": specification["scope"],
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest(),
        "collected_junit_cases": len(collected),
        "semantic_cases": len(results),
        "all_cases_verified": all_verified,
        "acceptance_passed": all_verified
        and all(item["status"] == "VERIFIED_ZERO" for item in prohibited_metrics.values()),
        "class_rates": {
            name: {
                "numerator": class_passed[name],
                "denominator": total,
            }
            for name, total in sorted(class_totals.items())
        },
        "prohibited_outcomes": prohibited_metrics,
        "gate_reason_code_coverage": sorted(
            {code for case in results for code in case["expected_gate_reason_codes"]}
        ),
        "cases": results,
        "unmeasured": specification["unmeasured"],
        "interpretation": (
            "Passing deterministic fixtures verifies their asserted routes only; it is not an "
            "observed production incident, human approval, unsafe-action rate, or recovery rate."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("NE2 safety result already exists")
    result = build(args.junit, args.plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
