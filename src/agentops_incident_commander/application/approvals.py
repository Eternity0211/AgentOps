"""RBAC-protected Approval lifecycle with proposal-bound audit events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Approval,
    ApprovalId,
    ApprovalStatus,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    AuthorizationError,
    CausationId,
    CorrelationId,
    EventReason,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Permission,
    PolicyDecision,
    PolicyEvaluationInput,
    PolicyOutcome,
    Principal,
    RiskLevel,
    Role,
    TenantId,
    as_utc,
    require_independent_approver,
    require_permission,
)


@dataclass(frozen=True, slots=True)
class ApprovalLifecycleChange:
    action: str
    before: Approval | None
    after: Approval


class ApprovalLifecycleStore(Protocol):
    async def get(self, approval_id: ApprovalId, *, tenant_id: TenantId) -> Approval | None: ...

    async def apply(
        self,
        change: ApprovalLifecycleChange,
        audit_event: AuditEvent,
    ) -> None: ...


class ApprovalLifecycleManager:
    """Create and resolve finite Approval aggregates; storage owns atomicity."""

    def __init__(
        self,
        store: ApprovalLifecycleStore,
        *,
        clock: Callable[[], datetime],
        approval_id_factory: Callable[[], str],
        audit_id_factory: Callable[[], str],
        expiry_actor_id: ActorId,
    ) -> None:
        self._store = store
        self._clock = clock
        self._approval_id_factory = approval_id_factory
        self._audit_id_factory = audit_id_factory
        self._expiry_actor_id = expiry_actor_id

    async def request(
        self,
        policy_input: PolicyEvaluationInput,
        policy_decision: PolicyDecision,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> Approval:
        requester = require_permission(
            principal,
            Permission.REMEDIATION_REQUEST,
            tenant_id=policy_input.tenant_id,
        )
        if (
            requester.actor_id != policy_input.requester_actor_id
            or requester.roles != policy_input.requester_roles
        ):
            raise AuthorizationError("Approval requester does not match Policy input")
        if (
            policy_decision.outcome is not PolicyOutcome.APPROVAL_REQUIRED
            or policy_decision.approval_ttl is None
            or policy_decision.input_fingerprint != policy_input.fingerprint
            or policy_decision.proposal_fingerprint != policy_input.proposal_fingerprint
        ):
            raise InvalidDomainValueError(
                "Approval requires an exact approval-required Policy decision"
            )
        requested_at = as_utc(self._clock())
        if policy_decision.evaluated_at > requested_at:
            raise InvalidDomainValueError("Policy decision cannot be evaluated in the future")
        expires_at = policy_decision.evaluated_at + policy_decision.approval_ttl
        if requested_at >= expires_at:
            raise InvalidDomainValueError("Policy decision approval lifetime has expired")
        independent = policy_input.separation_of_duties_required or policy_decision.risk_level in {
            RiskLevel.MEDIUM,
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }
        approval = Approval(
            id=ApprovalId(self._approval_id_factory()),
            tenant_id=requester.tenant_id,
            incident_id=policy_input.incident_id,
            proposal_id=policy_input.proposal_id,
            proposal_version=policy_input.proposal_version,
            proposal_fingerprint=policy_input.proposal_fingerprint,
            policy_decision_id=policy_decision.id,
            policy_decision_fingerprint=policy_decision.fingerprint,
            policy_input_fingerprint=policy_input.fingerprint,
            proposer_actor_id=requester.actor_id,
            risk_level=policy_decision.risk_level,
            independent_approver_required=independent,
            status=ApprovalStatus.PENDING,
            version=AggregateVersion.initial(),
            requested_at=requested_at,
            expires_at=expires_at,
        )
        await self._apply(
            ApprovalLifecycleChange("requested", None, approval),
            actor_id=requester.actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return approval

    async def approve(
        self,
        approval_id: ApprovalId,
        *,
        principal: Principal | None,
        reason: EventReason,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> Approval:
        return await self._human_decision(
            approval_id,
            principal=principal,
            status=ApprovalStatus.APPROVED,
            reason=reason,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

    async def reject(
        self,
        approval_id: ApprovalId,
        *,
        principal: Principal | None,
        reason: EventReason,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> Approval:
        return await self._human_decision(
            approval_id,
            principal=principal,
            status=ApprovalStatus.REJECTED,
            reason=reason,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

    async def expire(
        self,
        approval_id: ApprovalId,
        *,
        tenant_id: TenantId,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> Approval:
        current = await self._required(approval_id, tenant_id=tenant_id)
        at = as_utc(self._clock())
        if at < current.expires_at:
            raise InvalidDomainValueError("Approval has not reached its expiry time")
        return await self._expire(
            current,
            at=at,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

    async def _human_decision(
        self,
        approval_id: ApprovalId,
        *,
        principal: Principal | None,
        status: ApprovalStatus,
        reason: EventReason,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> Approval:
        tenant_id = TenantId("unauthenticated") if principal is None else principal.tenant_id
        approver = require_permission(
            principal,
            Permission.APPROVAL_DECIDE,
            tenant_id=tenant_id,
        )
        current = await self._required(approval_id, tenant_id=approver.tenant_id)
        proposer = Principal(
            current.proposer_actor_id,
            current.tenant_id,
            frozenset({Role.OPERATOR}),
        )
        if current.independent_approver_required:
            require_independent_approver(proposer, approver)
        at = as_utc(self._clock())
        if at >= current.expires_at:
            return await self._expire(
                current,
                at=at,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        decided = current.decide(status, actor_id=approver.actor_id, reason=reason, at=at)
        await self._apply(
            ApprovalLifecycleChange(status.value.lower(), current, decided),
            actor_id=approver.actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return decided

    async def _expire(
        self,
        current: Approval,
        *,
        at: datetime,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> Approval:
        expired = current.decide(
            ApprovalStatus.EXPIRED,
            actor_id=self._expiry_actor_id,
            reason=EventReason("Approval lifetime expired."),
            at=at,
        )
        await self._apply(
            ApprovalLifecycleChange("expired", current, expired),
            actor_id=self._expiry_actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return expired

    async def _required(self, approval_id: ApprovalId, *, tenant_id: TenantId) -> Approval:
        if not isinstance(approval_id, ApprovalId) or not isinstance(tenant_id, TenantId):
            raise InvalidDomainValueError("Approval lookup scope is invalid")
        value = await self._store.get(approval_id, tenant_id=tenant_id)
        if value is None:
            raise InvalidDomainValueError("Approval was not found in the tenant scope")
        return value

    async def _apply(
        self,
        change: ApprovalLifecycleChange,
        *,
        actor_id: ActorId,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> None:
        audit = AuditEvent(
            id=AuditEventId(self._audit_id_factory()),
            tenant_id=change.after.tenant_id,
            type=f"approval.{change.action}",
            event_version=1,
            payload_schema_version="approval/v1",
            actor_id=actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            target=AuditTarget("approval.record", OpaqueIdentifier(change.after.id.value)),
            occurred_at=(
                change.after.requested_at
                if change.before is None
                else change.after.decided_at or change.after.requested_at
            ),
            request_hash=(
                change.after.policy_decision_fingerprint
                if change.before is None
                else change.before.fingerprint
            ),
            result_hash=change.after.fingerprint,
        )
        await self._store.apply(change, audit)
