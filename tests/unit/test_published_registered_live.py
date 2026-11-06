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


def test_registered_v2_snapshot_preserves_pending_and_adverse_review() -> None:
    root = Path("evaluation/results/registered-live/v2/run-001")
    for name, digest in json.loads((root / "file-hashes.json").read_text(encoding="utf-8")).items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    rows = json.loads((root / "sql-records.json").read_text(encoding="utf-8"))
    assert len(rows["approvals"]) == 1 and rows["approvals"][0]["status"] == "PENDING"
    assert rows["action_executions"] == [] and rows["checkpoints"]
    assert rows["diagnosis_reports"] and rows["evidence_gate_decisions"]
    evidence = {e["id"]: e for e in rows["evidence"]}
    snapshot = rows["approval_review_snapshots"][0]
    proposal = snapshot["snapshot"]["proposal"]
    source = evidence[proposal["parameters"]["introducing_deployment_evidence_id"]]
    assert source["source_type"] == "LOG"
    review = json.loads((root / "review-findings.json").read_text(encoding="utf-8"))[0]
    assert review["recommendation"] == "REJECT"
    assert review["violations"] == ["INTRODUCING_REFERENCE_NOT_DEPLOYMENT"]
    assert review["approval_decided"] is review["recovery_executed"] is False


def test_registered_v3_preserves_tool_failures_without_guard_success_claim() -> None:
    root = Path("evaluation/results/registered-live/v3/run-001")
    for name, digest in json.loads((root / "file-hashes.json").read_text(encoding="utf-8")).items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert summary["provider_starts"] == 6 and summary["pending_approvals"] == 0
    rows = json.loads((root / "sql-records.json").read_text(encoding="utf-8"))
    assert rows["diagnosis_reports"] == rows["evidence_gate_decisions"] == rows["approvals"] == []
    assert rows["action_executions"] == [] and rows["checkpoints"]
    cases = [json.loads((root / f"case-{n}.json").read_text(encoding="utf-8")) for n in range(3)]
    assert all(r["status"] == "FAILED" and r["error_type"] == "ExceptionGroup" for r in cases)
    assert all(r["after_checkout"]["status"] == 200 for r in cases)
    assert all(r["cleanup_exit"] == 0 for r in cases[1:])
    assert any(p["status"] != 200 for p in cases[0]["probes"])


def test_registered_v4_real_gate_role_refusal_without_remediation_dispatch() -> None:
    from evaluation.structured_model import fingerprint

    root = Path("evaluation/results/registered-live/v4/run-001")
    for name, digest in json.loads((root / "file-hashes.json").read_text(encoding="utf-8")).items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    rows = json.loads((root / "sql-records.json").read_text(encoding="utf-8"))
    assert len(rows["diagnosis_reports"]) == 3 and len(rows["evidence_gate_decisions"]) == 1
    assert rows["approvals"] == rows["action_executions"] == []
    refusal = [
        r for r in rows["audit_events"] if r["event_type"] == "evaluation.rollback_evidence_refused"
    ]
    assert len(refusal) == 1
    assert refusal[0]["result_hash"] == fingerprint("ROLLBACK_DISTINCT_VERSION_EVIDENCE_REQUIRED")
    cases = [json.loads((root / f"case-{n}.json").read_text(encoding="utf-8")) for n in range(3)]
    assert [r["status"] for r in cases] == ["HUMAN_HANDOFF", "FAILED", "FAILED"]
    assert cases[1]["provider_starts"] == 2 and cases[1]["gates"][0]["outcome"] == "PASS"
    assert cases[2]["error_type"] == "InvalidDomainValueError"
    assert all(r["after_checkout"]["status"] == 200 for r in cases)
    assert all(r["cleanup_exit"] == 0 for r in cases[1:])
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert summary["provider_starts"] == 10 and summary["approval_decisions"] == 0
