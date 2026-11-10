"""Reconcile the real registered-call SQL export against its provider events."""

import hashlib
import json
from pathlib import Path


def test_real_registered_usage_reconciles_with_sql() -> None:
    root = Path("evaluation/results/registered-metering/v1/run-001")
    hashes = json.loads((root / "file-hashes.json").read_text(encoding="utf-8"))
    for name, digest in hashes.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    events = [
        json.loads(line)
        for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    usage = [event for event in events if event.get("event") == "model.usage_observed"]
    by_id = {event["call_id"]: event for event in usage}
    rows = json.loads((root / "sql-records.json").read_text(encoding="utf-8"))
    traces = rows["model_call_traces"]
    assert len(traces) == len(usage) == len(by_id) == 2
    assert {trace["id"] for trace in traces} == set(by_id)
    for trace in traces:
        event = by_id[trace["id"]]
        assert trace["status"] == "SUCCEEDED"
        assert trace["request_hash"] == event["request_hash"]
        for field in ("input_tokens", "output_tokens", "cached_input_tokens"):
            assert trace[field] == event[field]
        assert trace["total_tokens"] == event["input_tokens"] + event["output_tokens"]
        assert trace["cost_nanounits"] == event["cost_upper_bound_nanousd"]
        assert trace["cost_source"] == "RATE_CARD_CALCULATED"
        assert trace["rate_card_version"] == "1.0.0"
        assert event["actual_cost"] is None
    assert sum(trace["total_tokens"] for trace in traces) == 7207
    assert rows["approvals"] == rows["action_executions"] == []
