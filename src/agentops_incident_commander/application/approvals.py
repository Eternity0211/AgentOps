"""RBAC-protected Approval lifecycle with proposal-bound audit events."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, cast

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
    IncidentId,
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
    PolicyReason,
    PolicyReasonCode,
    Principal,
    RiskLevel,
    Role,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    as_utc,
    require_independent_approver,
    require_permission,
)
from agentops_incident_commander.workflows import RemediationProposal

from .control_plane_observability import (
    NOOP_CONTROL_PLANE_OBSERVER,
    ControlPlaneComponent,
    ControlPlaneObservation,
    ControlPlaneObserver,
    ControlPlaneOperation,
    ControlPlaneOutcome,
    safely_record,
    utc_observation_time,
)

APPROVAL_REVIEW_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class ApprovalReviewSnapshot:
    """Immutable, hash-bound proposal and Policy context shown to a human reviewer."""

    proposal: RemediationProposal
    policy_input: PolicyEvaluationInput
    policy_decision: PolicyDecision
    schema_version: str = APPROVAL_REVIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, RemediationProposal):
            raise InvalidDomainValueError("Approval review proposal is invalid")
        if not isinstance(self.policy_input, PolicyEvaluationInput) or not isinstance(
            self.policy_decision, PolicyDecision
        ):
            raise InvalidDomainValueError("Approval review Policy context is invalid")
        if self.schema_version != APPROVAL_REVIEW_SCHEMA_VERSION:
            raise InvalidDomainValueError("Approval review schema version is unsupported")
        value = self.policy_input
        decision = self.policy_decision
        if (
            self.proposal.incident_id != value.incident_id.value
            or self.proposal.proposal_id != value.proposal_id.value
            or self.proposal.proposal_version != value.proposal_version
            or self.proposal.fingerprint != value.proposal_fingerprint
            or self.proposal.action.value != value.action.value
            or self.proposal.parameters.service != value.service
            or self.proposal.evidence_gate_decision_fingerprint
            != value.evidence_gate_decision_fingerprint.value
            or decision.input_fingerprint != value.fingerprint
            or decision.proposal_fingerprint != self.proposal.fingerprint
            or decision.outcome is not PolicyOutcome.APPROVAL_REQUIRED
            or decision.approval_ttl is None
        ):
            raise InvalidDomainValueError("Approval review bindings are inconsistent")

    @property
    def document(self) -> dict[str, object]:
        value = self.policy_input
        decision = self.policy_decision
        approval_ttl = decision.approval_ttl
        if approval_ttl is None:  # pragma: no cover - constructor invariant
            raise InvalidDomainValueError("Approval review decision has no lifetime")
        return {
            "policy_decision": {
                "approval_ttl_seconds": int(approval_ttl.total_seconds()),
                "evaluated_at": decision.evaluated_at.isoformat(),
                "id": decision.id.value,
                "input_fingerprint": decision.input_fingerprint.value,
                "outcome": decision.outcome.value,
                "policy_version": decision.policy_version.value,
                "proposal_fingerprint": decision.proposal_fingerprint.value,
                "reasons": [
                    {"code": reason.code.value, "detail": reason.detail}
                    for reason in decision.reasons
                ],
                "risk_level": decision.risk_level.value,
                "schema_version": decision.schema_version,
            },
            "policy_input": {
                "action": value.action.value,
                "blast_radius": value.blast_radius.value,
                "environment": value.environment.value,
                "evidence_gate_decision_fingerprint": (
                    value.evidence_gate_decision_fingerprint.value
                ),
                "incident_id": value.incident_id.value,
                "maintenance_window": value.maintenance_window.value,
                "proposal_fingerprint": value.proposal_fingerprint.value,
                "proposal_id": value.proposal_id.value,
                "proposal_version": value.proposal_version,
                "requested_at": value.requested_at.isoformat(),
                "requester_actor_id": value.requester_actor_id.value,
                "requester_roles": sorted(role.value for role in value.requester_roles),
                "schema_version": value.schema_version,
                "separation_of_duties_required": value.separation_of_duties_required,
                "service": value.service,
                "tenant_id": value.tenant_id.value,
            },
            "proposal": self.proposal.model_dump(mode="json"),
            "schema_version": self.schema_version,
        }

    @property
    def fingerprint(self) -> Sha256Digest:
        canonical = json.dumps(self.document, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(canonical).hexdigest())


def approval_review_snapshot_from_document(
    document: Mapping[str, object],
) -> ApprovalReviewSnapshot:
    """Rebuild and validate persisted review content before it reaches the API."""

    try:
        proposal_raw = document["proposal"]
        input_raw = document["policy_input"]
        decision_raw = document["policy_decision"]
        if (
            not isinstance(proposal_raw, Mapping)
            or not isinstance(input_raw, Mapping)
            or not isinstance(decision_raw, Mapping)
        ):
            raise TypeError
        proposal = RemediationProposal.model_validate_json(json.dumps(proposal_raw))
        input_data = cast(Mapping[str, object], input_raw)
        decision_data = cast(Mapping[str, object], decision_raw)
        requester_roles = input_data["requester_roles"]
        reasons = decision_data["reasons"]
        separation_required = input_data["separation_of_duties_required"]
        proposal_version = input_data["proposal_version"]
        approval_ttl_seconds = decision_data["approval_ttl_seconds"]
        if (
            not isinstance(requester_roles, list)
            or not isinstance(reasons, list)
            or not isinstance(separation_required, bool)
            or not isinstance(proposal_version, int)
            or isinstance(proposal_version, bool)
            or not isinstance(approval_ttl_seconds, int)
            or isinstance(approval_ttl_seconds, bool)
        ):
            raise TypeError
        policy_input = PolicyEvaluationInput(
            tenant_id=TenantId(str(input_data["tenant_id"])),
            incident_id=IncidentId(str(input_data["incident_id"])),
            proposal_id=OpaqueIdentifier(str(input_data["proposal_id"])),
            proposal_version=proposal_version,
            proposal_fingerprint=Sha256Digest(str(input_data["proposal_fingerprint"])),
            evidence_gate_decision_fingerprint=Sha256Digest(
                str(input_data["evidence_gate_decision_fingerprint"])
            ),
            requester_actor_id=ActorId(str(input_data["requester_actor_id"])),
            requester_roles=frozenset(Role(str(item)) for item in requester_roles),
            environment=PolicyEnvironment(str(input_data["environment"])),
            action=PolicyAction(str(input_data["action"])),
            service=str(input_data["service"]),
            blast_radius=PolicyBlastRadius(str(input_data["blast_radius"])),
            maintenance_window=MaintenanceWindowStatus(str(input_data["maintenance_window"])),
            separation_of_duties_required=separation_required,
            requested_at=datetime.fromisoformat(str(input_data["requested_at"])),
            schema_version=str(input_data["schema_version"]),
        )
        decision = PolicyDecision(
            id=OpaqueIdentifier(str(decision_data["id"])),
            policy_version=SemanticVersion(str(decision_data["policy_version"])),
            input_fingerprint=Sha256Digest(str(decision_data["input_fingerprint"])),
            proposal_fingerprint=Sha256Digest(str(decision_data["proposal_fingerprint"])),
            outcome=PolicyOutcome(str(decision_data["outcome"])),
            risk_level=RiskLevel(str(decision_data["risk_level"])),
            reasons=tuple(
                PolicyReason(PolicyReasonCode(str(reason["code"])), str(reason["detail"]))
                for reason in cast(list[Mapping[str, object]], reasons)
            ),
            evaluated_at=datetime.fromisoformat(str(decision_data["evaluated_at"])),
            approval_ttl=timedelta(seconds=approval_ttl_seconds),
            schema_version=str(decision_data["schema_version"]),
        )
        snapshot = ApprovalReviewSnapshot(
            proposal,
            policy_input,
            decision,
            schema_version=str(document["schema_version"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidDomainValueError("Approval review snapshot is invalid") from error
    return snapshot


@dataclass(frozen=True, slots=True)
class ApprovalLifecycleChange:
    action: str
    before: Approval | None
    after: Approval
    review_snapshot: ApprovalReviewSnapshot | None = None


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
        observer: ControlPlaneObserver = NOOP_CONTROL_PLANE_OBSERVER,
    ) -> None:
        self._store = store
        self._clock = clock
        self._approval_id_factory = approval_id_factory
        self._audit_id_factory = audit_id_factory
        self._expiry_actor_id = expiry_actor_id
        self._observer = observer

    async def request(
        self,
        policy_input: PolicyEvaluationInput,
        policy_decision: PolicyDecision,
        *,
        proposal: RemediationProposal,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> Approval:
        started_ns = time.monotonic_ns()
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
        review_snapshot = ApprovalReviewSnapshot(proposal, policy_input, policy_decision)
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
            ApprovalLifecycleChange("requested", None, approval, review_snapshot),
            actor_id=requester.actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        self._observe(
            approval,
            ControlPlaneOperation.APPROVAL_REQUEST,
            ControlPlaneOutcome.SUCCEEDED,
            correlation_id=correlation_id,
            causation_id=causation_id,
            started_ns=started_ns,
            route=ApprovalStatus.PENDING.value,
            result_code="REQUESTED",
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
        expected_version: AggregateVersion | None = None,
    ) -> Approval:
        return await self._human_decision(
            approval_id,
            principal=principal,
            status=ApprovalStatus.APPROVED,
            reason=reason,
            correlation_id=correlation_id,
            causation_id=causation_id,
            expected_version=expected_version,
        )

    async def reject(
        self,
        approval_id: ApprovalId,
        *,
        principal: Principal | None,
        reason: EventReason,
        correlation_id: CorrelationId,
        causation_id: CausationId,
        expected_version: AggregateVersion | None = None,
    ) -> Approval:
        return await self._human_decision(
            approval_id,
            principal=principal,
            status=ApprovalStatus.REJECTED,
            reason=reason,
            correlation_id=correlation_id,
            causation_id=causation_id,
            expected_version=expected_version,
        )

    async def expire(
        self,
        approval_id: ApprovalId,
        *,
        tenant_id: TenantId,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> Approval:
        started_ns = time.monotonic_ns()
        current = await self._required(approval_id, tenant_id=tenant_id)
        at = as_utc(self._clock())
        if at < current.expires_at:
            raise InvalidDomainValueError("Approval has not reached its expiry time")
        return await self._expire(
            current,
            at=at,
            correlation_id=correlation_id,
            causation_id=causation_id,
            started_ns=started_ns,
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
        expected_version: AggregateVersion | None,
    ) -> Approval:
        started_ns = time.monotonic_ns()
        tenant_id = TenantId("unauthenticated") if principal is None else principal.tenant_id
        approver = require_permission(
            principal,
            Permission.APPROVAL_DECIDE,
            tenant_id=tenant_id,
        )
        current = await self._required(approval_id, tenant_id=approver.tenant_id)
        if expected_version is not None and current.version != expected_version:
            raise InvalidDomainValueError("stale Approval lifecycle version")
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
                started_ns=started_ns,
            )
        decided = current.decide(status, actor_id=approver.actor_id, reason=reason, at=at)
        await self._apply(
            ApprovalLifecycleChange(status.value.lower(), current, decided),
            actor_id=approver.actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        self._observe(
            decided,
            ControlPlaneOperation.APPROVAL_DECIDE,
            (
                ControlPlaneOutcome.SUCCEEDED
                if status is ApprovalStatus.APPROVED
                else ControlPlaneOutcome.REJECTED
            ),
            correlation_id=correlation_id,
            causation_id=causation_id,
            started_ns=started_ns,
            route=status.value,
            result_code=status.value,
        )
        return decided

    async def _expire(
        self,
        current: Approval,
        *,
        at: datetime,
        correlation_id: CorrelationId,
        causation_id: CausationId,
        started_ns: int,
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
        self._observe(
            expired,
            ControlPlaneOperation.APPROVAL_EXPIRE,
            ControlPlaneOutcome.EXPIRED,
            correlation_id=correlation_id,
            causation_id=causation_id,
            started_ns=started_ns,
            route=ApprovalStatus.EXPIRED.value,
            result_code="EXPIRED",
        )
        return expired

    def _observe(
        self,
        approval: Approval,
        operation: ControlPlaneOperation,
        outcome: ControlPlaneOutcome,
        *,
        correlation_id: CorrelationId,
        causation_id: CausationId,
        started_ns: int,
        route: str,
        result_code: str,
    ) -> None:
        safely_record(
            self._observer,
            ControlPlaneObservation(
                component=ControlPlaneComponent.APPROVAL,
                operation=operation,
                outcome=outcome,
                occurred_at=utc_observation_time(),
                tenant_id=approval.tenant_id,
                incident_id=approval.incident_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                operation_id=OpaqueIdentifier(approval.id.value),
                duration_ms=max(0, (time.monotonic_ns() - started_ns) // 1_000_000),
                route=route,
                result_code=result_code,
                subject_name="approval",
                subject_version=approval.schema_version,
            ),
        )

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
