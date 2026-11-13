from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.score_memory_context_pair import score_pair

ROOT = Path("evaluation/results/memory-context/v3")
RUN = ROOT / "run-001"
LABELS = Path("evaluation/memory_context/v3/evaluator_only/labels.json")


def test_expanded_memory_score_recomputes_and_passes_acceptance(tmp_path: Path) -> None:
    expected = json.loads((RUN / "score.json").read_text("utf-8"))
    actual = score_pair(LABELS, RUN, tmp_path / "score.json", claim_profile="v2")
    assert actual == expected
    baseline = actual["arms"]["baseline-context"]
    candidate = actual["arms"]["candidate-context"]
    assert (baseline["correct"], candidate["correct"]) == (9, 10)
    assert (baseline["sustained_detected"], candidate["sustained_detected"]) == (1, 2)
    assert (baseline["safe_negatives"], candidate["safe_negatives"]) == (8, 8)
    assert (baseline["failures"], candidate["failures"]) == (0, 0)


def test_expanded_memory_hash_manifest() -> None:
    expected = json.loads((ROOT / "file-hashes.json").read_text("utf-8"))
    actual = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }
    assert actual == expected
