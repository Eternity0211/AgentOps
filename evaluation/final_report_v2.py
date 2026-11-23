"""Generate the current comparative report with the disjoint FC4f4 lab result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from evaluation.final_report import build_report, publish

SCORE = Path("evaluation/results/confirmation-v2/run-001/analysis/score.json")
PROTOCOL = Path("evaluation/confirmation_v2/plan.json")
MANIFEST = Path("evaluation/results/confirmation-v2/run-001/file-hashes.json")


def build_report_v2(root: Path = Path(".")) -> dict[str, Any]:
    report = build_report(root)
    score = json.loads((root / SCORE).read_text(encoding="utf-8"))
    primary = score["comparisons"]["single-to-graph"]["result"]
    if score["outcome_count"] != 480:
        raise ValueError("confirmation outcome count mismatch")
    top1 = next(item for item in primary["metrics"] if item["metric_id"] == "top1")
    if (
        top1["claim"] != "IMPROVED"
        or not primary["critical_safety_gate_passed"]
        or not primary["cost_latency_gate_passed"]
    ):
        raise ValueError("confirmation improvement gate did not pass")
    report["schema_version"] = "final-comparative-report/2.0.0"
    report["report_date"] = "2026-11-23"
    report["outcome_summary"] = (
        "On a disjoint 160-case synthetic lab cohort, controlled graph improved Top-1 from "
        "14/120 to 47/120 (+27.5 points; paired 95% +18.33 to +36.67). Critical safety and "
        "predeclared median latency/cost ceilings passed. Median latency and estimated cost "
        "still regressed, with larger P95 overhead. PostgreSQL local throughput improved "
        "through four workers and regressed at eight."
    )
    report["comparisons"] += [
        {
            "work_id": "FC4-LAB",
            "metric": item["metric_id"],
            "statistic": estimate["statistic"],
            "unit": "rate" if estimate["statistic"] == "rate" else item["metric_id"],
            "baseline": estimate["baseline"],
            "candidate": estimate["candidate"],
            "absolute_delta": estimate["absolute_delta"],
            "relative_delta": estimate["relative_delta"],
            "delta_95pct_interval": [
                estimate["absolute_delta_interval"]["lower"],
                estimate["absolute_delta_interval"]["upper"],
            ],
            "status": item["claim"],
            "scope": (
                "Disjoint synthetic lab; single model versus controlled graph; "
                "rate-card cost is not billing."
            ),
            "denominator": item["pair_count"],
        }
        for item in primary["metrics"]
        for estimate in item["estimates"]
    ]
    report["lab_confirmation"] = {
        "status": "IMPROVED",
        "outcomes": 480,
        "top1_baseline_correct": 14,
        "top1_candidate_correct": 47,
        "critical_safety_gate_passed": primary["critical_safety_gate_passed"],
        "cost_latency_gate_passed": primary["cost_latency_gate_passed"],
    }
    report["frozen_protocols"]["FC4_lab_protocol_sha256"] = score["protocol_sha256"]
    report["failures"]["FC4_lab"] = {
        mode: arm["failures"] for mode, arm in score["arms"].items()
    }
    for path in (SCORE, PROTOCOL, MANIFEST):
        report["source_artifacts"].append(
            {
                "path": path.as_posix(),
                "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest(),
            }
        )
    report["limitations"].append(
        "The FC4 lab gain does not measure human diagnosis time, actual recovery, "
        "recurrence or billed cost."
    )
    report["reproduction"].append(
        ".venv/Scripts/python -m evaluation.final_report_v2 --output "
        "evaluation/results/final-comparative-report/v2 --doc docs/REAL_EVALUATION_REPORT_V2.md"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--doc", type=Path, required=True)
    args = parser.parse_args()
    publish(build_report_v2(), args.output, args.doc)


if __name__ == "__main__":
    main()
