"""Authoritative rollback preflight and fail-closed bypass tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    EvidenceBoundRemediationProposal,
    PolicyRules,
    RemediationEvidenceGate,
    RollbackExecutionPreflight,
    evaluate_remediation_policy,
    evidence_gate_decision_fingerprint,
)
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Approval,
    ApprovalId,
    ApprovalInvalidation,
    ApprovalStatus,
    AuthenticationError,
    AuthorizationError,
    EventReason,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceId,
    IdempotencyKey,
    Incident,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    MaintenanceWindowStatus,
    ManagedServiceTarget,
    OpaqueIdentifier,
    PolicyAction,
    PolicyBlastRadius,
    PolicyDecision,
    PolicyEnvironment,
    PolicyEvaluationInput,
    Principal,
    Role,
    RollbackServiceRequest,
    RollbackTargetCatalog,
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

NOW = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
TENANT = TenantId("tenant-execution")
INCIDENT = IncidentId("incident-execution")
CURRENT_VERSION = SemanticVersion("2.0.0")


def gate_decision() -> EvidenceGateDecision:
    return EvidenceGateDecision(
        incident_id=INCIDENT,
        candidate_id="candidate-deployment",
        outcome=EvidenceGateOutcome.PASS,
        reasons=(),
        evaluated_evidence_ids=(EvidenceId("evidence-release"), EvidenceId("evidence-version")),
        rules_version="1.1.0",
        input_fingerprint=Sha256Digest("a" * 64),
        evaluated_at=NOW,
        model_confidence_basis_points=8_000,
    )


def proposal(**overrides: Any) -> RemediationProposal:
    gate = gate_decision()
    values: dict[str, Any] = {
        "schema_version": REMEDIATION_PROPOSAL_SCHEMA_VERSION,
        "proposal_id": "remediation-execution",
        "proposal_version": 1,
        "incident_id": INCIDENT.value,
        "candidate_id": gate.candidate_id,
        "evidence_gate_input_fingerprint": gate.input_fingerprint.value,
        "evidence_gate_decision_fingerprint": evidence_gate_decision_fingerprint(gate).value,
        "action": RecoveryAction.ROLLBACK_SERVICE,
        "parameters": RollbackServiceParameters(
            service="orders",
            introducing_deployment_evidence_id="evidence-release",
        ),
        "prerequisites": RollbackPrerequisites(current_version_evidence_id="evidence-version"),
        "verification_conditions": RollbackVerificationConditions(
            max_error_rate_basis_points=100,
            max_p95_latency_ms=500,
            stability_window_seconds=300,
        ),
        "failure_handling": RemediationFailureHandling(
            route=RemediationFailureRoute.HUMAN_HANDOFF,
            max_rediagnosis_attempts=0,
        ),
        "risk_assumptions": ("The current deployment introduced the regression.",),
    }
    values.update(overrides)
    return RemediationProposal.model_validate(values)


def policy_rules(**overrides: Any) -> PolicyRules:
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


def policy_input(value: RemediationProposal, **overrides: Any) -> PolicyEvaluationInput:
    gate = gate_decision()
    values: dict[str, Any] = {
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "proposal_id": OpaqueIdentifier(value.proposal_id),
        "proposal_version": value.proposal_version,
        "proposal_fingerprint": value.fingerprint,
        "evidence_gate_decision_fingerprint": evidence_gate_decision_fingerprint(gate),
        "requester_actor_id": ActorId("operator-execution"),
        "requester_roles": frozenset({Role.OPERATOR}),
        "environment": PolicyEnvironment.PRODUCTION,
        "action": PolicyAction.ROLLBACK_SERVICE,
        "service": value.parameters.service,
        "blast_radius": PolicyBlastRadius.SINGLE_SERVICE,
        "maintenance_window": MaintenanceWindowStatus.ACTIVE,
        "separation_of_duties_required": True,
        "requested_at": NOW,
    }
    values.update(overrides)
    return PolicyEvaluationInput(**values)


def incident(**overrides: Any) -> Incident:
    values: dict[str, Any] = {
        "id": INCIDENT,
        "tenant_id": TENANT,
        "severity": IncidentSeverity.SEV1,
        "opened_at": NOW - timedelta(hours=1),
        "updated_at": NOW,
        "state": IncidentState.READY_TO_EXECUTE,
        "version": AggregateVersion(9),
    }
    values.update(overrides)
    return Incident(**values)


def managed_target() -> ManagedServiceTarget:
    return ManagedServiceTarget(
        tenant_id=TENANT,
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=OpaqueIdentifier("simulator-orders"),
        allowed_versions=(SemanticVersion("1.0.0"), SemanticVersion("2.0.0")),
        stable_version=SemanticVersion("1.0.0"),
    )


class GateStore:
    def __init__(self, value: EvidenceGateDecision | None) -> None:
        self.value = value

    async def get(self, **_: object) -> EvidenceGateDecision | None:
        return self.value


class IncidentStore:
    def __init__(self, value: Incident | None) -> None:
        self.value = value
        self.lookups: list[tuple[IncidentId, TenantId]] = []

    async def get_for_tenant(self, incident_id: IncidentId, tenant_id: TenantId) -> Incident | None:
        self.lookups.append((incident_id, tenant_id))
        return self.value


class ApprovalStore:
    def __init__(
        self,
        value: Approval | None,
        invalidation: ApprovalInvalidation | None = None,
    ) -> None:
        self.value = value
        self.invalidation = invalidation

    async def get(self, approval_id: ApprovalId, *, tenant_id: TenantId) -> Approval | None:
        if self.value is None or self.value.id != approval_id or self.value.tenant_id != tenant_id:
            return None
        return self.value

    async def get_invalidation(
        self, approval_id: ApprovalId, *, tenant_id: TenantId
    ) -> ApprovalInvalidation | None:
        assert self.value is not None
        assert approval_id == self.value.id and tenant_id == self.value.tenant_id
        return self.invalidation


class VersionStore:
    def __init__(self, value: SemanticVersion | None) -> None:
        self.value = value
        self.lookups: list[tuple[TenantId, str, PolicyEnvironment]] = []

    async def get_current_version(
        self,
        *,
        tenant_id: TenantId,
        service: str,
        environment: PolicyEnvironment,
    ) -> SemanticVersion | None:
        self.lookups.append((tenant_id, service, environment))
        return self.value


def authority_values() -> tuple[
    RemediationProposal,
    PolicyEvaluationInput,
    PolicyDecision,
    Approval,
]:
    proposed = proposal()
    evaluated_input = policy_input(proposed)
    rules = policy_rules()
    admitted = EvidenceBoundRemediationProposal(TENANT, proposed, gate_decision())
    decision = evaluate_remediation_policy(
        evaluated_input,
        admitted,
        rules=rules,
        decision_id=OpaqueIdentifier("policy-execution"),
        evaluated_at=NOW + timedelta(minutes=1),
    )
    approved = Approval(
        id=ApprovalId("approval-execution"),
        tenant_id=TENANT,
        incident_id=INCIDENT,
        proposal_id=OpaqueIdentifier(proposed.proposal_id),
        proposal_version=proposed.proposal_version,
        proposal_fingerprint=proposed.fingerprint,
        policy_decision_id=decision.id,
        policy_decision_fingerprint=decision.fingerprint,
        policy_input_fingerprint=evaluated_input.fingerprint,
        proposer_actor_id=evaluated_input.requester_actor_id,
        risk_level=decision.risk_level,
        independent_approver_required=True,
        status=ApprovalStatus.APPROVED,
        version=AggregateVersion(2),
        requested_at=NOW + timedelta(minutes=2),
        expires_at=NOW + timedelta(minutes=31),
        decided_at=NOW + timedelta(minutes=3),
        decided_by=ActorId("approver-execution"),
        decision_reason=EventReason("Approved for bounded rollback."),
    )
    return proposed, evaluated_input, decision, approved


def preflight(
    approved: Approval | None,
    *,
    current_incident: Incident | None = None,
    invalidation: ApprovalInvalidation | None = None,
    current_version: SemanticVersion | None = CURRENT_VERSION,
    rules: PolicyRules | None = None,
    now: datetime = NOW + timedelta(minutes=4),
) -> tuple[RollbackExecutionPreflight, IncidentStore, VersionStore]:
    incidents = IncidentStore(incident() if current_incident is None else current_incident)
    versions = VersionStore(current_version)
    service = RollbackExecutionPreflight(
        incidents,
        ApprovalStore(approved, invalidation),
        RemediationEvidenceGate(GateStore(gate_decision())),
        versions,
        RollbackTargetCatalog((managed_target(),)),
        policy_rules() if rules is None else rules,
        clock=lambda: now,
    )
    return service, incidents, versions


def request() -> RollbackServiceRequest:
    return RollbackServiceRequest(
        INCIDENT,
        ApprovalId("approval-execution"),
        IdempotencyKey("rollback-execution-1"),
    )


def operator(*roles: Role, tenant_id: TenantId = TENANT) -> Principal:
    return Principal(
        ActorId("executor-operator"),
        tenant_id,
        frozenset(roles or (Role.OPERATOR,)),
    )


@pytest.mark.anyio
async def test_preflight_reloads_authority_and_resolves_only_server_owned_target() -> None:
    proposed, evaluated_input, decision, approved = authority_values()
    service, incidents, versions = preflight(approved)

    authorized = await service.authorize(
        request(),
        proposed,
        evaluated_input,
        decision,
        principal=operator(),
    )

    assert authorized.actor_id == ActorId("executor-operator")
    assert authorized.incident == incident()
    assert authorized.approval == approved
    assert authorized.target.target_reference == OpaqueIdentifier("simulator-orders")
    assert authorized.target.expected_current_version == SemanticVersion("2.0.0")
    assert authorized.target.stable_version == SemanticVersion("1.0.0")
    assert authorized.authorized_at == NOW + timedelta(minutes=4)
    assert incidents.lookups == [(INCIDENT, TENANT)]
    assert versions.lookups == [(TENANT, "orders", PolicyEnvironment.PRODUCTION)]


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["request", "proposal", "policy_input", "policy_decision"])
async def test_preflight_rejects_untyped_authority_inputs(field: str) -> None:
    proposed, evaluated_input, decision, approved = authority_values()
    values: dict[str, object] = {
        "request": request(),
        "proposal": proposed,
        "policy_input": evaluated_input,
        "policy_decision": decision,
    }
    values[field] = "invalid"
    service, _, _ = preflight(approved)

    with pytest.raises(InvalidDomainValueError, match="inputs are invalid"):
        await service.authorize(
            cast(RollbackServiceRequest, values["request"]),
            cast(RemediationProposal, values["proposal"]),
            cast(PolicyEvaluationInput, values["policy_input"]),
            values["policy_decision"],  # type: ignore[arg-type]
            principal=operator(),
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("principal", "error"),
    [
        (None, AuthenticationError),
        (operator(Role.VIEWER), AuthorizationError),
        (operator(tenant_id=TenantId("tenant-other")), AuthorizationError),
    ],
)
async def test_preflight_rejects_missing_permission_or_cross_tenant_actor(
    principal: Principal | None,
    error: type[Exception],
) -> None:
    proposed, evaluated_input, decision, approved = authority_values()
    service, _, _ = preflight(approved)
    with pytest.raises(error):
        await service.authorize(request(), proposed, evaluated_input, decision, principal=principal)


@pytest.mark.anyio
async def test_preflight_rejects_missing_wrong_state_or_mismatched_incident() -> None:
    proposed, evaluated_input, decision, approved = authority_values()
    missing = RollbackExecutionPreflight(
        IncidentStore(None),
        ApprovalStore(approved),
        RemediationEvidenceGate(GateStore(gate_decision())),
        VersionStore(CURRENT_VERSION),
        RollbackTargetCatalog((managed_target(),)),
        policy_rules(),
        clock=lambda: NOW + timedelta(minutes=4),
    )
    with pytest.raises(InvalidDomainValueError, match="was not found"):
        await missing.authorize(
            request(), proposed, evaluated_input, decision, principal=operator()
        )

    wrong_state, _, _ = preflight(
        approved,
        current_incident=incident(state=IncidentState.POLICY_REVIEW),
    )
    with pytest.raises(InvalidDomainValueError, match="not ready"):
        await wrong_state.authorize(
            request(), proposed, evaluated_input, decision, principal=operator()
        )

    mismatched = proposal(incident_id="incident-other")
    service, _, _ = preflight(approved)
    with pytest.raises(InvalidDomainValueError, match="Incident authority binding"):
        await service.authorize(
            request(), mismatched, evaluated_input, decision, principal=operator()
        )


@pytest.mark.anyio
async def test_preflight_rejects_missing_rejected_expired_or_invalidated_approval() -> None:
    proposed, evaluated_input, decision, approved = authority_values()
    missing, _, _ = preflight(None)
    with pytest.raises(InvalidDomainValueError, match="Approval was not found"):
        await missing.authorize(
            request(), proposed, evaluated_input, decision, principal=operator()
        )

    rejected, _, _ = preflight(replace(approved, status=ApprovalStatus.REJECTED))
    with pytest.raises(InvalidDomainValueError, match="is not approved"):
        await rejected.authorize(
            request(), proposed, evaluated_input, decision, principal=operator()
        )

    expired, _, _ = preflight(approved, now=approved.expires_at)
    with pytest.raises(InvalidDomainValueError, match="has expired"):
        await expired.authorize(
            request(), proposed, evaluated_input, decision, principal=operator()
        )

    invalidation = ApprovalInvalidation(
        approval_id=approved.id,
        tenant_id=approved.tenant_id,
        incident_id=approved.incident_id,
        approval_fingerprint=approved.fingerprint,
        prior_proposal_fingerprint=approved.proposal_fingerprint,
        replacement_proposal_id=approved.proposal_id,
        replacement_proposal_version=2,
        replacement_proposal_fingerprint=Sha256Digest("b" * 64),
        replacement_material_fingerprint=Sha256Digest("c" * 64),
        invalidated_by=ActorId("operator-execution"),
        invalidated_at=NOW + timedelta(minutes=4),
    )
    invalidated, _, _ = preflight(approved, invalidation=invalidation)
    with pytest.raises(InvalidDomainValueError, match="was invalidated"):
        await invalidated.authorize(
            request(), proposed, evaluated_input, decision, principal=operator()
        )


@pytest.mark.anyio
async def test_preflight_rejects_changed_proposal_policy_input_or_decision() -> None:
    proposed, evaluated_input, decision, approved = authority_values()
    service, _, _ = preflight(approved)

    changed_proposal = proposal(
        risk_assumptions=("The deployment may not be the only contributing factor.",)
    )
    with pytest.raises(InvalidDomainValueError, match="proposal does not match"):
        await service.authorize(
            request(), changed_proposal, evaluated_input, decision, principal=operator()
        )

    changed_input = replace(
        evaluated_input,
        maintenance_window=MaintenanceWindowStatus.INACTIVE,
    )
    with pytest.raises(InvalidDomainValueError, match="Policy input does not match"):
        await service.authorize(request(), proposed, changed_input, decision, principal=operator())

    changed_decision = replace(decision, id=OpaqueIdentifier("policy-substituted"))
    with pytest.raises(InvalidDomainValueError, match="Policy decision does not match"):
        await service.authorize(
            request(), proposed, evaluated_input, changed_decision, principal=operator()
        )


@pytest.mark.anyio
async def test_preflight_rechecks_evidence_policy_and_current_version() -> None:
    proposed, evaluated_input, decision, approved = authority_values()

    no_gate = RollbackExecutionPreflight(
        IncidentStore(incident()),
        ApprovalStore(approved),
        RemediationEvidenceGate(GateStore(None)),
        VersionStore(SemanticVersion("2.0.0")),
        RollbackTargetCatalog((managed_target(),)),
        policy_rules(),
        clock=lambda: NOW + timedelta(minutes=4),
    )
    with pytest.raises(InvalidDomainValueError, match="stored passing"):
        await no_gate.authorize(
            request(), proposed, evaluated_input, decision, principal=operator()
        )

    changed_rules = policy_rules(allowed_services=frozenset())
    denied, _, _ = preflight(approved, rules=changed_rules)
    with pytest.raises(InvalidDomainValueError, match="no longer reproducible"):
        await denied.authorize(request(), proposed, evaluated_input, decision, principal=operator())

    unavailable, _, _ = preflight(approved, current_version=None)
    with pytest.raises(InvalidDomainValueError, match="version is unavailable"):
        await unavailable.authorize(
            request(), proposed, evaluated_input, decision, principal=operator()
        )

    already_stable, _, _ = preflight(
        approved,
        current_version=SemanticVersion("1.0.0"),
    )
    with pytest.raises(InvalidDomainValueError, match="already at the stable"):
        await already_stable.authorize(
            request(), proposed, evaluated_input, decision, principal=operator()
        )
