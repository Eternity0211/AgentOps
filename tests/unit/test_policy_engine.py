"""Deterministic remediation Policy Engine rule tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    MAX_POLICY_SERVICES,
    EvidenceBoundRemediationProposal,
    PolicyRules,
    evaluate_remediation_policy,
    evidence_gate_decision_fingerprint,
)
from agentops_incident_commander.domain import (
    ActorId,
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
    PolicyEvaluationInput,
    PolicyOutcome,
    PolicyReasonCode,
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

NOW = datetime(2026, 10, 6, 14, 0, tzinfo=UTC)
TENANT = TenantId("tenant-policy-engine")
INCIDENT = IncidentId("incident-policy-engine")


def admitted_proposal() -> EvidenceBoundRemediationProposal:
    decision = EvidenceGateDecision(
        incident_id=INCIDENT,
        candidate_id="candidate-deployment",
        outcome=EvidenceGateOutcome.PASS,
        reasons=(),
        evaluated_evidence_ids=(
            EvidenceId("evidence-deployment"),
            EvidenceId("evidence-current-version"),
        ),
        rules_version="1.1.0",
        input_fingerprint=Sha256Digest("a" * 64),
        evaluated_at=NOW,
        model_confidence_basis_points=9_000,
    )
    proposal = RemediationProposal(
        schema_version=REMEDIATION_PROPOSAL_SCHEMA_VERSION,
        proposal_id="remediation-1",
        proposal_version=1,
        incident_id=INCIDENT.value,
        candidate_id=decision.candidate_id,
        evidence_gate_input_fingerprint=decision.input_fingerprint.value,
        evidence_gate_decision_fingerprint=evidence_gate_decision_fingerprint(decision).value,
        action=RecoveryAction.ROLLBACK_SERVICE,
        parameters=RollbackServiceParameters(
            service="orders",
            introducing_deployment_evidence_id="evidence-deployment",
        ),
        prerequisites=RollbackPrerequisites(current_version_evidence_id="evidence-current-version"),
        verification_conditions=RollbackVerificationConditions(
            max_error_rate_basis_points=100,
            max_p95_latency_ms=500,
            stability_window_seconds=300,
        ),
        failure_handling=RemediationFailureHandling(
            route=RemediationFailureRoute.HUMAN_HANDOFF,
            max_rediagnosis_attempts=0,
        ),
        risk_assumptions=("The deployment evidence identifies the faulty version.",),
    )
    return EvidenceBoundRemediationProposal(TENANT, proposal, decision)


def policy_input(
    admitted: EvidenceBoundRemediationProposal,
    **overrides: Any,
) -> PolicyEvaluationInput:
    proposal = admitted.proposal
    values: dict[str, Any] = {
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "proposal_id": OpaqueIdentifier(proposal.proposal_id),
        "proposal_version": proposal.proposal_version,
        "proposal_fingerprint": proposal.fingerprint,
        "evidence_gate_decision_fingerprint": evidence_gate_decision_fingerprint(
            admitted.evidence_gate_decision
        ),
        "requester_actor_id": ActorId("operator-policy"),
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


def rules(**overrides: Any) -> PolicyRules:
    values: dict[str, Any] = {
        "version": SemanticVersion("1.0.0"),
        "allowed_environments": frozenset(PolicyEnvironment),
        "allowed_requester_roles": frozenset({Role.OPERATOR}),
        "allowed_actions": frozenset({PolicyAction.ROLLBACK_SERVICE}),
        "allowed_services": frozenset({"orders"}),
        "allowed_blast_radii": frozenset(
            {PolicyBlastRadius.SINGLE_INSTANCE, PolicyBlastRadius.SINGLE_SERVICE}
        ),
        "require_active_maintenance_window": True,
        "require_separation_of_duties": True,
        "approval_ttl": timedelta(minutes=30),
    }
    values.update(overrides)
    return PolicyRules(**values)


def evaluate(
    value: PolicyEvaluationInput,
    admitted: EvidenceBoundRemediationProposal,
    selected_rules: PolicyRules,
) -> PolicyDecision:
    return evaluate_remediation_policy(
        value,
        admitted,
        rules=selected_rules,
        decision_id=OpaqueIdentifier("policy-decision-1"),
        evaluated_at=NOW,
    )


def test_valid_rollback_requires_approval_and_never_directly_allows_execution() -> None:
    admitted = admitted_proposal()
    value = policy_input(admitted)
    result = evaluate(value, admitted, rules())
    assert result.outcome is PolicyOutcome.APPROVAL_REQUIRED
    assert result.risk_level is RiskLevel.HIGH
    assert result.approval_ttl == timedelta(minutes=30)
    assert result.input_fingerprint == value.fingerprint
    assert result.proposal_fingerprint == admitted.proposal.fingerprint
    assert [reason.code for reason in result.reasons] == [PolicyReasonCode.APPROVAL_REQUIRED]


@pytest.mark.parametrize(
    ("environment", "blast_radius", "expected"),
    [
        (PolicyEnvironment.DEVELOPMENT, PolicyBlastRadius.SINGLE_SERVICE, RiskLevel.LOW),
        (PolicyEnvironment.STAGING, PolicyBlastRadius.SINGLE_SERVICE, RiskLevel.MEDIUM),
        (PolicyEnvironment.PRODUCTION, PolicyBlastRadius.SINGLE_SERVICE, RiskLevel.HIGH),
        (PolicyEnvironment.DEVELOPMENT, PolicyBlastRadius.MULTI_SERVICE, RiskLevel.CRITICAL),
    ],
)
def test_risk_is_deterministic_from_environment_and_blast_radius(
    environment: PolicyEnvironment,
    blast_radius: PolicyBlastRadius,
    expected: RiskLevel,
) -> None:
    admitted = admitted_proposal()
    value = policy_input(admitted, environment=environment, blast_radius=blast_radius)
    selected = rules(allowed_blast_radii=frozenset(PolicyBlastRadius))
    assert evaluate(value, admitted, selected).risk_level is expected


@pytest.mark.parametrize(
    ("input_overrides", "rule_overrides", "admission_change", "expected"),
    [
        ({}, {"allowed_environments": frozenset()}, None, PolicyReasonCode.ENVIRONMENT_DENIED),
        ({}, {"allowed_requester_roles": frozenset()}, None, PolicyReasonCode.ROLE_DENIED),
        ({}, {"allowed_actions": frozenset()}, None, PolicyReasonCode.ACTION_NOT_ALLOWED),
        (
            {"service": "billing"},
            {"allowed_services": frozenset({"orders", "billing"})},
            None,
            PolicyReasonCode.TARGET_NOT_ALLOWED,
        ),
        ({}, {}, "tenant", PolicyReasonCode.EVIDENCE_GATE_INVALID),
        (
            {"blast_radius": PolicyBlastRadius.MULTI_SERVICE},
            {},
            None,
            PolicyReasonCode.BLAST_RADIUS_EXCEEDED,
        ),
        (
            {"maintenance_window": MaintenanceWindowStatus.INACTIVE},
            {},
            None,
            PolicyReasonCode.MAINTENANCE_WINDOW_REQUIRED,
        ),
        (
            {"separation_of_duties_required": False},
            {},
            None,
            PolicyReasonCode.SEPARATION_OF_DUTIES_REQUIRED,
        ),
    ],
)
def test_each_rule_fails_closed_with_one_structured_reason(
    input_overrides: dict[str, object],
    rule_overrides: dict[str, object],
    admission_change: str | None,
    expected: PolicyReasonCode,
) -> None:
    admitted = admitted_proposal()
    value = policy_input(admitted, **input_overrides)
    checked = (
        replace(admitted, tenant_id=TenantId("tenant-other"))
        if admission_change == "tenant"
        else admitted
    )
    result = evaluate(value, checked, rules(**rule_overrides))
    assert result.outcome is PolicyOutcome.DENY
    assert result.approval_ttl is None
    assert [reason.code for reason in result.reasons] == [expected]


def test_multiple_failures_are_complete_and_stably_ordered() -> None:
    admitted = admitted_proposal()
    value = policy_input(
        admitted,
        blast_radius=PolicyBlastRadius.MULTI_SERVICE,
        maintenance_window=MaintenanceWindowStatus.INACTIVE,
        separation_of_duties_required=False,
    )
    mismatched = replace(admitted, tenant_id=TenantId("tenant-other"))
    deny_all = rules(
        allowed_environments=frozenset(),
        allowed_requester_roles=frozenset(),
        allowed_actions=frozenset(),
        allowed_services=frozenset(),
        allowed_blast_radii=frozenset(),
    )
    result = evaluate(value, mismatched, deny_all)
    assert [reason.code for reason in result.reasons] == [
        PolicyReasonCode.ENVIRONMENT_DENIED,
        PolicyReasonCode.ROLE_DENIED,
        PolicyReasonCode.ACTION_NOT_ALLOWED,
        PolicyReasonCode.TARGET_NOT_ALLOWED,
        PolicyReasonCode.EVIDENCE_GATE_INVALID,
        PolicyReasonCode.BLAST_RADIUS_EXCEEDED,
        PolicyReasonCode.MAINTENANCE_WINDOW_REQUIRED,
        PolicyReasonCode.SEPARATION_OF_DUTIES_REQUIRED,
    ]


def test_optional_constraints_can_be_disabled_without_bypassing_approval() -> None:
    admitted = admitted_proposal()
    value = policy_input(
        admitted,
        maintenance_window=MaintenanceWindowStatus.NOT_REQUIRED,
        separation_of_duties_required=False,
    )
    selected = rules(
        require_active_maintenance_window=False,
        require_separation_of_duties=False,
    )
    assert evaluate(value, admitted, selected).outcome is PolicyOutcome.APPROVAL_REQUIRED


def test_rules_are_strict_bounded_and_immutable() -> None:
    selected = rules()
    with pytest.raises(FrozenInstanceError):
        selected.approval_ttl = timedelta(hours=1)  # type: ignore[misc]
    invalid: tuple[dict[str, object], ...] = (
        {"version": "1.0.0"},
        {"allowed_environments": {PolicyEnvironment.PRODUCTION}},
        {"allowed_requester_roles": frozenset({"OPERATOR"})},
        {"allowed_actions": frozenset({"rollback_service"})},
        {"allowed_blast_radii": frozenset({"SINGLE_SERVICE"})},
        {"allowed_services": frozenset({" orders"})},
        {
            "allowed_services": frozenset(
                f"service-{index}" for index in range(MAX_POLICY_SERVICES + 1)
            )
        },
        {"require_active_maintenance_window": 1},
        {"require_separation_of_duties": 1},
        {"approval_ttl": timedelta(seconds=59)},
        {"approval_ttl": timedelta(hours=24, seconds=1)},
    )
    for override in invalid:
        with pytest.raises(InvalidDomainValueError):
            rules(**override)


def test_invalid_evaluation_types_fail_before_policy_processing() -> None:
    admitted = admitted_proposal()
    value = policy_input(admitted)
    with pytest.raises(InvalidDomainValueError, match="arguments"):
        evaluate_remediation_policy(
            cast(PolicyEvaluationInput, object()),
            admitted,
            rules=rules(),
            decision_id=OpaqueIdentifier("policy-decision-1"),
            evaluated_at=NOW,
        )
    with pytest.raises(InvalidDomainValueError, match="arguments"):
        evaluate_remediation_policy(
            value,
            admitted,
            rules=rules(),
            decision_id=OpaqueIdentifier("policy-decision-1"),
            evaluated_at=cast(datetime, "not-a-date"),
        )
