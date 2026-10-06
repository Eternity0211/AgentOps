"""Material remediation revision, Approval invalidation, and re-evaluation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    ApprovalInvalidationStore,
    EvidenceBoundRemediationProposal,
    PolicyReevaluationContext,
    PolicyRules,
    RemediationEvidenceGate,
    RemediationRevisionResult,
    RemediationRevisionService,
    RevisionOutcome,
    evidence_gate_decision_fingerprint,
)
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Approval,
    ApprovalId,
    ApprovalInvalidation,
    ApprovalStatus,
    AuditEvent,
    AuthorizationError,
    CausationId,
    CorrelationId,
    EventReason,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceId,
    IncidentId,
    InvalidDomainValueError,
    MaintenanceWindowStatus,
    OpaqueIdentifier,
    PolicyAction,
    PolicyBlastRadius,
    PolicyDecision,
    PolicyEnvironment,
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
from agentops_incident_commander.workflows import (
    REMEDIATION_PROPOSAL_SCHEMA_VERSION,
    RecoveryAction,
    RemediationFailureHandling,
    RemediationFailureRoute,
    RemediationProposal,
    RollbackPrerequisites,
    RollbackServiceParameters,
    RollbackVerificationConditions,
)

NOW = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)
TENANT = TenantId("tenant-revision")
INCIDENT = IncidentId("incident-revision")


def gate_decision() -> EvidenceGateDecision:
    return EvidenceGateDecision(
        incident_id=INCIDENT,
        candidate_id="candidate-deployment",
        outcome=EvidenceGateOutcome.PASS,
        reasons=(),
        evaluated_evidence_ids=(EvidenceId("evidence-1"), EvidenceId("evidence-2")),
        rules_version="1.1.0",
        input_fingerprint=Sha256Digest("a" * 64),
        evaluated_at=NOW,
        model_confidence_basis_points=8_000,
    )


def proposal(version: int = 1, **overrides: Any) -> RemediationProposal:
    decision = gate_decision()
    values: dict[str, Any] = {
        "schema_version": REMEDIATION_PROPOSAL_SCHEMA_VERSION,
        "proposal_id": "remediation-revision",
        "proposal_version": version,
        "incident_id": INCIDENT.value,
        "candidate_id": decision.candidate_id,
        "evidence_gate_input_fingerprint": decision.input_fingerprint.value,
        "evidence_gate_decision_fingerprint": evidence_gate_decision_fingerprint(decision).value,
        "action": RecoveryAction.ROLLBACK_SERVICE,
        "parameters": RollbackServiceParameters(
            service="orders",
            introducing_deployment_evidence_id="evidence-1",
        ),
        "prerequisites": RollbackPrerequisites(current_version_evidence_id="evidence-2"),
        "verification_conditions": RollbackVerificationConditions(
            max_error_rate_basis_points=100,
            max_p95_latency_ms=500,
            stability_window_seconds=300,
        ),
        "failure_handling": RemediationFailureHandling(
            route=RemediationFailureRoute.HUMAN_HANDOFF,
            max_rediagnosis_attempts=0,
        ),
        "risk_assumptions": ("The current deployment is faulty.",),
    }
    values.update(overrides)
    return RemediationProposal.model_validate(values)


def approval(prior: RemediationProposal, **overrides: Any) -> Approval:
    values: dict[str, Any] = {
        "id": ApprovalId("approval-revision"),
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "proposal_id": OpaqueIdentifier(prior.proposal_id),
        "proposal_version": prior.proposal_version,
        "proposal_fingerprint": prior.fingerprint,
        "policy_decision_id": OpaqueIdentifier("policy-prior"),
        "policy_decision_fingerprint": Sha256Digest("b" * 64),
        "policy_input_fingerprint": Sha256Digest("c" * 64),
        "proposer_actor_id": ActorId("operator-revision"),
        "risk_level": RiskLevel.HIGH,
        "independent_approver_required": True,
        "status": ApprovalStatus.APPROVED,
        "version": AggregateVersion(2),
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "decided_at": NOW + timedelta(minutes=1),
        "decided_by": ActorId("approver-revision"),
        "decision_reason": EventReason("Approved original proposal."),
    }
    values.update(overrides)
    return Approval(**values)


class GateStore:
    def __init__(self, value: EvidenceGateDecision | None) -> None:
        self.value = value

    async def get(self, **_: object) -> EvidenceGateDecision | None:
        return self.value


class InvalidationStore(ApprovalInvalidationStore):
    def __init__(self, existing: ApprovalInvalidation | None = None) -> None:
        self.existing = existing
        self.records: list[tuple[Approval, ApprovalInvalidation, AuditEvent]] = []

    async def get_invalidation(
        self, approval_id: ApprovalId, *, tenant_id: TenantId
    ) -> ApprovalInvalidation | None:
        return self.existing

    async def record_invalidation(
        self,
        current: Approval,
        invalidation: ApprovalInvalidation,
        audit_event: AuditEvent,
    ) -> None:
        self.records.append((current, invalidation, audit_event))
        self.existing = invalidation


def rules(**overrides: Any) -> PolicyRules:
    values: dict[str, Any] = {
        "version": SemanticVersion("1.0.0"),
        "allowed_environments": frozenset({PolicyEnvironment.PRODUCTION}),
        "allowed_requester_roles": frozenset({Role.OPERATOR}),
        "allowed_actions": frozenset({PolicyAction.ROLLBACK_SERVICE}),
        "allowed_services": frozenset({"orders"}),
        "allowed_blast_radii": frozenset({PolicyBlastRadius.SINGLE_SERVICE}),
        "require_active_maintenance_window": True,
        "require_separation_of_duties": True,
        "approval_ttl": timedelta(minutes=30),
    }
    values.update(overrides)
    return PolicyRules(**values)


def context(**overrides: Any) -> PolicyReevaluationContext:
    values: dict[str, Any] = {
        "environment": PolicyEnvironment.PRODUCTION,
        "blast_radius": PolicyBlastRadius.SINGLE_SERVICE,
        "maintenance_window": MaintenanceWindowStatus.ACTIVE,
        "separation_of_duties_required": True,
    }
    values.update(overrides)
    return PolicyReevaluationContext(**values)


def service(
    invalidations: InvalidationStore,
    stored_gate: EvidenceGateDecision | None,
) -> RemediationRevisionService:
    return RemediationRevisionService(
        invalidations,
        RemediationEvidenceGate(GateStore(stored_gate)),
        clock=lambda: NOW + timedelta(minutes=2),
        audit_id_factory=lambda: "audit-revision",
        policy_decision_id_factory=lambda: "policy-revision",
    )


def operator(*roles: Role, tenant: TenantId = TENANT) -> Principal:
    return Principal(ActorId("operator-revision"), tenant, frozenset(roles or (Role.OPERATOR,)))


def revised_payload(prior: RemediationProposal, **updates: object) -> dict[str, object]:
    payload = cast(dict[str, object], prior.model_dump(mode="python"))
    payload.update({"proposal_version": prior.proposal_version + 1})
    payload.update(updates)
    return payload


@pytest.mark.anyio
async def test_material_revision_invalidates_and_requires_fresh_approval() -> None:
    prior = proposal()
    current = approval(prior)
    invalidations = InvalidationStore()
    payload = revised_payload(prior, risk_assumptions=("A newly reviewed risk assumption.",))
    result = await service(invalidations, gate_decision()).revise(
        current,
        prior,
        payload,
        principal=operator(),
        policy_context=context(),
        policy_rules=rules(),
        correlation_id=CorrelationId("correlation-revision"),
        causation_id=CausationId("revise-remediation"),
    )
    assert result.outcome is RevisionOutcome.APPROVAL_REQUIRED
    assert result.policy_decision is not None
    assert result.policy_decision.outcome is PolicyOutcome.APPROVAL_REQUIRED
    assert result.policy_input is not None
    assert result.policy_input.proposal_fingerprint == result.proposal.fingerprint
    assert result.invalidation.replacement_proposal_fingerprint == result.proposal.fingerprint
    assert len(invalidations.records) == 1
    _, invalidation, audit = invalidations.records[0]
    assert audit.type == "approval.invalidated"
    assert audit.request_hash == current.fingerprint
    assert audit.result_hash == invalidation.fingerprint
    assert result.proposal.material_fingerprint != prior.material_fingerprint
    with pytest.raises(InvalidDomainValueError, match="Policy outcome"):
        replace(result, outcome=RevisionOutcome.POLICY_DENIED)


@pytest.mark.anyio
async def test_gate_failure_keeps_invalidation_and_stops_before_policy() -> None:
    prior = proposal()
    invalidations = InvalidationStore()
    result = await service(invalidations, None).revise(
        approval(prior),
        prior,
        revised_payload(prior, risk_assumptions=("Changed and must be revalidated.",)),
        principal=operator(),
        policy_context=context(),
        policy_rules=rules(),
        correlation_id=CorrelationId("correlation-revision"),
        causation_id=CausationId("revise-remediation"),
    )
    assert result.outcome is RevisionOutcome.EVIDENCE_GATE_REJECTED
    assert result.admitted is None
    assert result.policy_input is None
    assert len(invalidations.records) == 1


@pytest.mark.anyio
async def test_policy_denial_cannot_reuse_old_approval() -> None:
    prior = proposal()
    invalidations = InvalidationStore()
    result = await service(invalidations, gate_decision()).revise(
        approval(prior),
        prior,
        revised_payload(prior, risk_assumptions=("Changed policy-relevant risk.",)),
        principal=operator(),
        policy_context=context(),
        policy_rules=rules(allowed_services=frozenset()),
        correlation_id=CorrelationId("correlation-revision"),
        causation_id=CausationId("revise-remediation"),
    )
    assert result.outcome is RevisionOutcome.POLICY_DENIED
    assert result.policy_decision is not None
    assert result.policy_decision.outcome is PolicyOutcome.DENY
    assert invalidations.existing == result.invalidation


@pytest.mark.anyio
async def test_unexpected_direct_allow_from_policy_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentops_incident_commander.application import remediation_revision as revision_module

    def direct_allow(
        policy_input: object,
        admitted: EvidenceBoundRemediationProposal,
        *,
        rules: PolicyRules,
        decision_id: OpaqueIdentifier,
        evaluated_at: datetime,
    ) -> PolicyDecision:
        typed_input = cast(Any, policy_input)
        return PolicyDecision(
            id=decision_id,
            policy_version=rules.version,
            input_fingerprint=typed_input.fingerprint,
            proposal_fingerprint=admitted.proposal.fingerprint,
            outcome=PolicyOutcome.ALLOW,
            risk_level=RiskLevel.HIGH,
            reasons=(PolicyReason(PolicyReasonCode.POLICY_SATISFIED, "Policy satisfied."),),
            evaluated_at=evaluated_at,
        )

    monkeypatch.setattr(revision_module, "evaluate_remediation_policy", direct_allow)
    prior = proposal()
    with pytest.raises(InvalidDomainValueError, match="unsupported Policy outcome"):
        await service(InvalidationStore(), gate_decision()).revise(
            approval(prior),
            prior,
            revised_payload(prior, risk_assumptions=("Changed revision.",)),
            principal=operator(),
            policy_context=context(),
            policy_rules=rules(),
            correlation_id=CorrelationId("correlation-revision"),
            causation_id=CausationId("direct-allow"),
        )


@pytest.mark.anyio
async def test_invalid_schema_identity_version_or_nonmaterial_revision_fails_first() -> None:
    prior = proposal()
    current = approval(prior)
    invalidations = InvalidationStore()
    candidates = (
        {**revised_payload(prior), "unexpected": True},
        revised_payload(prior, proposal_id="other-proposal"),
        revised_payload(prior, incident_id="other-incident"),
        revised_payload(prior, proposal_version=1, risk_assumptions=("changed",)),
        revised_payload(prior),
    )
    for payload in candidates:
        with pytest.raises(InvalidDomainValueError):
            await service(invalidations, gate_decision()).revise(
                current,
                prior,
                payload,
                principal=operator(),
                policy_context=context(),
                policy_rules=rules(),
                correlation_id=CorrelationId("correlation-revision"),
                causation_id=CausationId("invalid-revision"),
            )
    assert invalidations.records == []


@pytest.mark.anyio
async def test_prior_binding_terminal_approval_duplicate_and_authorization_fail_closed() -> None:
    prior = proposal()
    current = approval(prior)
    payload = revised_payload(prior, risk_assumptions=("Changed revision.",))
    invalid_cases = (
        (replace(current, proposal_fingerprint=Sha256Digest("f" * 64)), prior, operator()),
        (replace(current, status=ApprovalStatus.REJECTED), prior, operator()),
        (current, prior, operator(Role.VIEWER)),
        (current, prior, operator(tenant=TenantId("tenant-other"))),
    )
    for selected_approval, selected_prior, actor in invalid_cases:
        with pytest.raises((InvalidDomainValueError, AuthorizationError)):
            await service(InvalidationStore(), gate_decision()).revise(
                selected_approval,
                selected_prior,
                payload,
                principal=actor,
                policy_context=context(),
                policy_rules=rules(),
                correlation_id=CorrelationId("correlation-revision"),
                causation_id=CausationId("invalid-revision"),
            )

    first_store = InvalidationStore()
    first = await service(first_store, gate_decision()).revise(
        current,
        prior,
        payload,
        principal=operator(),
        policy_context=context(),
        policy_rules=rules(),
        correlation_id=CorrelationId("correlation-revision"),
        causation_id=CausationId("first-revision"),
    )
    with pytest.raises(InvalidDomainValueError, match="already invalidated"):
        await service(first_store, gate_decision()).revise(
            current,
            prior,
            payload,
            principal=operator(),
            policy_context=context(),
            policy_rules=rules(),
            correlation_id=CorrelationId("correlation-revision"),
            causation_id=CausationId("duplicate-revision"),
        )
    assert first_store.existing == first.invalidation


def test_revision_context_result_and_invalidation_contracts_fail_closed() -> None:
    with pytest.raises(InvalidDomainValueError, match="context"):
        context(environment="PRODUCTION")
    prior = proposal()
    current = approval(prior)
    invalidation = ApprovalInvalidation(
        approval_id=current.id,
        tenant_id=TENANT,
        incident_id=INCIDENT,
        approval_fingerprint=current.fingerprint,
        prior_proposal_fingerprint=prior.fingerprint,
        replacement_proposal_id=OpaqueIdentifier(prior.proposal_id),
        replacement_proposal_version=2,
        replacement_proposal_fingerprint=Sha256Digest("d" * 64),
        replacement_material_fingerprint=Sha256Digest("e" * 64),
        invalidated_by=ActorId("operator-revision"),
        invalidated_at=NOW,
    )
    assert len(invalidation.fingerprint.value) == 64
    with pytest.raises(InvalidDomainValueError, match="inconsistent"):
        RemediationRevisionResult(
            proposal(2, risk_assumptions=("changed",)),
            invalidation,
            RevisionOutcome.APPROVAL_REQUIRED,
        )
    invalid_values = (
        {"approval_id": OpaqueIdentifier("wrong")},
        {"replacement_proposal_version": 0},
        {"schema_version": "2.0.0"},
    )
    for changes in invalid_values:
        with pytest.raises(InvalidDomainValueError):
            replace(invalidation, **changes)
