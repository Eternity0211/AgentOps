"""Snapshot failure is retained without reading labels or fabricating usage."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from evaluation.live_gateway import SERVICES, local_definitions
from evaluation.observation_snapshot import write_snapshot
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.run_snapshot_comparison import run_snapshot


def test_unavailable_snapshot_sources_route_to_handoff(tmp_path: Path) -> None:
    import json

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
        body = json.loads(json.loads(request.content)["messages"][1]["content"])
        if "plan" in body["output_schema"]["properties"]:
            output = {
                "plan": {
                    "schema_version": "1.0.0",
                    "plan_id": "plan",
                    "summary": "Inspect unavailable metrics",
                    "steps": [
                        {
                            "step_id": "metrics",
                            "objective": "Inspect metrics",
                            "expected_source": "METRIC",
                            "parallel_group": 0,
                        }
                    ],
                },
                "tool_calls": [
                    {
                        "step_id": "metrics",
                        "tool_name": "query_metrics",
                        "tool_version": "2.0.0",
                        "arguments": {"service": "order"},
                    }
                ],
            }
        else:
            assert len(body["context"]["evidence_ids"]) == 1
            assert body["context"]["observations"][0]["summary"].startswith("{\"error_code\"")
            assert (
                body["context"]["unavailable_reads"][0]["error_code"]
                == "SNAPSHOT_CAPTURE_FAILED"
            )
            output = {
                "schema_version": "1.0.0",
                "incident_id": body["context"]["incident_id"],
                "disposition": "HUMAN_HANDOFF",
                "candidates": [],
                "missing_evidence": ["current metrics"],
                "explanation": "Current evidence source is unavailable",
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
    assert outcome.status == "SUCCEEDED"
    assert outcome.disposition == "HUMAN_HANDOFF"
    assert outcome.missing_evidence_count == 1
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
    report_file = tmp_path / "run/single-agent/instance-0000000000000001/diagnosis-report.json"
    stored = json.loads(report_file.read_text(encoding="utf-8"))
    assert stored["report"]["disposition"] == "HUMAN_HANDOFF"
    assert stored["validated_report_hash"] == stored["stored_report_hash"]
