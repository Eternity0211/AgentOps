"""Model planning reaches the actual Gateway and deterministic Gate without write authority."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from evaluation.autonomous_diagnosis import investigate
from evaluation.live_gateway import SOURCES, LocalReadAdapter, local_definitions
from evaluation.structured_model import StructuredEvaluationModel


def plan() -> dict[str, Any]:
    return {
        "plan": {
            "schema_version": "1.0.0",
            "plan_id": "plan-1",
            "summary": "Inspect sources",
            "steps": [
                {
                    "step_id": source,
                    "objective": "Inspect current source",
                    "expected_source": kind,
                    "parallel_group": 0,
                }
                for source, kind in (("metrics", "METRIC"), ("logs", "LOG"))
            ],
        },
        "tool_calls": [
            {
                "step_id": source,
                "tool_name": "query_" + source,
                "tool_version": "2.0.0",
                "arguments": {"service": "order"},
            }
            for source in ("metrics", "logs")
        ],
    }


def diagnosis() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "incident_id": "incident-1",
        "disposition": "CANDIDATES",
        "candidates": [
            {
                "candidate_id": "deployment-regression",
                "rank": 1,
                "statement": "Observed errors",
                "supporting_evidence_ids": ["evidence-metrics", "evidence-logs"],
                "counter_evidence_ids": [],
                "counter_evidence_treatment": "NOT_APPLICABLE",
                "counter_evidence_explanation": None,
                "missing_evidence": [],
                "uncertainty": "Local scope",
                "confidence_basis_points": 5000,
            }
        ],
        "missing_evidence": [],
        "explanation": "Current evidence",
    }


def test_autonomous_plan_gateway_evidence_and_gate(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    dispatched = []

    class Adapter:
        def __init__(self, name: str) -> None:
            self.name = name

        async def invoke(self, context: Any, arguments: Any) -> dict[str, Any]:
            dispatched.append(self.name)
            return {
                "source": SOURCES[self.name],
                "summary": "Observed error status 500",
                "provenance": json.dumps(
                    {
                        "tool": self.name,
                        "version": "2.0.0",
                        "requests": [{"endpoint": "fixed-local", "query": "bounded"}],
                    }
                ),
                "complete_window": False,
                "records_seen": 1,
            }

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        schema = json.loads(payload["messages"][1]["content"])["output_schema"]
        output = plan() if "plan" in schema["properties"] else diagnosis()
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}],
            },
        )

    now = datetime.now(UTC)
    model = StructuredEvaluationModel(
        "test-only", events.append, transport=httpx.MockTransport(respond)
    )
    adapters = {definition.identity: Adapter(definition.name) for definition in local_definitions()}
    state, services = asyncio.run(
        investigate(
            model,
            "incident-1",
            "Checkout errors",
            tmp_path,
            now - timedelta(minutes=1),
            now,
            events.append,
            adapters=adapters,
        )
    )
    assert state.phase.value == "COMPLETE"
    assert len(dispatched) == 2
    assert state.budgets.used_tool_calls == 2
    assert state.budgets.used_model_calls == 2
    assert services.gates[0].outcome.value == "PASS"
    assert len([event for event in events if event.get("kind") == "tool-audit"]) >= 4
    assert services.evidence is not None
    assert (
        "request_spec_00"
        in next(iter(services.evidence.records.values())).normalized_query.as_dict()
    )


def test_loki_status_and_dependency_metadata_are_preserved() -> None:
    async def run() -> dict[str, Any]:
        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "result": [
                            {
                                "stream": {
                                    "dependency": "postgresql",
                                    "outcome": "timeout",
                                    "trace_id": "omit",
                                },
                                "values": [
                                    [
                                        "1",
                                        "dependency_operation",
                                        {"http_response_status_code": "503"},
                                    ]
                                ],
                            }
                        ]
                    }
                },
            )

        now = datetime.now(UTC)
        adapter = LocalReadAdapter(
            "query_logs", now - timedelta(minutes=1), now, transport=httpx.MockTransport(respond)
        )
        return dict(await adapter.invoke(None, {"service": "order"}))  # type: ignore[arg-type]

    result = asyncio.run(run())
    assert "postgresql" in result["summary"] and "503" in result["summary"]
    assert "trace_id" not in result["summary"]
    provenance = json.loads(result["provenance"])
    assert provenance["requests"][0]["parameters"]["limit"] == "40"


def test_local_gateway_refuses_unknown_service_or_window() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        LocalReadAdapter("query_logs", now, now)
    with pytest.raises(ValueError):
        LocalReadAdapter("rollback_service", now - timedelta(minutes=1), now)
    adapter = LocalReadAdapter("query_logs", now - timedelta(minutes=1), now)
    with pytest.raises(ValueError):
        asyncio.run(adapter.invoke(None, {"service": "arbitrary"}))  # type: ignore[arg-type]
