from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.score_transport_pair import score_pair

ROOT = Path("evaluation/results/structured-reliability/v5")
RUN = ROOT / "run-001"
PLAN = Path("evaluation/real_protocol/v8/structured-transport-pair.json")


def test_candidate_1_9_failed_publication_recomputes(tmp_path: Path) -> None:
    expected = json.loads((RUN / "analysis/score.json").read_text("utf-8"))
    actual = score_pair(PLAN, RUN, tmp_path / "score")

    assert json.loads(json.dumps(actual)) == expected
    assert actual["acceptance"]["passed"] is False
    assert actual["audit"]["baseline-1.8"]["terminal_schema_protocol_invalids"] == 0
    assert actual["audit"]["candidate-1.9"]["terminal_schema_protocol_invalids"] == 1
    assert actual["repair_followthrough"]["candidate-1.9"]["failed_after_successful_repair"] == 0


def test_candidate_1_9_hash_manifest() -> None:
    expected = json.loads((ROOT / "file-hashes.json").read_text("utf-8"))
    actual = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }

    assert actual == expected
