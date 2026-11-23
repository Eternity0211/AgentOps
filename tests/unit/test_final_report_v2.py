from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.final_report import render_markdown
from evaluation.final_report_v2 import build_report_v2

ROOT = Path("evaluation/results/final-comparative-report/v2")
DOC = Path("docs/REAL_EVALUATION_REPORT_V2.md")


def test_published_v2_report_recomputes_from_frozen_sources() -> None:
    report = json.loads((ROOT / "report.json").read_text(encoding="utf-8"))
    assert report == build_report_v2()
    assert report["schema_version"] == "final-comparative-report/2.0.0"
    assert (ROOT / "README.md").read_text(encoding="utf-8") == render_markdown(report)
    assert DOC.read_text(encoding="utf-8") == render_markdown(report)
    for source in report["source_artifacts"]:
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]


def test_v2_reports_proven_lab_gain_and_external_boundaries() -> None:
    report = build_report_v2()
    assert report["lab_confirmation"] == {
        "status": "IMPROVED",
        "outcomes": 480,
        "top1_baseline_correct": 14,
        "top1_candidate_correct": 47,
        "critical_safety_gate_passed": True,
        "cost_latency_gate_passed": True,
    }
    lab = [row for row in report["comparisons"] if row["work_id"] == "FC4-LAB"]
    top1 = next(row for row in lab if row["metric"] == "top1")
    assert top1["baseline"] == 14 / 120
    assert top1["candidate"] == 47 / 120
    assert top1["status"] == "IMPROVED"
    assert len(lab) >= 14
    assert {item["work_id"] for item in report["external_blockers"]} >= {
        "FC4", "FC5", "FC6", "FC7", "FC8"
    }
