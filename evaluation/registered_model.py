"""Connect typed model calls to exact active Prompt registrations and durable trace ports."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Protocol
from uuid import uuid4

from agentops_incident_commander.application import model_call_trace_fingerprint
from agentops_incident_commander.application.diagnosis_prompts import (
    ApprovedDiagnosisPromptResolver,
    DiagnosisPromptStore,
)
from agentops_incident_commander.application.model_tracing import ModelCallTraceManager
from agentops_incident_commander.domain import (
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    IncidentId,
    ModelCallStatus,
    ModelMetering,
    ModelMeteringUnavailableReason,
    OpaqueIdentifier,
    Permission,
    Principal,
    PromptLifecycleStatus,
    PromptPurpose,
    PromptVersionReference,
    Sha256Digest,
    WorkflowRunId,
    require_permission,
)
from agentops_incident_commander.workflows import (
    DiagnosisReport,
    DiagnosisReportRecord,
    GraphPromptReference,
    diagnosis_report_fingerprint,
)
from evaluation.structured_model import (
    ModelPurpose,
    StructuredEvaluationModel,
    StructuredModelFailure,
    StructuredResult,
    fingerprint,
)


class DiagnosisReportWriter(Protocol):
    async def record(
        self, record: DiagnosisReportRecord, audit_event: AuditEvent
    ) -> DiagnosisReportRecord: ...


class RegisteredModelInvoker:
    """No provider dispatch before registration, RBAC and durable model-call start succeed."""

    def __init__(
        self,
        model: StructuredEvaluationModel,
        prompts: DiagnosisPromptStore,
        traces: ModelCallTraceManager,
        references: Mapping[ModelPurpose, PromptVersionReference],
        principal: Principal,
        incident: IncidentId,
        workflow: WorkflowRunId,
        correlation: CorrelationId,
        causation: CausationId,
        usage_observer: Callable[[dict[str, Any]], None],
        report_writer: DiagnosisReportWriter | None = None,
    ) -> None:
        self.model, self.prompts, self.traces = model, prompts, traces
        self.references = dict(references)
        self.principal, self.incident, self.workflow = principal, incident, workflow
        self.correlation, self.causation, self.observe = correlation, causation, usage_observer
        self.report_writer = report_writer

    async def workflow_reference(self) -> GraphPromptReference:
        require_permission(
            self.principal, Permission.INVESTIGATION_START, tenant_id=self.principal.tenant_id
        )
        if not {ModelPurpose.PLAN, ModelPurpose.DIAGNOSE} <= set(self.references):
            raise StructuredModelFailure("WORKFLOW_PROMPT_REFERENCES_REQUIRED")
        reference = self.references[ModelPurpose.PLAN]
        definition = await self.prompts.resolve(
            self.principal.tenant_id, reference.prompt_id, reference.version
        )
        active = await self.prompts.active(self.principal.tenant_id, reference.prompt_id)
        if (
            definition is None
            or definition != active
            or definition.status is not PromptLifecycleStatus.ACTIVE
        ):
            raise StructuredModelFailure("ACTIVE_PROMPT_REQUIRED")
        return GraphPromptReference(
            prompt_id=reference.prompt_id.value,
            version=reference.version.value,
            content_fingerprint=definition.content_fingerprint.value,
        )

    def workflow_authorizer(self) -> ApprovedDiagnosisPromptResolver:
        return ApprovedDiagnosisPromptResolver(self.prompts)

    async def invoke(
        self,
        purpose: ModelPurpose,
        context: dict[str, Any],
        *,
        attempt: int = 1,
        gate: EvidenceGateDecision | None = None,
    ) -> StructuredResult:
        require_permission(
            self.principal, Permission.INVESTIGATION_START, tenant_id=self.principal.tenant_id
        )
        if purpose is ModelPurpose.REMEDIATE and (
            gate is None
            or gate.outcome is not EvidenceGateOutcome.PASS
            or gate.incident_id != self.incident
        ):
            raise StructuredModelFailure("GATE_PASS_REQUIRED")
        context = json.loads(json.dumps(context, allow_nan=False))
        if context.get("incident_id") != self.incident.value or purpose not in self.references:
            raise StructuredModelFailure("MODEL_CONTEXT_BINDING_MISMATCH")
        reference = self.references[purpose]
        definition = await self.prompts.resolve(
            self.principal.tenant_id, reference.prompt_id, reference.version
        )
        active = await self.prompts.active(self.principal.tenant_id, reference.prompt_id)
        payload = self.model.request_payload(purpose, context)
        expected_purpose = (
            PromptPurpose.REMEDIATION
            if purpose is ModelPurpose.REMEDIATE
            else PromptPurpose.DIAGNOSIS
        )
        if (
            definition is None
            or definition != active
            or definition.status is not PromptLifecycleStatus.ACTIVE
        ):
            raise StructuredModelFailure("ACTIVE_PROMPT_REQUIRED")
        if (
            definition.purpose is not expected_purpose
            or definition.content != payload["messages"][0]["content"]
        ):
            raise StructuredModelFailure("PROMPT_CONTENT_MISMATCH")
        parameters = definition.model_parameters
        if (
            parameters.provider,
            parameters.model,
            parameters.temperature_basis_points,
            parameters.top_p_basis_points,
            parameters.max_output_tokens,
            parameters.seed,
        ) != ("deepseek", "deepseek-flash", 0, 10000, 2048, None):
            raise StructuredModelFailure("PROMPT_SETTINGS_MISMATCH")
        started = await self.traces.start(
            tenant_id=self.principal.tenant_id,
            incident_id=self.incident,
            workflow_run_id=self.workflow,
            node={
                ModelPurpose.PLAN: "diagnosis.plan",
                ModelPurpose.DIAGNOSE: "diagnosis.hypothesis",
                ModelPurpose.REMEDIATE: "remediation.proposal",
            }[purpose],
            attempt=attempt,
            prompt=definition,
            request_hash=Sha256Digest(fingerprint(payload)),
            actor_id=self.principal.actor_id,
            correlation_id=self.correlation,
            causation_id=self.causation,
        )
        unavailable = ModelMetering(
            None, None, ModelMeteringUnavailableReason.PROVIDER_DID_NOT_RETURN
        )
        try:
            self.observe(
                {
                    "event": "model.trace_bound",
                    "call_id": started.id.value,
                    "request_hash": started.request_hash.value,
                }
            )
            result = await asyncio.to_thread(self.model.invoke, purpose, context, gate=gate)
            if result.request_hash != started.request_hash.value:
                raise StructuredModelFailure("REQUEST_FINGERPRINT_MISMATCH")
            self.observe(
                {
                    "event": "model.usage_observed",
                    "call_id": started.id.value,
                    "request_hash": result.request_hash,
                    "response_hash": result.response_hash,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cached_input_tokens": result.cached_input_tokens,
                    "cost_upper_bound_nanousd": result.cost_upper_bound_nanousd,
                    "actual_cost": None,
                    "actual_cost_reason": "PROVIDER_DID_NOT_RETURN",
                }
            )
        except Exception as error:
            timeout = isinstance(error, StructuredModelFailure) and str(error) == "TIMEOUT"
            await self.traces.finish(
                started,
                status=ModelCallStatus.TIMED_OUT if timeout else ModelCallStatus.FAILED,
                metering=unavailable,
                actor_id=self.principal.actor_id,
                failure_code="TIMEOUT" if timeout else "MODEL_CALL_FAILED",
            )
            raise
        output_hash = (
            diagnosis_report_fingerprint(result.output)
            if isinstance(result.output, DiagnosisReport)
            else Sha256Digest(fingerprint(result.output.model_dump(mode="json")))
        )
        completed = await self.traces.finish(
            started,
            status=ModelCallStatus.SUCCEEDED,
            metering=unavailable,
            actor_id=self.principal.actor_id,
            response_hash=output_hash,
        )
        if isinstance(result.output, DiagnosisReport) and self.report_writer is not None:
            assert completed.completed_at is not None
            record = DiagnosisReportRecord(
                self.principal.tenant_id,
                self.workflow,
                completed.id,
                result.output,
                output_hash,
                completed.completed_at,
            )
            await self.report_writer.record(
                record,
                AuditEvent(
                    id=AuditEventId(f"report-audit-{uuid4().hex}"),
                    tenant_id=self.principal.tenant_id,
                    type="diagnosis.report_recorded",
                    event_version=1,
                    payload_schema_version="diagnosis_report/v1",
                    actor_id=self.principal.actor_id,
                    correlation_id=completed.correlation_id,
                    causation_id=completed.causation_id,
                    target=AuditTarget("diagnosis.report", OpaqueIdentifier(output_hash.value)),
                    occurred_at=completed.completed_at,
                    request_hash=model_call_trace_fingerprint(completed),
                    result_hash=output_hash,
                ),
            )
        return replace(result, call_id=started.id.value)
