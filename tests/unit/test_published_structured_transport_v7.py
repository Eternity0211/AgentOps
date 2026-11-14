from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.score_transport_pair import score_pair

ROOT = Path("evaluation/results/structured-reliability/v7")
RUN = ROOT / "run-001"
PLAN = Path("evaluation/real_protocol/v10/structured-transport-pair.json")


def test_candidate_1_11_publication_recomputes_token_improvement(tmp_path: Path) -> None:
    expected = json.loads((RUN / "analysis/score.json").read_text("utf-8"))
    actual = score_pair(PLAN, RUN, tmp_path / "score")

    assert json.loads(json.dumps(actual)) == expected
    assert actual["acceptance"]["passed"] is True
    assert actual["audit"]["candidate-1.11"]["terminal_schema_protocol_invalids"] == 0
    metrics = {item["metric_id"]: item for item in actual["paired_result"]["metrics"]}
    assert metrics["input-tokens"]["claim"] == "IMPROVED"
    median = next(
        item for item in metrics["input-tokens"]["estimates"] if item["statistic"] == "median"
    )
    assert median["baseline"] == 9672
    assert median["candidate"] == 9426
    assert median["absolute_delta_interval"]["upper"] < 0


def test_candidate_1_11_hash_manifest() -> None:
    expected = json.loads((ROOT / "file-hashes.json").read_text("utf-8"))
    actual = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }

    assert actual == expected
