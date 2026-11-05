"""Published deterministic review retains missing reports and exact denominators."""

import hashlib
import json
from collections import Counter
from pathlib import Path


def test_published_review_hashes_and_summary() -> None:
    root = Path("evaluation/results/simulated-operator/v1/run-001")
    hashes = json.loads((root / "file-hashes.json").read_text(encoding="utf-8"))
    for name, digest in hashes.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    rows = json.loads((root / "reviews.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert len(rows) == len({(r["instance_id"], r["mode"]) for r in rows}) == 81
    assert summary["review_count"] == len(rows)
    assert summary["report_binding"] == dict(Counter(r["tasks"]["report_binding"] for r in rows))
    assert (
        summary["missing_reports"]
        == sum(r["failure_type"] == "FileNotFoundError" for r in rows)
        == 73
    )
    for name in ("declared_citations", "unresolved_citations", "task_successes", "required_tasks"):
        assert summary[name] == sum(r[name] for r in rows)
    assert summary["code_hash"] == hashes["review_archive.source.txt"]
    for row in rows:
        assert row["task_successes"] == sum(v == "PASS" for v in row["tasks"].values())
        assert row["required_tasks"] == len(row["tasks"])
        assert row["human_time_saved"] is None
        assert row["approval_decided"] is row["recovery_executed"] is False
    assert summary["human_time_saved"] is None
    assert summary["approval_decisions"] == summary["recovery_executions"] == 0
