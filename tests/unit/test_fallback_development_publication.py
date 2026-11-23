"""Recompute the complete published development score from immutable raw outcomes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.audit_fallback_development_quality import audit
from evaluation.score_fallback_development_pair import decide

PLAN = Path("evaluation/final_diagnosis_optimization/v2/pair-plan.json")
RESULTS = Path("evaluation/results/final-diagnosis-optimization/v2/run-001")


def test_development_archive_manifest_binds_every_result_file() -> None:
    manifest = json.loads((RESULTS / "file-hashes.json").read_text(encoding="utf-8"))
    files = {
        path.relative_to(RESULTS).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in RESULTS.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }
    assert len(files) == 1206
    assert files == manifest


def test_development_safety_resource_and_quality_scores_reproduce(tmp_path: Path) -> None:
    output = tmp_path / "score"
    decision = decide(PLAN, RESULTS, output)
    quality = audit(PLAN, RESULTS, output / "quality-audit.json")
    assert decision == json.loads((RESULTS / "analysis" / "decision.json").read_text())
    assert quality == json.loads((RESULTS / "analysis" / "quality-audit.json").read_text())
    assert json.loads((output / "score.json").read_text()) == json.loads(
        (RESULTS / "analysis" / "score.json").read_text()
    )
    assert decision["failures"] == {"baseline-1.11": 0, "candidate-1.12": 0}
    assert quality["counts"]["top1"] == {"baseline": 15, "candidate": 12, "denominator": 18}
    assert quality["fallback_events"] == {"baseline-1.11": 0, "candidate-1.12": 0}
