"""Snapshot failure is retained without reading labels or fabricating usage."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from evaluation.live_gateway import SERVICES, local_definitions
from evaluation.observation_snapshot import write_snapshot
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.run_snapshot_comparison import run_snapshot


def test_failed_snapshot_run_is_durably_retained(tmp_path: Path) -> None:
    reads: dict[str, Any] = {
        f"{d.name}:{s}": {"status": "FAILED", "error_code": "CAPTURE_FAILED"}
        for d in local_definitions()
        for s in SERVICES
    }
    path = tmp_path / "snapshot.json"
    now = datetime.now(UTC)
    digest = write_snapshot(path, "instance-0000000000000001", now, now, reads, "observed error")

    def respond(request: httpx.Request) -> httpx.Response:
        assert b"public_cause_taxonomy" in request.content
        return httpx.Response(401)

    outcome = run_snapshot(
        path,
        digest,
        "single-agent",
        tmp_path / "run",
        "a" * 64,
        key="test-only",
        transport=httpx.MockTransport(respond),
    )
    assert outcome.status == "FAILED" and outcome.input_tokens is None
    assert OutcomeLedger(tmp_path / "run/outcomes").collect(protocol_hash="a" * 64) == (outcome,)


def test_snapshot_success_uses_read_replay_and_retains_usage(tmp_path: Path) -> None:
    import json

    reads: dict[str, Any] = {
        f"{d.name}:{s}": {"status": "FAILED", "error_code": "CAPTURE_FAILED"}
        for d in local_definitions()
        for s in SERVICES
    }
    reads["query_logs:order"] = {
        "status": "SUCCEEDED",
        "output": {
            "source": "logs",
            "summary": "No current error observed",
            "provenance": "{}",
            "complete_window": False,
            "records_seen": 1,
        },
    }
    path = tmp_path / "snapshot.json"
    now = datetime.now(UTC)
    digest = write_snapshot(path, "instance-0000000000000001", now, now, reads, "observations")

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(json.loads(request.content)["messages"][1]["content"])
        if "plan" in body["output_schema"]["properties"]:
            output = {
                "plan": {
                    "schema_version": "1.0.0",
                    "plan_id": "plan",
                    "summary": "Inspect logs",
                    "steps": [
                        {
                            "step_id": "logs",
                            "objective": "Inspect logs",
                            "expected_source": "LOG",
                            "parallel_group": 0,
                        }
                    ],
                },
                "tool_calls": [
                    {
                        "step_id": "logs",
                        "tool_name": "query_logs",
                        "tool_version": "2.0.0",
                        "arguments": {"service": "order"},
                    }
                ],
            }
        else:
            output = {
                "schema_version": "1.0.0",
                "incident_id": body["context"]["incident_id"],
                "disposition": "HUMAN_HANDOFF",
                "candidates": [],
                "missing_evidence": ["independent current source"],
                "explanation": "Insufficient evidence",
            }
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}],
            },
        )

    outcome = run_snapshot(
        path,
        digest,
        "single-agent",
        tmp_path / "run",
        "a" * 64,
        key="test-only",
        transport=httpx.MockTransport(respond),
    )
    assert outcome.status == "SUCCEEDED" and outcome.disposition == "HUMAN_HANDOFF"
    assert outcome.input_tokens == outcome.output_tokens == 20
