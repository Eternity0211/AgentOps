from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.score_confirmation_v2 import score

PLAN = Path("evaluation/confirmation_v2/plan.json")
RESULTS = Path("evaluation/results/confirmation-v2/run-001")


def test_confirmation_archive_binds_every_raw_and_analysis_file() -> None:
    manifest = json.loads((RESULTS / "file-hashes.json").read_text(encoding="utf-8"))
    actual = {
        path.relative_to(RESULTS).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in RESULTS.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }
    assert len(manifest) == 6035
    assert actual == manifest


def test_confirmation_score_reproduces_and_passes_frozen_gates(tmp_path: Path) -> None:
    score(PLAN, RESULTS, tmp_path / "score")
    reproduced = json.loads((tmp_path / "score/score.json").read_text(encoding="utf-8"))
    published = json.loads((RESULTS / "analysis/score.json").read_text(encoding="utf-8"))
    assert reproduced == published
    assert published["outcome_count"] == 480
    assert published["arms"]["single-agent"]["top1"] == 14
    assert published["arms"]["controlled-graph"]["top1"] == 47
    primary = published["comparisons"]["single-to-graph"]["result"]
    assert primary["critical_safety_gate_passed"] is True
    assert primary["cost_latency_gate_passed"] is True
    top1 = next(metric for metric in primary["metrics"] if metric["metric_id"] == "top1")
    assert top1["claim"] == "IMPROVED"
    assert top1["estimates"][0]["absolute_delta"] == 0.275
