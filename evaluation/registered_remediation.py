"""Gate-bound registered model proposal; deterministic admission remains authoritative."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.application.approvals import ApprovalLifecycleManager
from agentops_incident_commander.application.evidence_gate import evidence_gate_decision_fingerprint
from agentops_incident_commander.application.policy_engine import (
    PolicyRules,
    evaluate_remediation_policy,
)
from agentops_incident_commander.application.remediation_gate import (
    EvidenceBoundRemediationProposal,
    RemediationEvidenceGate,
    RemediationEvidenceGateStore,
)
from agentops_incident_commander.domain import (
    Approval,
    CausationId,
    CorrelationId,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    OpaqueIdentifier,
    Permission,
    PolicyDecision,
    PolicyEvaluationInput,
    PolicyOutcome,
    Principal,
    require_permission,
)
from agentops_incident_commander.workflows import RemediationProposal
from evaluation.registered_model import RegisteredModelInvoker
from evaluation.structured_model import ModelPurpose, StructuredModelFailure


async def propose_registered_remediation(
    invoker: RegisteredModelInvoker,
    gate_store: RemediationEvidenceGateStore,
    decision: EvidenceGateDecision,
    context: dict[str, Any],
) -> EvidenceBoundRemediationProposal:
    if decision.outcome is not EvidenceGateOutcome.PASS or decision.incident_id != invoker.incident:
        raise StructuredModelFailure("STORED_GATE_PASS_REQUIRED")
    stored = await gate_store.get(
        tenant_id=invoker.principal.tenant_id,
        incident_id=invoker.incident,
        candidate_id=decision.candidate_id,
        input_fingerprint=decision.input_fingerprint,
    )
    if stored != decision:
        raise StructuredModelFailure("STORED_GATE_BINDING_MISMATCH")
    bound_context = {
        **context,
        "incident_id": invoker.incident.value,
        "candidate_id": decision.candidate_id,
        "evidence_gate_input_fingerprint": decision.input_fingerprint.value,
        "evidence_gate_decision_fingerprint": evidence_gate_decision_fingerprint(decision).value,
    }
    result = await invoker.invoke(ModelPurpose.REMEDIATE, bound_context, gate=decision)
    if not isinstance(result.output, RemediationProposal):
        raise StructuredModelFailure("REMEDIATION_SCHEMA_REQUIRED")
    return await RemediationEvidenceGate(gate_store).admit(
        result.output,
        tenant_id=invoker.principal.tenant_id,
    )


async def request_remediation_review(
    admitted: EvidenceBoundRemediationProposal,
    policy_input: PolicyEvaluationInput,
    *,
    rules: PolicyRules,
    decision_id: OpaqueIdentifier,
    evaluated_at: datetime,
    approvals: ApprovalLifecycleManager,
    principal: Principal,
    correlation_id: CorrelationId,
    causation_id: CausationId,
) -> tuple[PolicyDecision, Approval | None]:
    """Evaluate server-owned Policy inputs and stop at a persisted human review request."""
    require_permission(principal, Permission.REMEDIATION_REQUEST, tenant_id=admitted.tenant_id)
    if (
        policy_input.tenant_id != principal.tenant_id
        or policy_input.requester_actor_id != principal.actor_id
        or policy_input.requester_roles != principal.roles
    ):
        raise StructuredModelFailure("POLICY_REQUESTER_BINDING_MISMATCH")
    decision = evaluate_remediation_policy(
        policy_input,
        admitted,
        rules=rules,
        decision_id=decision_id,
        evaluated_at=evaluated_at,
    )
    if decision.outcome is not PolicyOutcome.APPROVAL_REQUIRED:
        return decision, None
    approval = await approvals.request(
        policy_input,
        decision,
        proposal=admitted.proposal,
        principal=principal,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    return decision, approval
