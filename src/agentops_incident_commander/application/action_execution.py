"""Authoritative fail-closed checks immediately before a recovery execution claim."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    ActorId,
    Approval,
    ApprovalId,
    ApprovalInvalidation,
    ApprovalStatus,
    Incident,
    IncidentId,
    IncidentState,
    InvalidDomainValueError,
    Permission,
    PolicyDecision,
    PolicyEnvironment,
    PolicyEvaluationInput,
    PolicyOutcome,
    Principal,
    ResolvedRollbackTarget,
    RollbackServiceRequest,
    RollbackTargetCatalog,
    SemanticVersion,
    TenantId,
    as_utc,
    require_permission,
)
from agentops_incident_commander.workflows import RemediationProposal

from .policy_engine import PolicyRules, evaluate_remediation_policy
from .remediation_gate import EvidenceBoundRemediationProposal, RemediationEvidenceGate


class ExecutionIncidentStore(Protocol):
    async def get_for_tenant(
        self,
        incident_id: IncidentId,
        tenant_id: TenantId,
    ) -> Incident | None: ...


class ExecutionApprovalStore(Protocol):
    async def get(self, approval_id: ApprovalId, *, tenant_id: TenantId) -> Approval | None: ...

    async def get_invalidation(
        self,
        approval_id: ApprovalId,
        *,
        tenant_id: TenantId,
    ) -> ApprovalInvalidation | None: ...


class CurrentServiceVersionStore(Protocol):
    async def get_current_version(
        self,
        *,
        tenant_id: TenantId,
        service: str,
        environment: PolicyEnvironment,
    ) -> SemanticVersion | None: ...


@dataclass(frozen=True, slots=True)
class AuthorizedRollbackExecution:
    """Content-bounded authority assembled only from revalidated server state."""

    request: RollbackServiceRequest
    actor_id: ActorId
    incident: Incident
    approval: Approval
    admitted: EvidenceBoundRemediationProposal
    policy_input: PolicyEvaluationInput
    policy_decision: PolicyDecision
    target: ResolvedRollbackTarget
    authorized_at: datetime


class RollbackExecutionPreflight:
    """Reload every authority source and resolve a server-owned rollback target."""

    def __init__(
        self,
        incidents: ExecutionIncidentStore,
        approvals: ExecutionApprovalStore,
        evidence_gate: RemediationEvidenceGate,
        current_versions: CurrentServiceVersionStore,
        target_catalog: RollbackTargetCatalog,
        policy_rules: PolicyRules,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._incidents = incidents
        self._approvals = approvals
        self._evidence_gate = evidence_gate
        self._current_versions = current_versions
        self._target_catalog = target_catalog
        self._policy_rules = policy_rules
        self._clock = clock

    async def authorize(
        self,
        request: RollbackServiceRequest,
        proposal: RemediationProposal,
        policy_input: PolicyEvaluationInput,
        policy_decision: PolicyDecision,
        *,
        principal: Principal | None,
    ) -> AuthorizedRollbackExecution:
        if (
            not isinstance(request, RollbackServiceRequest)
            or not isinstance(proposal, RemediationProposal)
            or not isinstance(policy_input, PolicyEvaluationInput)
            or not isinstance(policy_decision, PolicyDecision)
        ):
            raise InvalidDomainValueError("rollback execution preflight inputs are invalid")
        actor = require_permission(
            principal,
            Permission.APPROVED_ACTION_EXECUTE,
            tenant_id=policy_input.tenant_id,
        )
        incident = await self._incidents.get_for_tenant(
            request.incident_id,
            actor.tenant_id,
        )
        if incident is None:
            raise InvalidDomainValueError("rollback Incident was not found in the tenant scope")
        if incident.state is not IncidentState.READY_TO_EXECUTE:
            raise InvalidDomainValueError("rollback Incident is not ready to execute")
        if (
            proposal.incident_id != incident.id.value
            or policy_input.incident_id != incident.id
            or policy_input.tenant_id != incident.tenant_id
        ):
            raise InvalidDomainValueError("rollback Incident authority binding is invalid")

        approval = await self._approvals.get(
            request.approval_id,
            tenant_id=incident.tenant_id,
        )
        if approval is None:
            raise InvalidDomainValueError("rollback Approval was not found in the tenant scope")
        authorized_at = as_utc(self._clock())
        if approval.status is not ApprovalStatus.APPROVED:
            raise InvalidDomainValueError("rollback Approval is not approved")
        if authorized_at >= approval.expires_at:
            raise InvalidDomainValueError("rollback Approval has expired")
        invalidation = await self._approvals.get_invalidation(
            approval.id,
            tenant_id=approval.tenant_id,
        )
        if invalidation is not None:
            raise InvalidDomainValueError("rollback Approval was invalidated")
        if (
            approval.incident_id != incident.id
            or approval.proposal_id.value != proposal.proposal_id
            or approval.proposal_version != proposal.proposal_version
            or approval.proposal_fingerprint != proposal.fingerprint
        ):
            raise InvalidDomainValueError("rollback proposal does not match the Approval")
        if (
            policy_input.proposal_id != approval.proposal_id
            or policy_input.proposal_version != approval.proposal_version
            or policy_input.proposal_fingerprint != approval.proposal_fingerprint
            or policy_input.requester_actor_id != approval.proposer_actor_id
            or policy_input.fingerprint != approval.policy_input_fingerprint
        ):
            raise InvalidDomainValueError("rollback Policy input does not match the Approval")
        if (
            policy_decision.id != approval.policy_decision_id
            or policy_decision.fingerprint != approval.policy_decision_fingerprint
            or policy_decision.input_fingerprint != policy_input.fingerprint
            or policy_decision.proposal_fingerprint != proposal.fingerprint
            or policy_decision.risk_level is not approval.risk_level
            or policy_decision.outcome is not PolicyOutcome.APPROVAL_REQUIRED
            or policy_decision.policy_version != self._policy_rules.version
        ):
            raise InvalidDomainValueError("rollback Policy decision does not match the Approval")

        admitted = await self._evidence_gate.admit(proposal, tenant_id=incident.tenant_id)
        refreshed_decision = evaluate_remediation_policy(
            policy_input,
            admitted,
            rules=self._policy_rules,
            decision_id=policy_decision.id,
            evaluated_at=policy_decision.evaluated_at,
        )
        if refreshed_decision != policy_decision:
            raise InvalidDomainValueError("rollback Policy decision is no longer reproducible")
        current_version = await self._current_versions.get_current_version(
            tenant_id=incident.tenant_id,
            service=proposal.parameters.service,
            environment=policy_input.environment,
        )
        if current_version is None:
            raise InvalidDomainValueError("rollback current service version is unavailable")
        target = self._target_catalog.resolve(
            tenant_id=incident.tenant_id,
            service=proposal.parameters.service,
            environment=policy_input.environment,
            current_version=current_version,
        )
        return AuthorizedRollbackExecution(
            request=request,
            actor_id=actor.actor_id,
            incident=incident,
            approval=approval,
            admitted=admitted,
            policy_input=policy_input,
            policy_decision=policy_decision,
            target=target,
            authorized_at=authorized_at,
        )
