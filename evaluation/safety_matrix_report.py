"""Bind explicit safety requirements to exact passing JUnit cases without capability claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def build(junit: Path, plan: Path) -> dict[str, Any]:
    specification = json.loads(plan.read_text(encoding="utf-8"))
    root = ET.fromstring(junit.read_bytes())
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("safety matrix requires collected cases")
    groups = []
    for group in specification["groups"]:
        selected = [
            c
            for c in cases
            if c.get("classname") in group["modules"]
            and (not group["names"] or c.get("name", "").split("[")[0] in group["names"])
        ]
        missing = [
            n
            for n in group["names"]
            if not any(c.get("name", "").split("[")[0] == n for c in selected)
        ]
        missing_modules = [
            m for m in group["modules"] if not any(c.get("classname") == m for c in selected)
        ]
        if not selected or missing or missing_modules:
            raise ValueError("safety matrix mapping has missing test coverage: " + group["id"])
        members = [
            {
                "id": c.get("classname", "") + "::" + c.get("name", ""),
                "status": "FAILED"
                if c.find("failure") is not None or c.find("error") is not None
                else "SKIPPED"
                if c.find("skipped") is not None
                else "PASSED",
                "duration_seconds": c.get("time"),
            }
            for c in selected
        ]
        groups.append(
            {
                "id": group["id"],
                "requirement": group["requirement"],
                "passed": sum(c["status"] == "PASSED" for c in members),
                "total": len(members),
                "members": members,
                "status": "VERIFIED_TESTS"
                if all(c["status"] == "PASSED" for c in members)
                else "NOT_VERIFIED",
            }
        )
    return {
        "schema_version": "1.0.0",
        "scope": specification["scope"],
        "junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest(),
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "collected_cases": len(cases),
        "all_cases_passed": all(
            not any(c.find(t) is not None for t in ("failure", "error", "skipped")) for c in cases
        ),
        "groups": groups,
        "unmeasured": specification["unmeasured"],
        "overlap_rule": "Group counts can overlap; never sum groups as independent experiments.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=Path("evaluation/safety_matrix/v1/plan.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.junit, args.plan)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
