from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.score_transport_pair import score_pair

ROOT = Path("evaluation/results/structured-reliability/v6")
RUN = ROOT / "run-001"
PLAN = Path("evaluation/real_protocol/v9/structured-transport-pair.json")


def test_candidate_1_10_publication_recomputes_without_efficiency_claim(tmp_path: Path) -> None:
    expected = json.loads((RUN / "analysis/score.json").read_text("utf-8"))
    actual = score_pair(PLAN, RUN, tmp_path / "score")

    assert json.loads(json.dumps(actual)) == expected
    assert actual["acceptance"]["passed"] is True
    assert actual["audit"]["candidate-1.10"]["terminal_schema_protocol_invalids"] == 0
    assert actual["audit"]["candidate-1.10"]["initial_schema_protocol_invalids"] == 11
    assert {metric["claim"] for metric in actual["paired_result"]["metrics"]} == {
        "NO_PROVEN_IMPROVEMENT"
    }


def test_candidate_1_10_hash_manifest() -> None:
    expected = json.loads((ROOT / "file-hashes.json").read_text("utf-8"))
    actual = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }

    assert actual == expected
