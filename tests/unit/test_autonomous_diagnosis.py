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
from langgraph.checkpoint.memory import InMemorySaver


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
                "supporting_evidence_ids": ["evidence-r0-metrics", "evidence-r0-logs"],
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


@pytest.mark.parametrize("replan,single_pass", [(False, False), (True, False), (False, True)])
def test_autonomous_plan_gateway_evidence_and_gate(
    tmp_path: Path, replan: bool, single_pass: bool
) -> None:
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

    model_requests: list[bool] = []

    def respond(request: httpx.Request) -> httpx.Response:
        model_requests.append(True)
        payload = json.loads(request.content)
        schema = json.loads(payload["messages"][1]["content"])["output_schema"]
        output = plan() if "plan" in schema["properties"] else diagnosis()
        if replan and len(model_requests) == 2:
            output["candidates"][0]["missing_evidence"] = ["deployment evidence"]
        if replan and len(model_requests) == 3:
            output = {
                "plan": {
                    "schema_version": "1.0.0",
                    "plan_id": "replan",
                    "summary": "Inspect missing deployment evidence",
                    "steps": [
                        {
                            "step_id": "deployment",
                            "objective": "Inspect deployment",
                            "expected_source": "DEPLOYMENT",
                            "parallel_group": 0,
                        }
                    ],
                },
                "tool_calls": [
                    {
                        "step_id": "deployment",
                        "tool_name": "query_deployments",
                        "tool_version": "2.0.0",
                        "arguments": {"service": "order"},
                    }
                ],
            }
        if replan and len(model_requests) == 4:
            output["candidates"][0]["supporting_evidence_ids"] = [
                "evidence-r0-metrics",
                "evidence-r1-deployment",
            ]
        if "plan" not in schema["properties"]:
            context = json.loads(payload["messages"][1]["content"])["context"]
            observations = context["observations"]
            metric_id = next(o["id"] for o in observations if o["source"] == "metrics")
            other_source = "deployments" if replan and len(model_requests) == 4 else "logs"
            other_id = next(o["id"] for o in observations if o["source"] == other_source)
            output["candidates"][0]["supporting_evidence_ids"] = [metric_id, other_id]
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
    saver = InMemorySaver()
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
            checkpointer=None if single_pass else saver,
            single_pass=single_pass,
        )
    )
    assert state.phase.value == "COMPLETE"
    assert len(dispatched) == (3 if replan else 2)
    assert state.budgets.used_tool_calls == (3 if replan else 2)
    assert state.budgets.used_model_calls == (4 if replan else 2)
    assert state.budgets.used_replans == (1 if replan else 0)
    assert services.gates[0].outcome.value == "PASS"
    assert len([event for event in events if event.get("kind") == "tool-audit"]) >= 4
    assert services.evidence is not None
    if single_pass:
        return
    calls_before_replay = len(dispatched)
    journal_before_replay = len(events)
    replay_state, replay_services = asyncio.run(
        investigate(
            model,
            "incident-1",
            "Checkout errors",
            tmp_path,
            now - timedelta(minutes=1),
            now,
            events.append,
            adapters=adapters,
            checkpointer=saver,
        )
    )
    assert replay_state == state and replay_services.resumed
    assert len(dispatched) == calls_before_replay
    assert len(events) == journal_before_replay
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


@pytest.mark.parametrize(
    "mode", ["missing", "workflow", "call", "empty_calls", "reader", "tenant", "incident"]
)
def test_gate_restore_rejects_unbound_report(mode: str) -> None:
    from types import SimpleNamespace
    from typing import cast

    from evaluation.autonomous_diagnosis import AutonomousServices

    from agentops_incident_commander.domain import ActorId, IncidentId, Principal, Role, TenantId

    async def latest(**kwargs: Any) -> Any:
        return (
            None
            if mode == "missing"
            else SimpleNamespace(
                workflow_run_id=SimpleNamespace(
                    value="other" if mode == "workflow" else "workflow"
                ),
                model_call_id=SimpleNamespace(value="other" if mode == "call" else "call"),
                tenant_id=TenantId("other" if mode == "tenant" else "tenant"),
                incident_id=IncidentId("other" if mode == "incident" else "incident"),
            )
        )

    service = AutonomousServices.__new__(AutonomousServices)
    service.evidence = cast(Any, object())
    service.report = None
    service.incident = "incident"
    service.principal = Principal(ActorId("reader"), TenantId("tenant"), frozenset({Role.OPERATOR}))
    service.model_invoker = cast(
        Any,
        SimpleNamespace(report_reader=None if mode == "reader" else SimpleNamespace(latest=latest)),
    )
    state = cast(
        Any,
        SimpleNamespace(
            workflow_run_id="workflow",
            model_call_ids=() if mode == "empty_calls" else ("call",),
            budgets=SimpleNamespace(used_replans=0),
        ),
    )
    with pytest.raises(ValueError, match=r"report reader|report binding"):
        asyncio.run(service.evaluate_evidence_gate(state, operation_id="operation"))


@pytest.mark.parametrize("trace_id", ["a", "336fcab452c224308d894456ed8467e", "A" * 32])
def test_tempo_short_trace_ids_are_padded_with_bounded_paths(trace_id: str) -> None:
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/search":
            return httpx.Response(200, json={"traces": [{"traceID": trace_id}]})
        return httpx.Response(200, json={"batches": []})

    now = datetime.now(UTC)
    adapter = LocalReadAdapter(
        "query_traces", now - timedelta(minutes=1), now, transport=httpx.MockTransport(respond)
    )
    result = asyncio.run(adapter.invoke(None, {"service": "gateway"}))  # type: ignore[arg-type]
    assert paths == ["/api/search", "/api/traces/" + trace_id.lower().zfill(32)]
    assert len(json.loads(result["provenance"])["requests"]) == 2


@pytest.mark.parametrize("trace_id", [None, 1, "", "0", "0" * 32, "a" * 33, "../x", "a?x", "g"])
def test_tempo_invalid_trace_ids_never_dispatch_detail(trace_id: Any) -> None:
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"traces": [{"traceID": trace_id}]})

    now = datetime.now(UTC)
    adapter = LocalReadAdapter(
        "query_traces", now - timedelta(minutes=1), now, transport=httpx.MockTransport(respond)
    )
    with pytest.raises(ValueError, match="invalid telemetry trace identity"):
        asyncio.run(adapter.invoke(None, {"service": "gateway"}))  # type: ignore[arg-type]
    assert paths == ["/api/search"]
