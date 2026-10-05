"""Model-call metadata is exact, bounded, lifecycle-safe, and content-free."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    ModelCallTraceManager,
    model_call_trace_fingerprint,
)
from agentops_incident_commander.domain import (
    MAX_MODEL_COST_NANOUNITS,
    MAX_MODEL_TOKENS,
    ActorId,
    AuditEvent,
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    ModelCallId,
    ModelCallStatus,
    ModelCallTrace,
    ModelCost,
    ModelCostSource,
    ModelMetering,
    ModelMeteringUnavailableReason,
    ModelTokenUsage,
    PromptDefinition,
    PromptId,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptPurpose,
    PromptSchemaCompatibility,
    PromptTraceLink,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    WorkflowRunId,
)

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


def active_prompt() -> PromptDefinition:
    return PromptDefinition.create(
        prompt_id=PromptId("diagnosis-root-cause"),
        version=SemanticVersion("1.2.3"),
        purpose=PromptPurpose.DIAGNOSIS,
        content="Use only resolvable evidence.",
        model_parameters=PromptModelParameters("mock", "model-v1", 0, 10_000, 2_048, 7),
        schema_compatibility=PromptSchemaCompatibility(
            SemanticVersion("2.0.0"), SemanticVersion("3.0.0")
        ),
        trace=PromptTraceLink(
            ActorId("admin"), CorrelationId("prompt-correlation"), CausationId("prompt-create"), NOW
        ),
        status=PromptLifecycleStatus.ACTIVE,
    )


def started_trace(**overrides: Any) -> ModelCallTrace:
    values: dict[str, object] = {
        "call_id": ModelCallId("model-call-1"),
        "tenant_id": TenantId("tenant-1"),
        "incident_id": IncidentId("incident-1"),
        "workflow_run_id": WorkflowRunId("workflow-1"),
        "node": "diagnosis.hypothesis",
        "attempt": 1,
        "prompt": active_prompt(),
        "request_hash": Sha256Digest("a" * 64),
        "correlation_id": CorrelationId("correlation-1"),
        "causation_id": CausationId("node-1"),
        "started_at": NOW,
    }
    values.update(overrides)
    return ModelCallTrace.start(**values)  # type: ignore[arg-type]


def usage() -> ModelTokenUsage:
    return ModelTokenUsage(100, 20, 10, 5, 120)


def cost() -> ModelCost:
    return ModelCost(12_345, "USD", ModelCostSource.RATE_CARD_CALCULATED, SemanticVersion("1.0.0"))


def metering() -> ModelMetering:
    return ModelMetering(usage(), cost())


class MemoryStore:
    def __init__(self) -> None:
        self.trace: ModelCallTrace | None = None
        self.audit: list[AuditEvent] = []

    async def start(self, trace: ModelCallTrace, audit_event: AuditEvent) -> None:
        self.trace = trace
        self.audit.append(audit_event)

    async def finish(
        self, expected: ModelCallTrace, completed: ModelCallTrace, audit_event: AuditEvent
    ) -> None:
        assert self.trace == expected
        self.trace = completed
        self.audit.append(audit_event)


@pytest.mark.anyio
async def test_manager_records_exact_content_free_start_and_success_metadata() -> None:
    store = MemoryStore()
    ids = count(1)
    moments = iter((NOW, NOW, NOW + timedelta(seconds=2), NOW + timedelta(seconds=2)))
    manager = ModelCallTraceManager(
        store, clock=lambda: next(moments), id_factory=lambda: f"trace-id-{next(ids)}"
    )
    started = await manager.start(
        tenant_id=TenantId("tenant-1"),
        incident_id=IncidentId("incident-1"),
        workflow_run_id=WorkflowRunId("workflow-1"),
        node="diagnosis.hypothesis",
        attempt=1,
        prompt=active_prompt(),
        request_hash=Sha256Digest("a" * 64),
        actor_id=ActorId("diagnosis-worker"),
        correlation_id=CorrelationId("correlation-1"),
        causation_id=CausationId("node-1"),
    )
    completed = await manager.finish(
        started,
        status=ModelCallStatus.SUCCEEDED,
        metering=metering(),
        actor_id=ActorId("diagnosis-worker"),
        response_hash=Sha256Digest("b" * 64),
    )

    assert completed.status is ModelCallStatus.SUCCEEDED
    assert completed.prompt_fingerprint == active_prompt().content_fingerprint
    assert completed.input_schema_version == SemanticVersion("2.0.0")
    assert completed.output_schema_version == SemanticVersion("3.0.0")
    assert store.trace == completed
    assert [event.type for event in store.audit] == ["model.call_started", "model.call_finished"]
    assert store.audit[-1].request_hash == model_call_trace_fingerprint(started)
    assert store.audit[-1].result_hash == model_call_trace_fingerprint(completed)
    assert not hasattr(completed, "prompt_content")
    assert not hasattr(completed, "request_body")
    assert not hasattr(completed, "response_body")


@pytest.mark.parametrize(
    ("tokens", "message"),
    [
        ((-1, 0, 0, 0, -1), "bounded"),
        ((MAX_MODEL_TOKENS + 1, 0, 0, 0, MAX_MODEL_TOKENS + 1), "bounded"),
        ((True, 0, 0, 0, 1), "bounded"),
        ((1, 0, 2, 0, 1), "cached"),
        ((0, 1, 0, 2, 1), "reasoning"),
        ((1, 1, 0, 0, 3), "total"),
    ],
)
def test_token_usage_rejects_inconsistent_or_unbounded_counts(
    tokens: tuple[Any, Any, Any, Any, Any], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        ModelTokenUsage(*tokens)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"amount_nanounits": -1}, "nanounits"),
        ({"amount_nanounits": MAX_MODEL_COST_NANOUNITS + 1}, "nanounits"),
        ({"amount_nanounits": True}, "nanounits"),
        ({"currency": "usd"}, "currency"),
        ({"source": "reported"}, "provenance"),
        ({"rate_card_version": "1.0.0"}, "provenance"),
    ],
)
def test_cost_rejects_ambiguous_or_invalid_measurements(
    overrides: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "amount_nanounits": 1,
        "currency": "USD",
        "source": ModelCostSource.PROVIDER_REPORTED,
        "rate_card_version": SemanticVersion("1.0.0"),
    }
    values.update(overrides)
    with pytest.raises(InvalidDomainValueError, match=message):
        ModelCost(**values)  # type: ignore[arg-type]


def test_metering_is_complete_or_explicitly_unavailable() -> None:
    assert (
        ModelMetering(
            None, None, ModelMeteringUnavailableReason.CALL_FAILED_BEFORE_METERING
        ).token_usage
        is None
    )
    with pytest.raises(InvalidDomainValueError, match="complete"):
        ModelMetering(usage(), None)
    with pytest.raises(InvalidDomainValueError, match="unavailable reason"):
        ModelMetering(usage(), cost(), ModelMeteringUnavailableReason.PROVIDER_DID_NOT_RETURN)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"node": "bad node"}, "node"),
        ({"attempt": 0}, "attempt"),
        ({"prompt": cast(PromptDefinition, object())}, "Prompt reference"),
        ({"request_hash": cast(Sha256Digest, object())}, "request hash"),
    ],
)
def test_start_rejects_invalid_identity_and_metadata(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        started_trace(**overrides)


def test_start_requires_active_registered_prompt() -> None:
    with pytest.raises(InvalidDomainValueError, match="ACTIVE"):
        started_trace(prompt=replace(active_prompt(), status=PromptLifecycleStatus.EVALUATED))


@pytest.mark.parametrize(
    ("status", "response_hash", "failure_code", "message"),
    [
        (ModelCallStatus.STARTED, None, None, "terminal"),
        (ModelCallStatus.SUCCEEDED, None, None, "response hash"),
        (ModelCallStatus.SUCCEEDED, Sha256Digest("b" * 64), "error", "only"),
        (ModelCallStatus.FAILED, None, None, "failure code"),
        (ModelCallStatus.TIMED_OUT, None, "unsafe error text", "failure code"),
    ],
)
def test_finish_enforces_terminal_contract(
    status: ModelCallStatus,
    response_hash: Sha256Digest | None,
    failure_code: str | None,
    message: str,
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        started_trace().finish(
            status=status,
            completed_at=NOW + timedelta(seconds=1),
            metering=metering(),
            response_hash=response_hash,
            failure_code=failure_code,
        )


def test_failure_and_refusal_support_hash_only_or_unavailable_metering() -> None:
    unavailable = ModelMetering(
        None, None, ModelMeteringUnavailableReason.CALL_FAILED_BEFORE_METERING
    )
    timed_out = started_trace().finish(
        status=ModelCallStatus.TIMED_OUT,
        completed_at=NOW + timedelta(seconds=1),
        metering=unavailable,
        failure_code="provider_timeout",
    )
    refused = started_trace().finish(
        status=ModelCallStatus.REFUSED,
        completed_at=NOW + timedelta(seconds=1),
        metering=metering(),
        response_hash=Sha256Digest("c" * 64),
        failure_code="safety_refusal",
    )
    assert timed_out.response_hash is None
    assert refused.response_hash == Sha256Digest("c" * 64)
    with pytest.raises(InvalidDomainValueError, match="finish once"):
        refused.finish(
            status=ModelCallStatus.FAILED,
            completed_at=NOW + timedelta(seconds=2),
            metering=unavailable,
            failure_code="duplicate",
        )


def test_trace_rejects_invalid_direct_terminal_state_and_schema() -> None:
    base = started_trace()
    with pytest.raises(InvalidDomainValueError, match="terminal metadata"):
        replace(base, response_hash=Sha256Digest("b" * 64))
    with pytest.raises(InvalidDomainValueError, match="completion time"):
        replace(
            base,
            status=ModelCallStatus.FAILED,
            completed_at=NOW - timedelta(seconds=1),
            metering=metering(),
            failure_code="provider_error",
        )
    with pytest.raises(InvalidDomainValueError, match="schema version"):
        replace(base, schema_version="2.0.0")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": cast(ModelCallId, object())}, "identity"),
        ({"node": cast(str, 1)}, "node"),
        ({"attempt": cast(int, "1")}, "attempt"),
        ({"attempt": True}, "attempt"),
        ({"prompt": cast(Any, object())}, "Prompt reference"),
        ({"prompt_fingerprint": cast(Any, object())}, "Prompt fingerprint"),
        ({"provider": cast(str, 1)}, "provider"),
        ({"provider": "bad provider"}, "provider"),
        ({"model": "bad model"}, "model"),
        ({"temperature_basis_points": cast(int, "0")}, "temperature"),
        ({"top_p_basis_points": True}, "top-p"),
        ({"max_output_tokens": cast(int, "2048")}, "output token"),
        ({"temperature_basis_points": -1}, "temperature"),
        ({"temperature_basis_points": 20_001}, "temperature"),
        ({"top_p_basis_points": 0}, "top-p"),
        ({"top_p_basis_points": 10_001}, "top-p"),
        ({"max_output_tokens": 0}, "output token"),
        ({"max_output_tokens": 32_769}, "output token"),
        ({"input_schema_version": cast(Any, "1.0.0")}, "schema versions"),
        ({"output_schema_version": cast(Any, "1.0.0")}, "schema versions"),
        ({"request_hash": cast(Any, object())}, "request hash"),
        ({"status": cast(Any, "STARTED")}, "status"),
    ],
)
def test_trace_rejects_invalid_direct_metadata(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        replace(cast(Any, started_trace()), **overrides)


def test_terminal_trace_requires_completion_and_metering() -> None:
    base = started_trace()
    with pytest.raises(InvalidDomainValueError, match="completion time"):
        replace(base, status=ModelCallStatus.FAILED, failure_code="provider_error")
    with pytest.raises(InvalidDomainValueError, match="metering"):
        replace(
            base,
            status=ModelCallStatus.FAILED,
            completed_at=NOW + timedelta(seconds=1),
            failure_code="provider_error",
        )
