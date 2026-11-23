"""Apply frozen FC4f development gates to the complete paired transport score."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

from evaluation.outcome_ledger import OutcomeLedger
from evaluation.score_transport_pair import score_pair

METRICS = (
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "cost_upper_bound_nanousd",
)


def _p95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def decide(plan_path: Path, results: Path, output: Path) -> dict[str, Any]:
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    if plan.get("schema_version") != "diagnosis-fallback-development-pair/1.0.0":
        raise ValueError("unknown fallback decision protocol")
    baseline_name, candidate_name = tuple(plan["profiles"])
    protocol_hash = hashlib.sha256(plan_bytes).hexdigest()
    rows = {
        name: OutcomeLedger(results / name / "outcomes").collect(protocol_hash=protocol_hash)
        for name in (baseline_name, candidate_name)
    }
    expected = plan["expected_cases"]
    if any(len(items) != expected for items in rows.values()):
        raise ValueError("fallback decision requires every paired outcome")
    paired = {name: {item.instance_id: item for item in items} for name, items in rows.items()}
    if paired[baseline_name].keys() != paired[candidate_name].keys():
        raise ValueError("fallback decision pair identity mismatch")
    ceilings = plan["acceptance"]["resource_delta_ceilings"]
    if set(ceilings) != set(METRICS) or any(
        set(ceilings[name]) != {"median", "p95"}
        or any(type(value) is not int or value < 0 for value in ceilings[name].values())
        for name in METRICS
    ):
        raise ValueError("fallback decision ceilings malformed")

    scored = score_pair(plan_path, results, output)
    measured: dict[str, Any] = {}
    resource_passed = True
    for metric in METRICS:
        left = [
            getattr(paired[baseline_name][key], metric) for key in sorted(paired[baseline_name])
        ]
        right = [
            getattr(paired[candidate_name][key], metric) for key in sorted(paired[candidate_name])
        ]
        if any(type(value) is not int for value in (*left, *right)):
            measured[metric] = {"available": False, "passed": False}
            resource_passed = False
            continue
        baseline = [int(value) for value in left]
        candidate = [int(value) for value in right]
        median_delta = statistics.median(candidate) - statistics.median(baseline)
        p95_delta = _p95(candidate) - _p95(baseline)
        passed = median_delta <= ceilings[metric]["median"] and p95_delta <= ceilings[metric]["p95"]
        resource_passed &= passed
        measured[metric] = {
            "available": True,
            "baseline_median": statistics.median(baseline),
            "candidate_median": statistics.median(candidate),
            "median_delta": median_delta,
            "median_ceiling": ceilings[metric]["median"],
            "baseline_p95": _p95(baseline),
            "candidate_p95": _p95(candidate),
            "p95_delta": p95_delta,
            "p95_ceiling": ceilings[metric]["p95"],
            "passed": passed,
        }
    failures = {
        name: sum(item.status == "FAILED" for item in items) for name, items in rows.items()
    }
    safety_passed = bool(scored["acceptance"]["passed"]) and failures[candidate_name] == 0
    decision = {
        "schema_version": "diagnosis-fallback-development-decision/1.0.0",
        "protocol_sha256": protocol_hash,
        "outcomes_per_arm": expected,
        "failures": failures,
        "resource_metrics": measured,
        "safety_passed": safety_passed,
        "resource_passed": resource_passed,
        "passed": safety_passed and resource_passed,
        "limitation": (
            "Development snapshots; rate-card upper bound is not billed cost or human time."
        ),
    }
    (output / "decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    decide(args.plan, args.results, args.output)


if __name__ == "__main__":  # pragma: no cover
    main()
