"""Proposal-bound Approval aggregate and lifecycle tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.application import (
    ApprovalLifecycleChange,
    ApprovalLifecycleManager,
)
from agentops_incident_commander.domain import (
    APPROVAL_SCHEMA_VERSION,
    ActorId,
    AggregateVersion,
    Approval,
    ApprovalId,
    ApprovalStatus,
    AuditEvent,
    AuthenticationError,
    AuthorizationError,
    CausationId,
    CorrelationId,
    EventReason,
    IncidentId,
    InvalidDomainValueError,
    MaintenanceWindowStatus,
    OpaqueIdentifier,
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
)
from agentops_incident_commander.infrastructure.persistence import ApprovalLifecycleRepository

NOW = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)
TENANT = TenantId("tenant-approval")
INCIDENT = IncidentId("incident-approval")


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class Store:
    def __init__(self) -> None:
        self.values: dict[tuple[TenantId, ApprovalId], Approval] = {}
        self.applied: list[tuple[ApprovalLifecycleChange, AuditEvent]] = []

    async def get(self, approval_id: ApprovalId, *, tenant_id: TenantId) -> Approval | None:
        return self.values.get((tenant_id, approval_id))

    async def apply(self, change: ApprovalLifecycleChange, audit_event: AuditEvent) -> None:
        key = (change.after.tenant_id, change.after.id)
        current = self.values.get(key)
        if current != change.before:
            raise InvalidDomainValueError("stale Approval lifecycle state")
        self.values[key] = change.after
        self.applied.append((change, audit_event))


def principal(
    actor: str,
    *roles: Role,
    tenant: TenantId = TENANT,
) -> Principal:
    return Principal(ActorId(actor), tenant, frozenset(roles))


def policy_input(**overrides: Any) -> PolicyEvaluationInput:
    values: dict[str, Any] = {
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "proposal_id": OpaqueIdentifier("remediation-approval-1"),
        "proposal_version": 1,
        "proposal_fingerprint": Sha256Digest("a" * 64),
        "evidence_gate_decision_fingerprint": Sha256Digest("b" * 64),
        "requester_actor_id": ActorId("operator-approval"),
        "requester_roles": frozenset({Role.OPERATOR}),
        "environment": PolicyEnvironment.PRODUCTION,
        "action": PolicyAction.ROLLBACK_SERVICE,
        "service": "orders",
        "blast_radius": PolicyBlastRadius.SINGLE_SERVICE,
        "maintenance_window": MaintenanceWindowStatus.ACTIVE,
        "separation_of_duties_required": True,
        "requested_at": NOW,
    }
    values.update(overrides)
    return PolicyEvaluationInput(**values)


def policy_decision(value: PolicyEvaluationInput, **overrides: Any) -> PolicyDecision:
    values: dict[str, Any] = {
        "id": OpaqueIdentifier("policy-decision-approval-1"),
        "policy_version": SemanticVersion("1.0.0"),
        "input_fingerprint": value.fingerprint,
        "proposal_fingerprint": value.proposal_fingerprint,
        "outcome": PolicyOutcome.APPROVAL_REQUIRED,
        "risk_level": RiskLevel.HIGH,
        "reasons": (
            PolicyReason(
                PolicyReasonCode.APPROVAL_REQUIRED,
                "Human approval is required before rollback execution.",
            ),
        ),
        "evaluated_at": NOW,
        "approval_ttl": timedelta(minutes=30),
    }
    values.update(overrides)
    return PolicyDecision(**values)


def manager(store: Store, clock: Clock) -> ApprovalLifecycleManager:
    approval_ids = count(1)
    audit_ids = count(1)
    return ApprovalLifecycleManager(
        store,
        clock=clock,
        approval_id_factory=lambda: f"approval-{next(approval_ids)}",
        audit_id_factory=lambda: f"approval-audit-{next(audit_ids)}",
        expiry_actor_id=ActorId("approval-expiry-worker"),
    )


async def request_approval(
    lifecycle: ApprovalLifecycleManager,
    value: PolicyEvaluationInput | None = None,
    decision: PolicyDecision | None = None,
    requester: Principal | None = None,
) -> Approval:
    selected_input = policy_input() if value is None else value
    selected_decision = policy_decision(selected_input) if decision is None else decision
    selected_requester = (
        principal("operator-approval", Role.OPERATOR) if requester is None else requester
    )
    return await lifecycle.request(
        selected_input,
        selected_decision,
        principal=selected_requester,
        correlation_id=CorrelationId("correlation-approval"),
        causation_id=CausationId("request-approval"),
    )


@pytest.mark.anyio
async def test_request_and_independent_approval_are_hash_bound_and_audited() -> None:
    store = Store()
    clock = Clock(NOW + timedelta(minutes=1))
    lifecycle = manager(store, clock)
    requested = await request_approval(lifecycle)
    assert requested.schema_version == APPROVAL_SCHEMA_VERSION
    assert requested.status is ApprovalStatus.PENDING
    assert requested.version == AggregateVersion(1)
    assert requested.expires_at == NOW + timedelta(minutes=30)
    assert requested.independent_approver_required
    request_change, request_audit = store.applied[0]
    assert request_change.before is None
    assert request_audit.type == "approval.requested"
    assert request_audit.request_hash == requested.policy_decision_fingerprint
    assert request_audit.result_hash == requested.fingerprint

    clock.value = NOW + timedelta(minutes=2)
    approved = await lifecycle.approve(
        requested.id,
        principal=principal("approver-approval", Role.APPROVER),
        reason=EventReason("Reviewed evidence and rollback scope."),
        correlation_id=CorrelationId("correlation-approval"),
        causation_id=CausationId("approve-approval"),
    )
    assert approved.status is ApprovalStatus.APPROVED
    assert approved.version == AggregateVersion(2)
    assert approved.decided_by == ActorId("approver-approval")
    approve_change, approve_audit = store.applied[1]
    assert approve_change.before == requested
    assert approve_audit.type == "approval.approved"
    assert approve_audit.request_hash == requested.fingerprint
    assert approve_audit.result_hash == approved.fingerprint


@pytest.mark.anyio
async def test_rejection_is_terminal_and_audited() -> None:
    store = Store()
    clock = Clock(NOW + timedelta(minutes=1))
    lifecycle = manager(store, clock)
    requested = await request_approval(lifecycle)
    rejected = await lifecycle.reject(
        requested.id,
        principal=principal("approver-approval", Role.APPROVER),
        reason=EventReason("Rollback scope needs revision."),
        correlation_id=CorrelationId("correlation-approval"),
        causation_id=CausationId("reject-approval"),
    )
    assert rejected.status is ApprovalStatus.REJECTED
    assert store.applied[-1][1].type == "approval.rejected"
    with pytest.raises(InvalidDomainValueError, match="only a pending"):
        await lifecycle.approve(
            rejected.id,
            principal=principal("approver-2", Role.APPROVER),
            reason=EventReason("Cannot revise a terminal Approval."),
            correlation_id=CorrelationId("correlation-approval"),
            causation_id=CausationId("approve-terminal"),
        )


@pytest.mark.anyio
async def test_explicit_and_late_decisions_expire_with_system_actor() -> None:
    for late_action in ("expire", "approve", "reject"):
        store = Store()
        clock = Clock(NOW + timedelta(minutes=1))
        lifecycle = manager(store, clock)
        requested = await request_approval(lifecycle)
        with pytest.raises(InvalidDomainValueError, match="not reached"):
            await lifecycle.expire(
                requested.id,
                tenant_id=TENANT,
                correlation_id=CorrelationId("correlation-approval"),
                causation_id=CausationId("early-expiry"),
            )
        clock.value = requested.expires_at
        if late_action == "expire":
            expired = await lifecycle.expire(
                requested.id,
                tenant_id=TENANT,
                correlation_id=CorrelationId("correlation-approval"),
                causation_id=CausationId("expiry-scan"),
            )
        else:
            operation = getattr(lifecycle, late_action)
            expired = await operation(
                requested.id,
                principal=principal("approver-approval", Role.APPROVER),
                reason=EventReason("Too late to decide."),
                correlation_id=CorrelationId("correlation-approval"),
                causation_id=CausationId(f"late-{late_action}"),
            )
        assert expired.status is ApprovalStatus.EXPIRED
        assert expired.decided_by == ActorId("approval-expiry-worker")
        assert expired.decision_reason == EventReason("Approval lifetime expired.")
        assert store.applied[-1][1].type == "approval.expired"


@pytest.mark.anyio
async def test_request_rejects_nonmatching_stale_or_nonapproval_policy() -> None:
    store = Store()
    clock = Clock(NOW + timedelta(minutes=1))
    lifecycle = manager(store, clock)
    value = policy_input()
    invalid_decisions = (
        policy_decision(value, input_fingerprint=Sha256Digest("c" * 64)),
        policy_decision(value, proposal_fingerprint=Sha256Digest("d" * 64)),
        policy_decision(
            value,
            outcome=PolicyOutcome.DENY,
            reasons=(PolicyReason(PolicyReasonCode.ROLE_DENIED, "Requester role denied."),),
            approval_ttl=None,
        ),
        policy_decision(value, evaluated_at=NOW + timedelta(minutes=2)),
    )
    for invalid in invalid_decisions:
        with pytest.raises(InvalidDomainValueError):
            await request_approval(lifecycle, value, invalid)
    clock.value = NOW + timedelta(minutes=30)
    with pytest.raises(InvalidDomainValueError, match="expired"):
        await request_approval(lifecycle, value, policy_decision(value))
    assert store.applied == []


@pytest.mark.anyio
async def test_requester_and_approver_authorization_fail_closed() -> None:
    store = Store()
    clock = Clock(NOW + timedelta(minutes=1))
    lifecycle = manager(store, clock)
    value = policy_input()
    for requester in (
        principal("viewer", Role.VIEWER),
        principal("other-operator", Role.OPERATOR),
        principal("operator-approval", Role.OPERATOR, Role.APPROVER),
        principal("operator-approval", Role.OPERATOR, tenant=TenantId("tenant-other")),
    ):
        with pytest.raises(AuthorizationError):
            await request_approval(lifecycle, value, requester=requester)
    with pytest.raises(AuthenticationError):
        await lifecycle.request(
            value,
            policy_decision(value),
            principal=None,
            correlation_id=CorrelationId("correlation-approval"),
            causation_id=CausationId("anonymous-request"),
        )

    requested = await request_approval(lifecycle, value)
    unauthorized: tuple[Principal | None, ...] = (
        None,
        principal("viewer", Role.VIEWER),
        principal("operator-approval", Role.APPROVER),
        principal("approver", Role.APPROVER, tenant=TenantId("tenant-other")),
    )
    for actor in unauthorized:
        with pytest.raises((AuthenticationError, AuthorizationError, InvalidDomainValueError)):
            await lifecycle.approve(
                requested.id,
                principal=actor,
                reason=EventReason("Unauthorized decision."),
                correlation_id=CorrelationId("correlation-approval"),
                causation_id=CausationId("unauthorized-decision"),
            )
    assert len(store.applied) == 1


@pytest.mark.anyio
async def test_low_risk_can_disable_independence_but_still_requires_approver_permission() -> None:
    store = Store()
    clock = Clock(NOW + timedelta(minutes=1))
    lifecycle = manager(store, clock)
    requester = principal("dual-role", Role.OPERATOR, Role.APPROVER)
    value = policy_input(
        requester_actor_id=requester.actor_id,
        requester_roles=requester.roles,
        environment=PolicyEnvironment.DEVELOPMENT,
        separation_of_duties_required=False,
    )
    decision = policy_decision(value, risk_level=RiskLevel.LOW)
    requested = await request_approval(lifecycle, value, decision, requester)
    assert not requested.independent_approver_required
    approved = await lifecycle.approve(
        requested.id,
        principal=requester,
        reason=EventReason("Low-risk self approval allowed by policy."),
        correlation_id=CorrelationId("correlation-approval"),
        causation_id=CausationId("approve-low-risk"),
    )
    assert approved.status is ApprovalStatus.APPROVED


@pytest.mark.anyio
async def test_invalid_lookup_and_repository_change_or_audit_fail_before_storage() -> None:
    store = Store()
    clock = Clock(NOW + timedelta(minutes=1))
    lifecycle = manager(store, clock)
    requested = await request_approval(lifecycle)
    with pytest.raises(InvalidDomainValueError, match="lookup scope"):
        await lifecycle.approve(
            cast(ApprovalId, OpaqueIdentifier("wrong-id-type")),
            principal=principal("approver", Role.APPROVER),
            reason=EventReason("Invalid lookup."),
            correlation_id=CorrelationId("correlation-approval"),
            causation_id=CausationId("invalid-lookup"),
        )

    change, audit = store.applied[0]
    repository = ApprovalLifecycleRepository(cast(AsyncSession, object()))
    with pytest.raises(InvalidDomainValueError, match="invalid Approval lifecycle"):
        await repository.apply(replace(change, action="approved"), audit)
    with pytest.raises(InvalidDomainValueError, match="audit event"):
        await repository.apply(
            change,
            replace(audit, tenant_id=TenantId("tenant-other")),
        )
    assert requested.status is ApprovalStatus.PENDING


def test_approval_contract_rejects_invalid_state_and_is_immutable() -> None:
    value = policy_input()
    decision = policy_decision(value)
    base = Approval(
        id=ApprovalId("approval-contract"),
        tenant_id=TENANT,
        incident_id=INCIDENT,
        proposal_id=value.proposal_id,
        proposal_version=1,
        proposal_fingerprint=value.proposal_fingerprint,
        policy_decision_id=decision.id,
        policy_decision_fingerprint=decision.fingerprint,
        policy_input_fingerprint=value.fingerprint,
        proposer_actor_id=value.requester_actor_id,
        risk_level=RiskLevel.HIGH,
        independent_approver_required=True,
        status=ApprovalStatus.PENDING,
        version=AggregateVersion.initial(),
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )
    assert len(base.fingerprint.value) == 64
    with pytest.raises(FrozenInstanceError):
        base.status = ApprovalStatus.APPROVED  # type: ignore[misc]
    invalid = (
        {"id": OpaqueIdentifier("wrong-id-type")},
        {"decided_at": "not-a-date"},
        {"decided_by": "not-an-actor"},
        {"decision_reason": "not-a-reason"},
        {"proposal_version": 0},
        {"independent_approver_required": 1},
        {"expires_at": NOW},
        {"status": ApprovalStatus.APPROVED},
        {
            "status": ApprovalStatus.APPROVED,
            "decided_at": NOW - timedelta(seconds=1),
            "decided_by": ActorId("approver"),
            "decision_reason": EventReason("Decision precedes request."),
        },
        {
            "status": ApprovalStatus.APPROVED,
            "decided_at": NOW + timedelta(minutes=30),
            "decided_by": ActorId("approver"),
            "decision_reason": EventReason("At expiry is too late."),
        },
        {
            "status": ApprovalStatus.EXPIRED,
            "decided_at": NOW + timedelta(minutes=29),
            "decided_by": ActorId("expiry-worker"),
            "decision_reason": EventReason("Too early."),
        },
        {"schema_version": "2.0.0"},
    )
    for changes in invalid:
        with pytest.raises(InvalidDomainValueError):
            replace(base, **changes)
    with pytest.raises(InvalidDomainValueError, match="terminal status"):
        base.decide(
            ApprovalStatus.PENDING,
            actor_id=ActorId("approver"),
            reason=EventReason("Invalid pending decision."),
            at=NOW + timedelta(minutes=1),
        )
