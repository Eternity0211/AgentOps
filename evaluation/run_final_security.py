"""Compare the frozen security matrix against archived and fresh JUnit evidence."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evaluation.contracts import EvaluationContractError, canonical_json, load_json_object

SCHEMA_VERSION = "final-security-result/1.0.0"


def _load_plan(path: Path) -> tuple[dict[str, Any], str]:
    value = load_json_object(path)
    if (
        value.get("schema_version") != "final-security-plan/1.0.0"
        or value.get("status") != "FROZEN_BEFORE_CANDIDATE_RUN"
        or not isinstance(value.get("cases"), list)
        or len(value["cases"]) != 13
    ):
        raise EvaluationContractError("final security plan is not frozen and complete")
    return value, hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _cases(junit: Path) -> list[ET.Element]:
    try:
        root = ET.parse(junit).getroot()
    except (OSError, ET.ParseError) as error:
        raise EvaluationContractError("security JUnit is unavailable or invalid") from error
    return list(root.iter("testcase"))


def _arm(plan: Mapping[str, Any], junit: Path) -> dict[str, Any]:
    testcases = _cases(junit)
    results = []
    for specification in plan["cases"]:
        name = specification["junit_name"]
        selected = [
            item for item in testcases if item.attrib.get("name", "").split("[")[0] == name
        ]
        if not selected:
            raise EvaluationContractError(f"security JUnit omitted case {specification['case_id']}")
        failed = sum(
            item.find("failure") is not None
            or item.find("error") is not None
            or item.find("skipped") is not None
            for item in selected
        )
        duration_ms = round(
            sum(float(item.attrib.get("time", "0")) for item in selected) * 1_000
        )
        results.append(
            {
                "case_id": specification["case_id"],
                "class": specification["class"],
                "members": len(selected),
                "failed_members": failed,
                "passed": failed == 0,
                "duration_ms": duration_ms,
            }
        )
    return {"cases": results, "junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest()}


def _metrics(arm: Mapping[str, Any]) -> dict[str, Any]:
    cases = arm["cases"]
    attacks = [item for item in cases if item["class"] == "attack"]
    handoffs = [item for item in cases if item["class"] == "safe-handoff"]
    controls = [item for item in cases if item["class"] == "normal-control"]
    return {
        "attack_block": [sum(item["passed"] for item in attacks), len(attacks)],
        "safe_handoff": [sum(item["passed"] for item in handoffs), len(handoffs)],
        "false_block": [sum(not item["passed"] for item in controls), len(controls)],
        "route_correctness": [sum(item["passed"] for item in cases), len(cases)],
        "critical_failures": sum(not item["passed"] for item in cases),
        "duration_ms": sum(item["duration_ms"] for item in cases),
        "provider_cost_nusd": 0,
    }


def compare(plan: Mapping[str, Any], baseline: Path, candidate: Path) -> dict[str, Any]:
    arms = {"baseline": _arm(plan, baseline), "candidate": _arm(plan, candidate)}
    baseline_metrics, candidate_metrics = _metrics(arms["baseline"]), _metrics(
        arms["candidate"]
    )
    deltas: dict[str, Any] = {}
    for metric in ("attack_block", "safe_handoff", "false_block", "route_correctness"):
        before, after = baseline_metrics[metric], candidate_metrics[metric]
        if before[1] != after[1]:
            raise EvaluationContractError("security arm denominators changed")
        before_rate, after_rate = before[0] / before[1], after[0] / after[1]
        deltas[metric] = {
            "baseline": before,
            "candidate": after,
            "absolute_rate_delta": after_rate - before_rate,
            "relative_rate_delta": None if before_rate == 0 else after_rate / before_rate - 1,
        }
    for metric in ("critical_failures", "duration_ms", "provider_cost_nusd"):
        before, after = baseline_metrics[metric], candidate_metrics[metric]
        deltas[metric] = {
            "baseline": before,
            "candidate": after,
            "absolute_delta": after - before,
            "relative_delta": None if before == 0 else after / before - 1,
        }
    acceptance = plan["acceptance"]
    passed = (
        candidate_metrics["critical_failures"] == acceptance["critical_failures"]
        and candidate_metrics["attack_block"][0] / candidate_metrics["attack_block"][1]
        >= acceptance["minimum_attack_block_rate"]
        and candidate_metrics["safe_handoff"][0] / candidate_metrics["safe_handoff"][1]
        >= acceptance["minimum_safe_handoff_rate"]
        and candidate_metrics["false_block"][0] / candidate_metrics["false_block"][1]
        <= acceptance["maximum_false_block_rate"]
        and candidate_metrics["route_correctness"][0]
        / candidate_metrics["route_correctness"][1]
        >= acceptance["minimum_route_correctness"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "arms": arms,
        "metrics": {"baseline": baseline_metrics, "candidate": candidate_metrics},
        "deltas": deltas,
        "accepted": passed,
    }


def _render(result: Mapping[str, Any]) -> str:
    lines = [
        "# Final adversarial and chaos comparison",
        "",
        "| Metric | Baseline | Candidate | Absolute delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name in ("attack_block", "safe_handoff", "false_block", "route_correctness"):
        item = result["deltas"][name]
        lines.append(
            f"| {name} | {item['baseline'][0]}/{item['baseline'][1]} | "
            f"{item['candidate'][0]}/{item['candidate'][1]} | "
            f"{item['absolute_rate_delta']:+.1%} |"
        )
    duration = result["deltas"]["duration_ms"]
    lines.extend(
        (
            f"| local JUnit duration | {duration['baseline']} ms | "
            f"{duration['candidate']} ms | {duration['absolute_delta']:+} ms |",
            "",
            f"Acceptance: `{'PASS' if result['accepted'] else 'FAIL'}`. Provider cost is 0 in "
            "both arms because these deterministic cases dispatch no provider request.",
            "",
            "This is a fixed local safety census, not model quality, attack prevalence, or "
            "production reliability evidence.",
            "",
        )
    )
    return "\n".join(lines)


def execute(*, plan_path: Path, output_dir: Path, code_revision: str) -> None:
    if output_dir.exists():
        raise EvaluationContractError("final security output already exists")
    if len(code_revision) != 40:
        raise EvaluationContractError("final security revision must be a full SHA")
    plan, plan_hash = _load_plan(plan_path)
    root = Path(__file__).resolve().parents[1]
    baseline = root / plan["baseline_junit"]
    with tempfile.TemporaryDirectory(prefix="agentops-final-security-") as directory:
        candidate = Path(directory) / "candidate.xml"
        completed = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                *(item["test_node"] for item in plan["cases"]),
                "-p",
                "no:cacheprovider",
                "--no-cov",
                "--junitxml",
                str(candidate),
            ),
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
            timeout=300,
        )
        if completed.returncode != 0:
            raise EvaluationContractError("final security candidate suite failed")
        result = compare(plan, baseline, candidate) | {
            "plan_sha256": plan_hash,
            "candidate_revision": code_revision,
            "baseline_revision": plan["baseline_revision"],
        }
        output_dir.mkdir(parents=True)
        shutil.copyfile(candidate, output_dir / "candidate-junit.xml")
    (output_dir / "result.json").write_text(
        f"{canonical_json(result)}\n", encoding="utf-8", newline="\n"
    )
    (output_dir / "README.md").write_text(_render(result), encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    arguments = parser.parse_args(argv)
    try:
        execute(
            plan_path=arguments.plan,
            output_dir=arguments.output_dir,
            code_revision=arguments.code_revision,
        )
    except (EvaluationContractError, subprocess.TimeoutExpired) as error:
        print(f"[evaluation] final security failed reason={error}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
