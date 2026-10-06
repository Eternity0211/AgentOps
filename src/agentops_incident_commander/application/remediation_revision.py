"""Invalidate stale approvals and re-evaluate materially revised remediation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import ValidationError

from agentops_incident_commander.domain import (
    Approval,
    ApprovalId,
    ApprovalInvalidation,
    ApprovalStatus,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    InvalidDomainValueError,
    MaintenanceWindowStatus,
    OpaqueIdentifier,
    Permission,
    PolicyAction,
    PolicyBlastRadius,
    PolicyDecision,
    PolicyEnvironment,
    PolicyEvaluationInput,
    PolicyOutcome,
    Principal,
    TenantId,
    as_utc,
    require_permission,
)
from agentops_incident_commander.workflows import RemediationProposal

from .evidence_gate import evidence_gate_decision_fingerprint
from .policy_engine import PolicyRules, evaluate_remediation_policy
from .remediation_gate import EvidenceBoundRemediationProposal, RemediationEvidenceGate


class RevisionOutcome(StrEnum):
    EVIDENCE_GATE_REJECTED = "EVIDENCE_GATE_REJECTED"
    POLICY_DENIED = "POLICY_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


@dataclass(frozen=True, slots=True)
class PolicyReevaluationContext:
    environment: PolicyEnvironment
    blast_radius: PolicyBlastRadius
    maintenance_window: MaintenanceWindowStatus
    separation_of_duties_required: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.environment, PolicyEnvironment)
            or not isinstance(self.blast_radius, PolicyBlastRadius)
            or not isinstance(self.maintenance_window, MaintenanceWindowStatus)
            or not isinstance(self.separation_of_duties_required, bool)
        ):
            raise InvalidDomainValueError("Policy re-evaluation context is invalid")


@dataclass(frozen=True, slots=True)
class RemediationRevisionResult:
    proposal: RemediationProposal
    invalidation: ApprovalInvalidation
    outcome: RevisionOutcome
    admitted: EvidenceBoundRemediationProposal | None = None
    policy_input: PolicyEvaluationInput | None = None
    policy_decision: PolicyDecision | None = None

    def __post_init__(self) -> None:
        has_policy = self.policy_input is not None and self.policy_decision is not None
        if self.outcome is RevisionOutcome.EVIDENCE_GATE_REJECTED:
            valid = self.admitted is None and not has_policy
        else:
            valid = self.admitted is not None and has_policy
        if not valid:
            raise InvalidDomainValueError("remediation revision result is inconsistent")
        if self.policy_decision is not None:
            expected = (
                PolicyOutcome.DENY
                if self.outcome is RevisionOutcome.POLICY_DENIED
                else PolicyOutcome.APPROVAL_REQUIRED
            )
            if self.policy_decision.outcome is not expected:
                raise InvalidDomainValueError("remediation revision Policy outcome is inconsistent")


class ApprovalInvalidationStore(Protocol):
    async def get_invalidation(
        self,
        approval_id: ApprovalId,
        *,
        tenant_id: TenantId,
    ) -> ApprovalInvalidation | None: ...

    async def record_invalidation(
        self,
        approval: Approval,
        invalidation: ApprovalInvalidation,
        audit_event: AuditEvent,
    ) -> None: ...


class RemediationRevisionService:
    def __init__(
        self,
        invalidations: ApprovalInvalidationStore,
        evidence_gate: RemediationEvidenceGate,
        *,
        clock: Callable[[], datetime],
        audit_id_factory: Callable[[], str],
        policy_decision_id_factory: Callable[[], str],
    ) -> None:
        self._invalidations = invalidations
        self._evidence_gate = evidence_gate
        self._clock = clock
        self._audit_id_factory = audit_id_factory
        self._policy_decision_id_factory = policy_decision_id_factory

    async def revise(
        self,
        approval: Approval,
        prior_proposal: RemediationProposal,
        revised_payload: Mapping[str, object],
        *,
        principal: Principal | None,
        policy_context: PolicyReevaluationContext,
        policy_rules: PolicyRules,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> RemediationRevisionResult:
        actor = require_permission(
            principal,
            Permission.REMEDIATION_REQUEST,
            tenant_id=approval.tenant_id,
        )
        try:
            revised = RemediationProposal.model_validate(revised_payload)
        except ValidationError as error:
            raise InvalidDomainValueError(
                "revised remediation proposal failed schema validation"
            ) from error
        self._validate_revision(approval, prior_proposal, revised)
        existing = await self._invalidations.get_invalidation(
            approval.id,
            tenant_id=approval.tenant_id,
        )
        if existing is not None:
            raise InvalidDomainValueError("Approval is already invalidated")
        invalidated_at = as_utc(self._clock())
        invalidation = ApprovalInvalidation(
            approval_id=approval.id,
            tenant_id=approval.tenant_id,
            incident_id=approval.incident_id,
            approval_fingerprint=approval.fingerprint,
            prior_proposal_fingerprint=prior_proposal.fingerprint,
            replacement_proposal_id=OpaqueIdentifier(revised.proposal_id),
            replacement_proposal_version=revised.proposal_version,
            replacement_proposal_fingerprint=revised.fingerprint,
            replacement_material_fingerprint=revised.material_fingerprint,
            invalidated_by=actor.actor_id,
            invalidated_at=invalidated_at,
        )
        audit = AuditEvent(
            id=AuditEventId(self._audit_id_factory()),
            tenant_id=approval.tenant_id,
            type="approval.invalidated",
            event_version=1,
            payload_schema_version="approval_invalidation/v1",
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            target=AuditTarget("approval.record", OpaqueIdentifier(approval.id.value)),
            occurred_at=invalidated_at,
            request_hash=approval.fingerprint,
            result_hash=invalidation.fingerprint,
        )
        await self._invalidations.record_invalidation(approval, invalidation, audit)
        try:
            admitted = await self._evidence_gate.admit(revised, tenant_id=approval.tenant_id)
        except InvalidDomainValueError:
            return RemediationRevisionResult(
                revised,
                invalidation,
                RevisionOutcome.EVIDENCE_GATE_REJECTED,
            )
        policy_input = PolicyEvaluationInput(
            tenant_id=approval.tenant_id,
            incident_id=approval.incident_id,
            proposal_id=OpaqueIdentifier(revised.proposal_id),
            proposal_version=revised.proposal_version,
            proposal_fingerprint=revised.fingerprint,
            evidence_gate_decision_fingerprint=evidence_gate_decision_fingerprint(
                admitted.evidence_gate_decision
            ),
            requester_actor_id=actor.actor_id,
            requester_roles=actor.roles,
            environment=policy_context.environment,
            action=PolicyAction(revised.action.value),
            service=revised.parameters.service,
            blast_radius=policy_context.blast_radius,
            maintenance_window=policy_context.maintenance_window,
            separation_of_duties_required=policy_context.separation_of_duties_required,
            requested_at=invalidated_at,
        )
        decision = evaluate_remediation_policy(
            policy_input,
            admitted,
            rules=policy_rules,
            decision_id=OpaqueIdentifier(self._policy_decision_id_factory()),
            evaluated_at=invalidated_at,
        )
        if decision.outcome not in {PolicyOutcome.DENY, PolicyOutcome.APPROVAL_REQUIRED}:
            raise InvalidDomainValueError(
                "revised remediation received an unsupported Policy outcome"
            )
        outcome = (
            RevisionOutcome.POLICY_DENIED
            if decision.outcome is PolicyOutcome.DENY
            else RevisionOutcome.APPROVAL_REQUIRED
        )
        return RemediationRevisionResult(
            revised,
            invalidation,
            outcome,
            admitted,
            policy_input,
            decision,
        )

    @staticmethod
    def _validate_revision(
        approval: Approval,
        prior: RemediationProposal,
        revised: RemediationProposal,
    ) -> None:
        if approval.status not in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}:
            raise InvalidDomainValueError("only an active Approval can be invalidated")
        if (
            prior.incident_id != approval.incident_id.value
            or prior.proposal_id != approval.proposal_id.value
            or prior.proposal_version != approval.proposal_version
            or prior.fingerprint != approval.proposal_fingerprint
        ):
            raise InvalidDomainValueError("prior proposal does not match the Approval binding")
        if (
            revised.incident_id != prior.incident_id
            or revised.proposal_id != prior.proposal_id
            or revised.proposal_version <= prior.proposal_version
        ):
            raise InvalidDomainValueError("revised proposal identity or version is invalid")
        if revised.material_fingerprint == prior.material_fingerprint:
            raise InvalidDomainValueError("proposal version changed without a material revision")
