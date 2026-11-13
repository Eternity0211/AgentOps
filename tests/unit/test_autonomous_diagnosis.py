"""Model planning reaches the actual Gateway and deterministic Gate without write authority."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from evaluation.autonomous_diagnosis import (
    build_candidate_diagnosis_context,
    build_diagnosis_context,
    investigate,
)
from evaluation.live_gateway import SOURCES, LocalReadAdapter, local_definitions
from evaluation.structured_model import StructuredEvaluationModel, StructuredTransportProfile
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


def memory_span(service: str, timestamp: int, retained: int) -> dict[str, Any]:
    return {
        "service": service,
        "start": str(timestamp - 1),
        "end": str(timestamp),
        "attributes": [
            {
                "key": "process.memory.retained_bytes",
                "value": {"intValue": str(retained)},
            },
            {
                "key": "process.memory.retention_limit_bytes",
                "value": {"intValue": "33554432"},
            },
        ],
    }


def test_candidate_memory_context_refuses_three_rises_without_gc() -> None:
    observation = {
        "id": "evidence-trace-a",
        "source": "traces",
        "summary": json.dumps(
            [memory_span("order", index * 10, index * 1_048_576) for index in range(1, 6)]
        ),
    }
    baseline = build_diagnosis_context([observation], {})
    candidate = build_candidate_diagnosis_context([observation], {})

    assert baseline["memory_retention_by_service"][0]["sustained_increase_observed"] is True
    assert candidate["memory_retention_by_service"][0]["classification"] == "INSUFFICIENT"
    assert candidate["memory_evidence_contract"] == "gc-aware/1.0.0"


def test_diagnosis_context_binds_chronological_memory_facts_to_evidence() -> None:
    observations = [
        {
            "id": "evidence-trace-a",
            "source": "traces",
            "summary": json.dumps(
                [
                    memory_span("order", 30, 8_388_608),
                    memory_span("order", 10, 5_242_880),
                    memory_span("order", 20, 7_340_032),
                ]
            ),
        },
        {
            "id": "evidence-deployment-a",
            "source": "deployments",
            "summary": json.dumps(
                [{"service": "order", "version": "1.0.0", "previous_version": None}]
            ),
        },
    ]

    context = build_diagnosis_context(observations, {})

    memory = context["memory_retention_by_service"][0]
    assert memory["service"] == "order"
    assert [item["retained_bytes"] for item in memory["samples"]] == [
        5_242_880,
        7_340_032,
        8_388_608,
    ]
    assert memory["delta_bytes"] == 3_145_728
    assert memory["direction"] == "INCREASING"
    assert memory["sustained_increase_observed"] is True
    assert all(item["evidence_ids"] == ["evidence-trace-a"] for item in memory["samples"])
    assert context["deployment_facts"] == [
        {
            "evidence_id": "evidence-deployment-a",
            "service": "order",
            "version": "1.0.0",
            "previous_version": None,
            "causal_inference": "NOT_ESTABLISHED_BY_DEPLOYMENT_RECORD",
        }
    ]


def test_normal_short_rise_and_deployment_only_do_not_claim_sustained_memory_growth() -> None:
    normal = build_diagnosis_context(
        [{"id": "trace-normal", "source": "traces", "summary": "[]"}], {}
    )
    short_rise = build_diagnosis_context(
        [
            {
                "id": "trace-short",
                "source": "traces",
                "summary": json.dumps(
                    [memory_span("order", 10, 1_048_576), memory_span("order", 20, 2_097_152)]
                ),
            }
        ],
        {},
    )
    deployment_only = build_diagnosis_context(
        [
            {
                "id": "deployment-only",
                "source": "deployments",
                "summary": json.dumps(
                    [{"service": "order", "version": "2.0.0", "previous_version": "1.0.0"}]
                ),
            }
        ],
        {},
    )

    assert normal["memory_retention_by_service"] == []
    assert short_rise["memory_retention_by_service"][0]["sustained_increase_observed"] is False
    assert deployment_only["memory_retention_by_service"] == []
    assert deployment_only["deployment_facts"][0]["causal_inference"].startswith(
        "NOT_ESTABLISHED"
    )


def test_compact_facts_keep_excluded_evidence_referenceable() -> None:
    observations = [
        {
            "id": "trace-large",
            "source": "traces",
            "summary": json.dumps(
                [
                    memory_span("order", 10, 1_048_576),
                    memory_span("order", 20, 2_097_152),
                    memory_span("order", 30, 3_145_728),
                ]
            ),
        },
        {"id": "log-excluded", "source": "logs", "summary": "x" * 2_000},
    ]

    context = build_diagnosis_context(observations, {}, byte_budget=1)

    assert context["observations"] == []
    assert context["context_budget"]["admitted_evidence_ids"] == []
    assert context["context_budget"]["excluded_evidence_ids"] == [
        "trace-large",
        "log-excluded",
    ]
    assert context["context_budget"]["compact_fact_evidence_ids"] == ["trace-large"]
    assert context["evidence_ids"] == ["trace-large"]


def test_diagnosis_context_records_unavailable_reads_without_evidence_ids() -> None:
    context = build_diagnosis_context(
        [],
        {
            "call-1": {
                "source": "metrics",
                "tool_name": "query_metrics",
                "error_code": "SNAPSHOT_SOURCE_UNAVAILABLE",
                "attempts": 1,
            }
        },
    )

    assert context["evidence_ids"] == []
    assert context["unavailable_reads"] == [
        {
            "call_id": "call-1",
            "source": "metrics",
            "tool_name": "query_metrics",
            "error_code": "SNAPSHOT_SOURCE_UNAVAILABLE",
            "attempts": 1,
        }
    ]


@pytest.mark.parametrize(
    "replan,single_pass,budget_guard",
    [(False, False, False), (True, False, False), (False, True, False), (True, False, True)],
)
def test_autonomous_plan_gateway_evidence_and_gate(
    tmp_path: Path, replan: bool, single_pass: bool, budget_guard: bool
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
            context = json.loads(payload["messages"][1]["content"])["context"]
            assert [(q["tool_name"], q["arguments"]) for q in context["prior_tool_queries"]] == [
                ("query_metrics", {"service": "order"}),
                ("query_logs", {"service": "order"}),
            ]
            assert [q["query_fingerprint"] for q in context["prior_tool_queries"]] == context[
                "prior_queries"
            ]
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
        "test-only",
        events.append,
        transport=httpx.MockTransport(respond),
        profile=(
            StructuredTransportProfile.CANDIDATE_1_7
            if budget_guard
            else StructuredTransportProfile.CANDIDATE_1_6
        ),
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
    assert state.phase.value == ("HUMAN_HANDOFF" if budget_guard else "COMPLETE")
    expected_tools = 2 if budget_guard else 3 if replan else 2
    expected_model_calls = 2 if budget_guard else 4 if replan else 2
    assert len(dispatched) == expected_tools
    assert state.budgets.used_tool_calls == expected_tools
    assert state.budgets.used_model_calls == expected_model_calls
    assert state.budgets.used_replans == (1 if replan and not budget_guard else 0)
    assert services.gates[0].outcome.value == ("FAIL" if budget_guard else "PASS")
    if budget_guard:
        assert any(
            event.get("kind") == "model-budget-decision"
            and event["decision"] == "HUMAN_HANDOFF"
            for event in events
        )
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


def test_metric_queries_use_the_observation_window() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert "[20375ms]" in request.url.params["query"]
        return httpx.Response(200, json={"data": {"result": []}})

    now = datetime.now(UTC)
    adapter = LocalReadAdapter(
        "query_metrics",
        now - timedelta(milliseconds=20375),
        now,
        transport=httpx.MockTransport(respond),
    )
    result = asyncio.run(adapter.invoke(None, {"service": "order"}))  # type: ignore[arg-type]
    assert len(json.loads(result["provenance"])["requests"]) == 3


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


def test_tempo_truncation_retains_late_error_span() -> None:
    spans: list[dict[str, Any]] = [{"name": "routine", "attributes": ["x" * 1000]}] * 14
    spans += [{"name": "failure", "status": {"code": "STATUS_CODE_ERROR"}}]

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search":
            return httpx.Response(200, json={"traces": [{"traceID": "a"}]})
        resource = {
            "attributes": [
                {"key": "service.name", "value": {"stringValue": "agentops-simulator-order"}}
            ]
        }
        return httpx.Response(
            200, json={"batches": [{"resource": resource, "scopeSpans": [{"spans": spans}]}]}
        )

    now = datetime.now(UTC)
    adapter = LocalReadAdapter(
        "query_traces", now - timedelta(minutes=1), now, transport=httpx.MockTransport(respond)
    )
    result = asyncio.run(adapter.invoke(None, {"service": "gateway"}))  # type: ignore[arg-type]
    retained = json.loads(result["summary"])
    assert retained[0]["name"] == "failure"
    assert retained[0]["service"] == "agentops-simulator-order"
    assert len(result["summary"]) <= 12000
    assert json.loads(result["provenance"])["dropped_records"] == len(spans) - len(retained)


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


@pytest.mark.parametrize("mode", ["missing_effect", "changed_checkpoint", "missing_compiled"])
def test_replan_prior_queries_refuse_missing_or_changed_bindings(mode: str) -> None:
    from types import SimpleNamespace

    from evaluation.autonomous_diagnosis import AutonomousServices

    async def load(*args: Any) -> None:
        return None

    fake: Any = SimpleNamespace(
        compiled=None if mode != "changed_checkpoint" else SimpleNamespace(calls=()),
        effects=SimpleNamespace(load=load) if mode == "missing_effect" else None,
        effect_binding=lambda state: {},
    )
    state: Any = SimpleNamespace(
        budgets=SimpleNamespace(used_replans=1), tool_query_fingerprints=("changed",)
    )
    with pytest.raises(ValueError, match="prior plan"):
        asyncio.run(AutonomousServices.prior_tool_queries(fake, state))
