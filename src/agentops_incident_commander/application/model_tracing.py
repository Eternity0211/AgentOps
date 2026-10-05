"""Application orchestration for content-free model-call traces."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    ActorId,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    IncidentId,
    ModelCallId,
    ModelCallStatus,
    ModelCallTrace,
    ModelMetering,
    OpaqueIdentifier,
    PromptDefinition,
    Sha256Digest,
    TenantId,
    WorkflowRunId,
)


class ModelCallTraceStore(Protocol):
    async def start(self, trace: ModelCallTrace, audit_event: AuditEvent) -> None: ...

    async def finish(
        self,
        expected: ModelCallTrace,
        completed: ModelCallTrace,
        audit_event: AuditEvent,
    ) -> None: ...


def model_call_trace_fingerprint(trace: ModelCallTrace) -> Sha256Digest:
    payload = {
        "attempt": trace.attempt,
        "call_id": trace.id.value,
        "causation_id": trace.causation_id.value,
        "completed_at": trace.completed_at.isoformat() if trace.completed_at else None,
        "correlation_id": trace.correlation_id.value,
        "failure_code": trace.failure_code,
        "incident_id": trace.incident_id.value,
        "input_schema_version": trace.input_schema_version.value,
        "max_output_tokens": trace.max_output_tokens,
        "metering": _metering_snapshot(trace.metering),
        "model": trace.model,
        "node": trace.node,
        "output_schema_version": trace.output_schema_version.value,
        "prompt_fingerprint": trace.prompt_fingerprint.value,
        "prompt_id": trace.prompt.prompt_id.value,
        "prompt_version": trace.prompt.version.value,
        "provider": trace.provider,
        "request_hash": trace.request_hash.value,
        "response_hash": trace.response_hash.value if trace.response_hash else None,
        "seed": trace.seed,
        "started_at": trace.started_at.isoformat(),
        "status": trace.status.value,
        "temperature_basis_points": trace.temperature_basis_points,
        "tenant_id": trace.tenant_id.value,
        "top_p_basis_points": trace.top_p_basis_points,
        "workflow_run_id": trace.workflow_run_id.value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return Sha256Digest(hashlib.sha256(encoded).hexdigest())


def _metering_snapshot(metering: ModelMetering | None) -> dict[str, object] | None:
    if metering is None:
        return None
    usage = metering.token_usage
    cost = metering.cost
    return {
        "cost": (
            None
            if cost is None
            else {
                "amount_nanounits": cost.amount_nanounits,
                "currency": cost.currency,
                "rate_card_version": cost.rate_card_version.value,
                "source": cost.source.value,
            }
        ),
        "token_usage": (
            None
            if usage is None
            else {
                "cached_input_tokens": usage.cached_input_tokens,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "reasoning_tokens": usage.reasoning_tokens,
                "total_tokens": usage.total_tokens,
            }
        ),
        "unavailable_reason": (
            metering.unavailable_reason.value if metering.unavailable_reason else None
        ),
    }


class ModelCallTraceManager:
    """Record an attempted call before dispatch and its terminal metering afterward."""

    def __init__(
        self,
        store: ModelCallTraceStore,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    async def start(
        self,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
        workflow_run_id: WorkflowRunId,
        node: str,
        attempt: int,
        prompt: PromptDefinition,
        request_hash: Sha256Digest,
        actor_id: ActorId,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> ModelCallTrace:
        trace = ModelCallTrace.start(
            call_id=ModelCallId(self._id_factory()),
            tenant_id=tenant_id,
            incident_id=incident_id,
            workflow_run_id=workflow_run_id,
            node=node,
            attempt=attempt,
            prompt=prompt,
            request_hash=request_hash,
            correlation_id=correlation_id,
            causation_id=causation_id,
            started_at=self._clock(),
        )
        fingerprint = model_call_trace_fingerprint(trace)
        await self._store.start(
            trace,
            self._audit(
                event_type="model.call_started",
                trace=trace,
                actor_id=actor_id,
                request_hash=fingerprint,
                result_hash=fingerprint,
            ),
        )
        return trace

    async def finish(
        self,
        started: ModelCallTrace,
        *,
        status: ModelCallStatus,
        metering: ModelMetering,
        actor_id: ActorId,
        response_hash: Sha256Digest | None = None,
        failure_code: str | None = None,
    ) -> ModelCallTrace:
        completed = started.finish(
            status=status,
            completed_at=self._clock(),
            metering=metering,
            response_hash=response_hash,
            failure_code=failure_code,
        )
        await self._store.finish(
            started,
            completed,
            self._audit(
                event_type="model.call_finished",
                trace=completed,
                actor_id=actor_id,
                request_hash=model_call_trace_fingerprint(started),
                result_hash=model_call_trace_fingerprint(completed),
            ),
        )
        return completed

    def _audit(
        self,
        *,
        event_type: str,
        trace: ModelCallTrace,
        actor_id: ActorId,
        request_hash: Sha256Digest,
        result_hash: Sha256Digest,
    ) -> AuditEvent:
        return AuditEvent(
            id=AuditEventId(self._id_factory()),
            tenant_id=trace.tenant_id,
            type=event_type,
            event_version=1,
            payload_schema_version="model_call/v1",
            actor_id=actor_id,
            correlation_id=trace.correlation_id,
            causation_id=trace.causation_id,
            target=AuditTarget("model.call", OpaqueIdentifier(trace.id.value)),
            occurred_at=self._clock(),
            request_hash=request_hash,
            result_hash=result_hash,
        )
