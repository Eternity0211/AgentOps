"""Real-model proposals remain typed, bounded and non-authoritative."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from evaluation.structured_model import (
    ModelPurpose,
    StructuredEvaluationModel,
    StructuredModelFailure,
    StructuredTransportProfile,
    compile_real_plan,
)

from agentops_incident_commander.application import (
    PlanningBudgets,
    ToolPayloadValidationError,
    evidence_gate_decision_fingerprint,
)
from agentops_incident_commander.domain import (
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceId,
    IncidentId,
    InvalidDomainValueError,
    Sha256Digest,
    ToolRegistry,
)
from agentops_incident_commander.infrastructure.tool_adapters import query_metrics_definition


def report() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "incident_id": "incident-1",
        "disposition": "CANDIDATES",
        "candidates": [
            {
                "candidate_id": "cause",
                "rank": 1,
                "statement": "Bounded cause",
                "supporting_evidence_ids": ["e1"],
                "counter_evidence_ids": [],
                "counter_evidence_treatment": "NOT_APPLICABLE",
                "counter_evidence_explanation": None,
                "missing_evidence": [],
                "uncertainty": "Limited scope",
                "confidence_basis_points": 5000,
            }
        ],
        "missing_evidence": [],
        "explanation": "Bounded diagnosis",
    }


def body(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 100,
            "total_tokens": 200,
            "prompt_cache_hit_tokens": 50,
        },
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}],
    }


def client(output: dict[str, Any], events: list[dict[str, Any]]) -> StructuredEvaluationModel:
    return StructuredEvaluationModel(
        "test-only",
        events.append,
        max_calls=1,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body(output))),
    )


def test_report_usage_hashes_budget_and_no_payload_in_journal() -> None:
    events: list[dict[str, Any]] = []
    model = client(report(), events)
    result = model.invoke(
        ModelPurpose.DIAGNOSE, {"incident_id": "incident-1", "evidence_ids": ["e1"]}
    )
    assert result.input_tokens == 100 and result.cached_input_tokens == 50
    assert result.cost_upper_bound_nanousd == 150000
    assert events[0]["status"] == "STARTED" and events[1]["status"] == "SUCCEEDED"
    assert "Bounded cause" not in json.dumps(events) and "test-only" not in json.dumps(events)
    with pytest.raises(StructuredModelFailure, match="MODEL_CALL_BUDGET_EXHAUSTED"):
        model.invoke(ModelPurpose.DIAGNOSE, {})


@pytest.mark.parametrize("case", ["overflow", "extra", "incident", "reference"])
def test_diagnosis_gets_one_bounded_content_free_schema_repair(case: str) -> None:
    events: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        output = report()
        if len(requests) == 1:
            if case == "overflow":
                output["explanation"] = "REJECTED_MARKER" + "x" * 512
            elif case == "extra":
                output["steps_note"] = "REJECTED_MARKER"
            elif case == "incident":
                output["incident_id"] = "other"
            else:
                output["candidates"][0]["supporting_evidence_ids"] = ["fabricated"]
        return httpx.Response(200, json=body(output))

    model = StructuredEvaluationModel(
        "test-only", events.append, max_calls=2, transport=httpx.MockTransport(handle)
    )
    result = model.invoke(
        ModelPurpose.DIAGNOSE, {"incident_id": "incident-1", "evidence_ids": ["e1"]}
    )

    assert result.output.incident_id == "incident-1"  # type: ignore[attr-defined]
    assert result.input_tokens == 200 and result.output_tokens == 200
    assert result.cached_input_tokens == 100
    assert result.cost_upper_bound_nanousd == 300000
    assert len(requests) == 2 and len(events) == 4
    repair = json.loads(requests[1]["messages"][1]["content"])["repair"]
    assert repair["repair_attempt"] == 1
    assert repair["original_request_hash"] == events[0]["request_hash"]
    assert repair["error_code"] in {"INVALID_RESPONSE", "INCIDENT_MISMATCH", "UNKNOWN_REFERENCE"}
    assert "REJECTED_MARKER" not in requests[1]["messages"][1]["content"]
    assert events[1]["status"] == "FAILED"
    assert events[2]["repair_attempt"] == 1
    assert events[3]["status"] == "SUCCEEDED"


def test_schema_repair_is_attempted_only_once() -> None:
    events: list[dict[str, Any]] = []
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        output = report()
        output["explanation"] = "x" * 513
        return httpx.Response(200, json=body(output))

    model = StructuredEvaluationModel(
        "test-only", events.append, max_calls=4, transport=httpx.MockTransport(handle)
    )
    with pytest.raises(StructuredModelFailure, match="INVALID_RESPONSE"):
        model.invoke(
            ModelPurpose.DIAGNOSE, {"incident_id": "incident-1", "evidence_ids": ["e1"]}
        )

    assert calls == 2
    assert [event["repair_attempt"] for event in events] == [0, 0, 1, 1]


def test_frozen_baseline_profile_has_old_prompt_and_never_repairs() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        output = report()
        output["explanation"] = "x" * 513
        return httpx.Response(200, json=body(output))

    model = StructuredEvaluationModel(
        "test-only",
        lambda event: None,
        max_calls=4,
        profile=StructuredTransportProfile.BASELINE_1_4,
        transport=httpx.MockTransport(handle),
    )
    with pytest.raises(StructuredModelFailure, match="INVALID_RESPONSE"):
        model.invoke(
            ModelPurpose.DIAGNOSE, {"incident_id": "incident-1", "evidence_ids": ["e1"]}
        )

    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert "at most 512 characters" not in payload["messages"][0]["content"]


def test_field_budgets_are_explicit_and_repair_never_applies_to_remediation() -> None:
    payload = StructuredEvaluationModel.request_payload(
        ModelPurpose.DIAGNOSE, {"incident_id": "incident-1", "evidence_ids": []}
    )
    assert "at most 512 characters" in payload["messages"][0]["content"]
    assert "at most 256 characters" in payload["messages"][0]["content"]

    events: list[dict[str, Any]] = []
    gate = EvidenceGateDecision(
        incident_id=IncidentId("incident-1"),
        candidate_id="cause",
        outcome=EvidenceGateOutcome.PASS,
        reasons=(),
        evaluated_evidence_ids=(EvidenceId("e1"), EvidenceId("e2")),
        rules_version="1.1.0",
        input_fingerprint=Sha256Digest("a" * 64),
        evaluated_at=datetime.now(UTC),
    )
    invalid = {"unexpected": True}
    model = StructuredEvaluationModel(
        "test-only",
        events.append,
        max_calls=4,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=body(invalid))
        ),
    )
    with pytest.raises(StructuredModelFailure, match="INVALID_RESPONSE"):
        model.invoke(ModelPurpose.REMEDIATE, {"incident_id": "incident-1"}, gate=gate)
    assert len(events) == 2


def test_candidate_1_6_adds_machine_readable_generation_constraints() -> None:
    context = {"incident_id": "incident-1", "evidence_ids": []}
    diagnosis = StructuredEvaluationModel.request_payload(
        ModelPurpose.DIAGNOSE,
        context,
        profile=StructuredTransportProfile.CANDIDATE_1_6,
    )
    user = json.loads(diagnosis["messages"][1]["content"])

    assert user["output_constraints"]["required_literal_values"] == {
        "incident_id": "incident-1"
    }
    assert user["output_constraints"]["safe_text_caps_characters"]["explanation"] == 320
    assert "Copy every required literal value exactly" in diagnosis["messages"][0]["content"]

    plan = StructuredEvaluationModel.request_payload(
        ModelPurpose.PLAN,
        {"incident_id": "incident-1"},
        profile=StructuredTransportProfile.CANDIDATE_1_6,
    )
    plan_constraints = json.loads(plan["messages"][1]["content"])["output_constraints"]
    assert plan_constraints["forbidden_fields"] == [
        "steps_note",
        "comments",
        "explanations",
    ]

    frozen = StructuredEvaluationModel.request_payload(
        ModelPurpose.DIAGNOSE,
        context,
        profile=StructuredTransportProfile.CANDIDATE_1_5,
    )
    assert "output_constraints" not in json.loads(frozen["messages"][1]["content"])


@pytest.mark.parametrize(
    "case,expected",
    [
        ("timeout", "TIMEOUT"),
        ("transport", "TRANSPORT_ERROR"),
        ("auth", "HTTP_401"),
        ("truncated", "INCOMPLETE_OUTPUT"),
        ("large", "RESPONSE_TOO_LARGE"),
        ("usage", "INVALID_USAGE"),
        ("total", "INVALID_USAGE"),
        ("cache", "INVALID_USAGE"),
        ("schema", "INVALID_RESPONSE"),
        ("incident", "INCIDENT_MISMATCH"),
        ("reference", "UNKNOWN_REFERENCE"),
    ],
)
def test_failures_are_content_free_and_preserve_observed_usage(case: str, expected: str) -> None:
    events: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if case == "timeout":
            raise httpx.ReadTimeout("sensitive")
        if case == "transport":
            raise httpx.ConnectError("sensitive")
        if case == "auth":
            return httpx.Response(401, text="sensitive")
        if case == "large":
            return httpx.Response(200, content=b"x" * 262145)
        output = report()
        if case == "schema":
            output = {}
        if case == "incident":
            output["incident_id"] = "other"
        if case == "reference":
            output["candidates"][0]["supporting_evidence_ids"] = ["fabricated"]
        response = body(output)
        if case == "usage":
            response["usage"]["prompt_tokens"] = True
        if case == "total":
            response["usage"]["total_tokens"] = 999
        if case == "cache":
            response["usage"]["prompt_cache_hit_tokens"] = 999
        if case == "truncated":
            response["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=response)

    model = StructuredEvaluationModel(
        "test-only", events.append, transport=httpx.MockTransport(handle)
    )
    with pytest.raises(StructuredModelFailure, match=expected):
        model.invoke(ModelPurpose.DIAGNOSE, {"incident_id": "incident-1", "evidence_ids": ["e1"]})
    assert events[-1]["status"] == "FAILED"
    assert "sensitive" not in json.dumps(events)
    if case == "schema":
        assert events[-1]["usage"]["total_tokens"] == 200


def test_preflight_and_audit_failure_dispatch_nothing() -> None:
    events: list[dict[str, Any]] = []
    model = client(report(), events)
    with pytest.raises(StructuredModelFailure, match="GATE_PASS_REQUIRED"):
        model.invoke(ModelPurpose.REMEDIATE, {})
    with pytest.raises(StructuredModelFailure, match="CONTEXT_BUDGET_EXCEEDED"):
        model.invoke(ModelPurpose.PLAN, {"text": "x" * 32769})
    assert events == []

    def unavailable(event: dict[str, Any]) -> None:
        raise OSError("audit unavailable")

    with pytest.raises(OSError):
        StructuredEvaluationModel("test-only", unavailable).invoke(ModelPurpose.PLAN, {})
    with pytest.raises(ValueError):
        StructuredEvaluationModel("", events.append)


def test_real_plan_compiles_against_registry_and_rejects_arbitrary_targets() -> None:
    output: dict[str, Any] = {
        "plan": {
            "schema_version": "1.0.0",
            "plan_id": "plan-1",
            "summary": "Inspect metrics",
            "steps": [
                {
                    "step_id": "metrics",
                    "objective": "Inspect errors",
                    "expected_source": "METRIC",
                    "parallel_group": 0,
                }
            ],
        },
        "tool_calls": [
            {
                "step_id": "metrics",
                "tool_name": "query_metrics",
                "tool_version": "1.0.0",
                "arguments": {
                    "service": "order",
                    "environment": "staging",
                    "metric": "http_request_error_rate",
                    "start": "2026-11-03T00:00:00+00:00",
                    "end": "2026-11-03T00:01:00+00:00",
                    "step_seconds": 5,
                },
            }
        ],
    }
    registry = ToolRegistry((query_metrics_definition(),))
    budgets = PlanningBudgets(8, 4, 120000, 16000, 10000000)
    result = client(output, []).invoke(ModelPurpose.PLAN, {})
    compiled = compile_real_plan(result, registry, budgets)
    assert compiled.calls[0].tool_name == "query_metrics"
    assert len(compiled.calls[0].query_fingerprint) == 64
    with pytest.raises(InvalidDomainValueError):
        compile_real_plan(
            result,
            registry,
            budgets,
            prior_query_fingerprints=frozenset({compiled.calls[0].query_fingerprint}),
        )
    output["tool_calls"][0]["arguments"]["service"] = "https://untrusted.invalid"
    malicious = client(output, []).invoke(ModelPurpose.PLAN, {})
    with pytest.raises(ToolPayloadValidationError):
        compile_real_plan(malicious, registry, budgets)
    with pytest.raises(InvalidDomainValueError):
        compile_real_plan(result, registry, PlanningBudgets(8, 4, 120000, 1, 1))


def test_remediation_must_bind_exact_gate_and_evaluated_references() -> None:
    gate = EvidenceGateDecision(
        incident_id=IncidentId("incident-1"),
        candidate_id="cause",
        outcome=EvidenceGateOutcome.PASS,
        reasons=(),
        evaluated_evidence_ids=(EvidenceId("e1"), EvidenceId("e2")),
        rules_version="1.1.0",
        input_fingerprint=Sha256Digest("a" * 64),
        evaluated_at=datetime.now(UTC),
    )
    output: dict[str, Any] = {
        "schema_version": "1.0.0",
        "proposal_id": "proposal-1",
        "proposal_version": 1,
        "incident_id": "incident-1",
        "candidate_id": "cause",
        "evidence_gate_input_fingerprint": gate.input_fingerprint.value,
        "evidence_gate_decision_fingerprint": evidence_gate_decision_fingerprint(gate).value,
        "action": "rollback_service",
        "parameters": {"service": "order", "introducing_deployment_evidence_id": "e1"},
        "prerequisites": {"current_version_evidence_id": "e2"},
        "verification_conditions": {
            "max_error_rate_basis_points": 100,
            "max_p95_latency_ms": 1000,
            "stability_window_seconds": 60,
        },
        "failure_handling": {"route": "HUMAN_HANDOFF", "max_rediagnosis_attempts": 0},
        "compensation_eligible": False,
        "risk_assumptions": ["Local bounded rollback"],
    }
    result = client(output, []).invoke(
        ModelPurpose.REMEDIATE, {"incident_id": "incident-1"}, gate=gate
    )
    assert result.output is not None
    output["candidate_id"] = "forged"
    with pytest.raises(StructuredModelFailure, match="GATE_BINDING_MISMATCH"):
        client(output, []).invoke(ModelPurpose.REMEDIATE, {"incident_id": "incident-1"}, gate=gate)
