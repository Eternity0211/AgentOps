"""Read-only scripted review; never a human approver or recovery authority."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Protocol

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.application import (
    evaluate_evidence_gate,
    resolve_gate_evidence_references,
)
from agentops_incident_commander.application.approvals import ApprovalReviewSnapshot
from agentops_incident_commander.domain import (
    Approval,
    ApprovalId,
    ApprovalStatus,
    ArtifactStorage,
    EvidenceGateRules,
    IncidentId,
    ModelCallId,
    ModelCallStatus,
    ModelCallTrace,
    Permission,
    Principal,
    TenantId,
    require_permission,
)
from evaluation.autonomous_diagnosis import WorkflowEvidenceStore
from evaluation.registered_model import DiagnosisReportReader


class TraceReader(Protocol):
    async def get(self, tenant_id: TenantId, call_id: ModelCallId) -> ModelCallTrace | None: ...


async def review_diagnosis(
    reports: DiagnosisReportReader,
    traces: TraceReader,
    evidence: WorkflowEvidenceStore,
    artifacts: ArtifactStorage,
    *,
    principal: Principal,
    incident: IncidentId,
    workflow_id: str,
) -> dict[str, Any]:
    started = time.monotonic_ns()
    require_permission(principal, Permission.EVIDENCE_READ, tenant_id=principal.tenant_id)
    record = await reports.latest(tenant_id=principal.tenant_id, incident_id=incident)
    tasks: dict[str, str] = {}
    gate_outcomes: dict[str, str] = {}
    citations = unresolved = 0
    if record is None or record.workflow_run_id.value != workflow_id:
        tasks["report_binding"] = "FAIL"
    else:
        trace = await traces.get(principal.tenant_id, record.model_call_id)
        bound = (
            trace is not None
            and trace.tenant_id == principal.tenant_id
            and trace.incident_id == incident
            and trace.workflow_run_id.value == workflow_id
            and trace.status is ModelCallStatus.SUCCEEDED
            and trace.response_hash == record.report_fingerprint
        )
        tasks["report_binding"] = "PASS" if bound else "FAIL"
        if bound:
            for candidate in record.report.candidates:
                claim = record.report.evidence_gate_claim(candidate.candidate_id)
                resolution = await resolve_gate_evidence_references(
                    claim,
                    tenant_id=principal.tenant_id,
                    principal=principal,
                    reader=evidence,
                    artifact_storage=artifacts,
                    at=datetime.now(UTC),
                )
                declared = set(
                    (*candidate.supporting_evidence_ids, *candidate.counter_evidence_ids)
                )
                citations += len(declared)
                unresolved += len(declared) - len(resolution.verified_evidence)
                decision = evaluate_evidence_gate(
                    claim, resolution, rules=EvidenceGateRules(), at=datetime.now(UTC)
                )
                tasks[f"gate:{candidate.candidate_id}"] = "PASS"
                gate_outcomes[candidate.candidate_id] = decision.outcome.value
            if citations:
                tasks["citation_resolution"] = "PASS" if unresolved == 0 else "FAIL"
    return {
        "actor_kind": "DETERMINISTIC_EVALUATOR_NOT_HUMAN",
        "tasks": tasks,
        "gate_outcomes": gate_outcomes,
        "task_successes": sum(value == "PASS" for value in tasks.values()),
        "required_tasks": len(tasks),
        "declared_citations": citations,
        "unresolved_citations": unresolved,
        "backend_review_ms": (time.monotonic_ns() - started) // 1_000_000,
        "approval_decided": False,
        "recovery_executed": False,
        "human_time_saved": None,
    }


class ApprovalReviewReader(Protocol):
    async def get(self, approval_id: ApprovalId, *, tenant_id: TenantId) -> Approval | None: ...
    async def get_review_snapshot(
        self, approval_id: ApprovalId, *, tenant_id: TenantId
    ) -> ApprovalReviewSnapshot | None: ...


async def review_pending_approval(
    reader: ApprovalReviewReader,
    approval_id: ApprovalId,
    *,
    principal: Principal,
    incident: IncidentId,
    at: datetime,
) -> dict[str, Any]:
    require_permission(principal, Permission.EVIDENCE_READ, tenant_id=principal.tenant_id)
    approval = await reader.get(approval_id, tenant_id=principal.tenant_id)
    snapshot = await reader.get_review_snapshot(approval_id, tenant_id=principal.tenant_id)
    valid = (
        approval is not None
        and snapshot is not None
        and approval.incident_id == incident
        and approval.tenant_id == principal.tenant_id
        and approval.status is ApprovalStatus.PENDING
        and at < approval.expires_at
        and approval.proposal_fingerprint == snapshot.proposal.fingerprint
        and approval.policy_decision_fingerprint == snapshot.policy_decision.fingerprint
        and approval.policy_input_fingerprint == snapshot.policy_input.fingerprint
    )
    return {
        "actor_kind": "DETERMINISTIC_EVALUATOR_NOT_HUMAN",
        "tasks": {"pending_approval_review": "PASS" if valid else "FAIL"},
        "task_successes": int(valid),
        "required_tasks": 1,
        "approval_decided": False,
        "recovery_executed": False,
        "human_time_saved": None,
    }
