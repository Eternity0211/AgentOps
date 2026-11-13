from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from evaluation.capture_memory_runtime_audit import build_audit_document


def test_runtime_audit_reports_comparison_ready_cleanup_and_evidence() -> None:
    start = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)
    end = start + timedelta(minutes=1)
    span = {
        "service": "agentops-simulator-order",
        "name": "POST /v1/orders",
        "start": "1000000000",
        "end": "1100000000",
        "status": {"code": "STATUS_CODE_OK"},
        "attributes": [
            {"key": "process.memory.retained_bytes", "value": {"intValue": "1048576"}},
            {
                "key": "process.memory.retention_limit_bytes",
                "value": {"intValue": "33554432"},
            },
            {"key": "process.memory.retention_allocations", "value": {"intValue": "1"}},
            {"key": "process.memory.retention_releases", "value": {"intValue": "0"}},
        ],
    }
    observations = [
        {
            "id": "runtime-traces",
            "source": "traces",
            "summary": json.dumps([span]),
            "observed_from": start.isoformat(),
            "observed_to": end.isoformat(),
            "provenance": json.dumps({"dropped_records": 0}),
        }
    ]
    document = build_audit_document(
        run_id="run-test001",
        start=start,
        end=end,
        checkouts=[{"status": 200, "duration_ms": 10}],
        observations=observations,
        cleanup_exit=0,
        after_cleanup_status=200,
    )

    assert document["recovery_credit"] is False
    assert document["referenceable_evidence_ids"] == ["runtime-traces"]
    assert document["context_budget"]["admitted_bytes"] <= document["context_budget"]["limit_bytes"]
    assert document["service_facts"][0]["p95_duration_ms"] == 100.0
    assert document["accepted"] is False
    assert document["acceptance"]["six_successful_checkouts"] is False
    assert document["acceptance"]["release_counter_observed"] is True
