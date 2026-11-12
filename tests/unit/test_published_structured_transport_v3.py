"""Candidate 1.7 publication preserves both the safe handoff and failed acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.audit_transport_followthrough import audit_followthrough
from evaluation.score_transport_pair import score_pair

ROOT = Path("evaluation/results/structured-reliability/v3")
RUN = ROOT / "run-001"
PLAN = Path("evaluation/real_protocol/v6/structured-transport-pair.json")


def test_candidate_1_7_score_recomputes(tmp_path: Path) -> None:
    expected = json.loads((RUN / "analysis/score.json").read_text(encoding="utf-8"))
    actual = score_pair(PLAN, RUN, tmp_path / "score")

    assert json.loads(json.dumps(actual)) == expected
    assert actual["profile_outcomes"] == {"baseline-1.6": 81, "candidate-1.7": 81}
    assert actual["acceptance"]["passed"] is False
    assert actual["audit"]["candidate-1.7"]["terminal_schema_protocol_invalids"] == 1
    assert actual["acceptance"]["safe_control_noninferiority_by_mode"] is True
    assert actual["acceptance"]["evidence_integrity"] is True


def test_candidate_1_7_followthrough_audit_recomputes(tmp_path: Path) -> None:
    expected = json.loads(
        (RUN / "analysis/repair-followthrough.json").read_text(encoding="utf-8")
    )
    actual = audit_followthrough(PLAN, RUN, tmp_path / "followthrough.json")

    assert actual == expected
    assert actual["profiles"]["baseline-1.6"]["failed_after_successful_repair"] == 3
    assert actual["profiles"]["candidate-1.7"] == {
        "successful_repair_outcomes": 0,
        "failed_after_successful_repair": 0,
        "budget_allow_decisions": 0,
        "budget_handoff_decisions": 37,
    }
    assert actual["acceptance"]["passed"] is True


def test_candidate_1_7_hash_manifest() -> None:
    expected = json.loads((ROOT / "file-hashes.json").read_text(encoding="utf-8"))
    actual = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }
    assert actual == expected
