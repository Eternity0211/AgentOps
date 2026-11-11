"""Published diagnosis-quality replay is complete, hash-bound and Evidence-resolvable."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import protocol_hash

ROOT = Path("evaluation/results/diagnosis-quality/v1")
RUN = ROOT / "run-001"
PROTOCOL = Path("evaluation/real_protocol/v1/plan.json")


def test_published_diagnosis_quality_hashes_and_scores() -> None:
    hashes = json.loads((ROOT / "file-hashes.json").read_text(encoding="utf-8"))
    actual = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }
    assert actual == hashes and len(hashes) == 1318

    outcomes = OutcomeLedger(RUN / "outcomes").collect(protocol_hash=protocol_hash(PROTOCOL))
    assert len(outcomes) == 81
    score = json.loads((RUN / "score.json").read_text(encoding="utf-8"))
    assert score["modes"] == {
        "single-agent": {
            "fault_denominator": 18,
            "top1": 11,
            "top3": 11,
            "control_denominator": 9,
            "safe_controls": 9,
            "failures": 1,
        },
        "controlled-graph": {
            "fault_denominator": 18,
            "top1": 11,
            "top3": 11,
            "control_denominator": 9,
            "safe_controls": 8,
            "failures": 3,
        },
        "controlled-graph-simulated-memory": {
            "fault_denominator": 18,
            "top1": 11,
            "top3": 11,
            "control_denominator": 9,
            "safe_controls": 9,
            "failures": 2,
        },
    }


def test_published_diagnosis_quality_evidence_and_calls() -> None:
    audit = json.loads((RUN / "audit-summary.json").read_text(encoding="utf-8"))
    assert audit["cases"] == 81 and audit["reports"] == 75
    assert audit["model_calls"] == 199 and audit["gate_passes"] == 15
    assert audit["evidence_references"] == 150
    assert audit["resolved_same_incident_references"] == 150
    assert audit["artifact_hash_checks"] == audit["artifact_hash_matches"] == 150

    cases = json.loads((RUN / "case-audit.json").read_text(encoding="utf-8"))
    assert len(cases) == 81
    assert all(row["references_resolved"] == len(row["references"]) for row in cases)
    controls = {
        "normal": 3,
        "insufficient-evidence": 3,
        "counter-evidence": 3,
    }
    for mode in audit["modes"]:
        rows = [row for row in cases if row["mode"] == mode]
        assert {kind: sum(row["stratum"] == kind for row in rows) for kind in controls} == controls
    assert all(not list(RUN.rglob(name)) for name in ("approvals.json", "executions.json"))
