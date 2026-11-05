"""Published real-provider preflight keeps refusals and exact request denominators."""

import hashlib
import json
from pathlib import Path

from evaluation.structured_model import fingerprint


def test_published_lab_bootstrap_retains_real_refusals_and_bindings() -> None:
    base = Path("evaluation/results/lab-prompt-bootstrap")
    starts = metered = bound = 0
    for root in sorted(base.glob("v*/run-*")):
        hashes = json.loads((root / "file-hashes.json").read_text(encoding="utf-8"))
        for name, digest in hashes.items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
        events = [
            json.loads(s) for s in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        starts += sum(e.get("status") == "STARTED" for e in events)
        metered += sum(isinstance(e.get("usage"), dict) for e in events)
        registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
        assert len(registry) == 3 and {r["status"] for r in registry} == {"DRAFT"}
        summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        assert (
            summary["activated_count"]
            == summary["approval_decisions"]
            == summary["recovery_executions"]
            == 0
        )
        for purpose, passed in (("plan", True), ("diagnose", False), ("remediate", True)):
            row = json.loads((root / "regression" / f"{purpose}.json").read_text(encoding="utf-8"))
            assert row["passed"] is passed
            if "validated_output" in row:
                assert any(
                    e.get("request_hash") == row["request_hash"]
                    and e.get("validated_output_hash") == fingerprint(row["validated_output"])
                    and e.get("status") == "SUCCEEDED"
                    for e in events
                )
                bound += 1
            if purpose == "diagnose" and "gate_results" in row:
                assert row["gate_results"][0]["reasons"] == ["MISSING_EVIDENCE_DECLARED"]
        if (root / "audit.json").exists():
            audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
            assert len(audit) == 3 and all(e["event_type"] == "prompt.drafted" for e in audit)
    assert starts == metered == 9 and bound == 8
    published = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    assert sum(r["provider_starts"] for r in published) == starts
    assert sum(r["metered_responses"] for r in published) == metered
