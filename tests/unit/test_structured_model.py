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
