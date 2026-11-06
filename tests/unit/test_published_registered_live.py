"""Published actual registered rehearsal retains refusal and cleanup denominators."""

import hashlib
import json
from pathlib import Path


def test_registered_live_archive_counts_and_failures() -> None:
    root = Path("evaluation/results/registered-live/v1/run-001")
    for name, digest in json.loads((root / "file-hashes.json").read_text(encoding="utf-8")).items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    cases = [json.loads((root / f"case-{n}.json").read_text(encoding="utf-8")) for n in range(3)]
    assert [r["status"] for r in cases] == ["HUMAN_HANDOFF", "FAILED", "FAILED"]
    assert all(r["after_checkout"]["status"] == 200 for r in cases)
    assert all(r["cleanup_exit"] == 0 for r in cases[1:])
    assert all(not r["approval_decided"] and not r["recovery_executed"] for r in cases)
    events = [
        json.loads(s) for s in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert sum(e.get("status") == "STARTED" for e in events) == summary["provider_starts"] == 11
    assert summary["cases"] == 3 and summary["pending_approvals"] == 0
    state = json.loads((root / "sql-state.json").read_text(encoding="utf-8"))
    assert len(state["incidents"]) == 3 and {r["state"] for r in state["incidents"]} == {
        "NEEDS_HUMAN"
    }
    assert len(state["model_traces"]) == 8 and state["approvals"] == []
