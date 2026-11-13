from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("evaluation/results/memory-runtime/v1")


def test_live_memory_runtime_audits_preserve_failure_and_success() -> None:
    failed = json.loads((ROOT / "run-001/audit.json").read_text("utf-8"))
    passed = json.loads((ROOT / "run-002/audit.json").read_text("utf-8"))

    assert failed["checkout_statuses"] == [200] * 6
    assert failed["memory_facts"] == []
    assert failed["after_cleanup_status"] == 200
    assert passed["accepted"] is True
    assert all(passed["acceptance"].values())
    assert passed["memory_facts"][0]["classification"] == "SUSTAINED_RETENTION"
    assert passed["memory_facts"][0]["sample_count"] == 6
    assert passed["memory_facts"][0]["gc_pair_count"] == 1
    assert passed["deployment_facts"][0]["version"] == "2.0.0"
    assert passed["after_cleanup_status"] == 200
    assert passed["recovery_credit"] is False


def test_live_memory_runtime_hash_manifest() -> None:
    expected = json.loads((ROOT / "file-hashes.json").read_text("utf-8"))
    actual = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }
    assert actual == expected
