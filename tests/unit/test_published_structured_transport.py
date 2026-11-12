"""Published structured-transport pair is complete, reproducible and hash-bound."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.score_transport_pair import score_pair

ROOT = Path("evaluation/results/structured-reliability/v1")
RUN = ROOT / "run-001"
PLAN = Path("evaluation/real_protocol/v4/structured-transport-pair.json")


def test_published_pair_recomputes_from_immutable_outputs(tmp_path: Path) -> None:
    expected = json.loads((RUN / "analysis/score.json").read_text(encoding="utf-8"))
    actual = score_pair(PLAN, RUN, tmp_path / "analysis")

    assert json.loads(json.dumps(actual)) == expected
    assert actual["profile_outcomes"] == {"baseline-1.4": 81, "candidate-1.5": 81}
    assert actual["acceptance"] == {
        "candidate_terminal_schema_protocol_invalids_zero": False,
        "safe_control_noninferiority_by_mode": True,
        "evidence_integrity": True,
        "passed": False,
        "safe_controls_by_mode": {
            "single-agent": {"baseline-1.4": 7, "candidate-1.5": 8},
            "controlled-graph": {"baseline-1.4": 8, "candidate-1.5": 8},
            "controlled-graph-simulated-memory": {
                "baseline-1.4": 8,
                "candidate-1.5": 9,
            },
        },
    }
    assert actual["audit"]["baseline-1.4"]["terminal_schema_protocol_invalids"] == 12
    assert actual["audit"]["candidate-1.5"]["terminal_schema_protocol_invalids"] == 4


def test_published_pair_hash_manifest_and_claims() -> None:
    hashes = json.loads((ROOT / "file-hashes.json").read_text(encoding="utf-8"))
    actual_hashes = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }
    assert actual_hashes == hashes

    score = json.loads((RUN / "analysis/score.json").read_text(encoding="utf-8"))
    claims = {item["metric_id"]: item["claim"] for item in score["paired_result"]["metrics"]}
    assert claims == {
        "valid-outcome": "NO_PROVEN_IMPROVEMENT",
        "safe-control": "NO_PROVEN_IMPROVEMENT",
        "evidence-integrity": "NO_PROVEN_IMPROVEMENT",
        "duration-ms": "REGRESSED",
        "input-tokens": "REGRESSED",
        "output-tokens": "REGRESSED",
        "cost-upper-bound": "REGRESSED",
    }
    assert score["missing_resource_pairs"] == 0
