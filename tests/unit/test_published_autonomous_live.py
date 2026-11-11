"""Verify the archived live read evidence against its tool audit and case records."""

import hashlib
import json
from pathlib import Path


def test_trace_first_live_evidence_resolves() -> None:
    root = Path("evaluation/results/autonomous-live/v5")
    events = [json.loads(line) for line in (root / "events.jsonl").read_bytes().splitlines()]
    calls = {event["call_id"] for event in events if event.get("kind") == "tool-audit"}
    cases = json.loads((root / "results.json").read_bytes())["results"]
    verified = set()
    assert len(cases) == 6
    for case in cases:
        evidence = root / "evidence" / case["incident_id"]
        assert case["after_checkout"]["status"] == 200
        for manifest in evidence.glob("evidence-records*.json"):
            for row in json.loads(manifest.read_bytes()):
                item = row["evidence"]
                digest = item["content_hash"]["value"]
                assert item["incident_id"]["value"] == case["incident_id"]
                assert (
                    hashlib.sha256(
                        (evidence / "blobs" / digest[:2] / digest).read_bytes()
                    ).hexdigest()
                    == digest
                )
                call = item["lineage"]["tool_call_id"]["value"]
                assert call not in verified
                verified.add(call)
    assert verified == calls
    assert len(verified) == 40
