"""Measured rules publication keeps exact denominators and frozen source bytes."""

import hashlib
import json
from pathlib import Path


def test_published_rules_snapshot_results_and_sources() -> None:
    root = Path("evaluation/results/rules-snapshots/v1/run-001")
    hashes = json.loads((root / "file-hashes.json").read_text(encoding="utf-8"))
    for name, digest in hashes.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    for name, digest in metadata["source_hashes"].items():
        assert (
            hashlib.sha256((root / "source" / (Path(name).name + ".bin")).read_bytes()).hexdigest()
            == digest
        )
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in root.glob("instance-*.json")]
    assert len(rows) == len({r["outcome"]["instance_id"] for r in rows}) == 27
    assert sum(len(r["snapshot_reads"]) for r in rows) == metadata["snapshot_reads"] == 324
    assert sum(r["outcome"]["status"] == "FAILED" for r in rows) == 3
    score = json.loads((root / "score.json").read_text(encoding="utf-8"))
    assert score["modes"]["rules-only"] == {
        "fault_denominator": 18,
        "top1": 0,
        "top3": 0,
        "control_denominator": 9,
        "safe_controls": 6,
        "failures": 3,
    }
    assert not score["comparison_complete"]
    assert metadata["model_calls"] == metadata["live_tool_calls"] == 0
