"""Registered model calls refuse before dispatch when prompt/RBAC/audit bindings fail."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from itertools import count
from typing import Any

import httpx
import pytest
from evaluation.registered_model import RegisteredModelInvoker
from evaluation.structured_model import (
    ModelPurpose,
    StructuredEvaluationModel,
    StructuredModelFailure,
)

from agentops_incident_commander.application import ModelCallTraceManager
from agentops_incident_commander.domain import (
    ActorId,
    AuditEvent,
    AuthorizationError,
    CausationId,
    CorrelationId,
    IncidentId,
    ModelCallTrace,
    Principal,
    PromptDefinition,
    PromptId,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptPurpose,
    PromptSchemaCompatibility,
    PromptTraceLink,
    PromptVersionReference,
    Role,
    SemanticVersion,
    TenantId,
    WorkflowRunId,
)


@pytest.mark.parametrize(
    "mode",
    ["success", "missing", "draft", "content", "settings", "viewer", "audit", "timeout", "report"],
)
def test_registered_model_preflight_and_trace_completion(mode: str) -> None:
    now = datetime.now(UTC)
    context = {"incident_id": "incident-1", "evidence_ids": []}
    content = StructuredEvaluationModel.request_payload(ModelPurpose.DIAGNOSE, context)["messages"][
        0
    ]["content"]
    definition = PromptDefinition.create(
        prompt_id=PromptId("registered-diagnosis"),
        version=SemanticVersion("1.0.0"),
        purpose=PromptPurpose.DIAGNOSIS,
        content="wrong content" if mode == "content" else content,
        model_parameters=PromptModelParameters(
            "other" if mode == "settings" else "deepseek", "deepseek-flash", 0, 10000, 2048
        ),
        schema_compatibility=PromptSchemaCompatibility(
            SemanticVersion("1.0.0"), SemanticVersion("1.0.0")
        ),
        trace=PromptTraceLink(ActorId("admin"), CorrelationId("corr"), CausationId("cause"), now),
        status=PromptLifecycleStatus.DRAFT if mode == "draft" else PromptLifecycleStatus.ACTIVE,
    )

    class Prompts:
        async def resolve(
            self, tenant: TenantId, identifier: PromptId, version: SemanticVersion
        ) -> PromptDefinition | None:
            return None if mode == "missing" else definition

        async def active(self, tenant: TenantId, identifier: PromptId) -> PromptDefinition | None:
            return None if mode == "missing" else definition

    class Traces:
        started: ModelCallTrace | None = None
        completed: ModelCallTrace | None = None

        async def start(self, trace: ModelCallTrace, event: AuditEvent) -> None:
            if mode == "audit":
                raise OSError("durable start failed")
            self.started = trace

        async def finish(
            self, expected: ModelCallTrace, completed: ModelCallTrace, event: AuditEvent
        ) -> None:
            assert self.started == expected
            self.completed = completed

    traces = Traces()
    requests = []
    observed: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert traces.started is not None
        requests.append(True)
        if mode == "timeout":
            raise httpx.ReadTimeout("sensitive provider text")
        report = {
            "schema_version": "1.0.0",
            "incident_id": "incident-1",
            "disposition": "HUMAN_HANDOFF",
            "candidates": [],
            "missing_evidence": ["independent source"],
            "explanation": "Need current independent evidence",
        }
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(report)}}],
            },
        )

    model = StructuredEvaluationModel(
        "test-only", lambda e: None, transport=httpx.MockTransport(respond)
    )
    identifiers = count(1)
    manager = ModelCallTraceManager(
        traces, clock=lambda: now, id_factory=lambda: f"trace-{next(identifiers)}"
    )

    class Reports:
        async def record(self, record: Any, event: AuditEvent) -> Any:
            assert traces.completed is not None
            assert record.model_call_id == traces.completed.id
            raise OSError("report persistence unavailable")

    invoker = RegisteredModelInvoker(
        model,
        Prompts(),
        manager,
        {ModelPurpose.DIAGNOSE: PromptVersionReference(definition.prompt_id, definition.version)},
        Principal(
            ActorId("operator"),
            TenantId("tenant-1"),
            frozenset({Role.VIEWER if mode == "viewer" else Role.OPERATOR}),
        ),
        IncidentId("incident-1"),
        WorkflowRunId("workflow"),
        CorrelationId("corr"),
        CausationId("cause"),
        observed.append,
        report_writer=Reports() if mode == "report" else None,
    )
    if mode == "success":
        result = asyncio.run(invoker.invoke(ModelPurpose.DIAGNOSE, context))
        assert traces.completed is not None and traces.completed.status.value == "SUCCEEDED"
        assert result.call_id == traces.completed.id.value
        assert observed[-1]["input_tokens"] == 10 and observed[-1]["actual_cost"] is None
    else:
        expected = (
            AuthorizationError
            if mode == "viewer"
            else OSError
            if mode in ("audit", "report")
            else StructuredModelFailure
        )
        with pytest.raises(expected):
            asyncio.run(invoker.invoke(ModelPurpose.DIAGNOSE, context))
        if mode == "timeout":
            assert traces.completed is not None and traces.completed.status.value == "TIMED_OUT"
        elif mode == "report":
            assert traces.completed is not None and traces.completed.status.value == "SUCCEEDED"
            assert requests == [True]
        else:
            assert requests == []
    assert "sensitive provider text" not in json.dumps(observed)
    assert "Need current independent evidence" not in json.dumps(observed)
