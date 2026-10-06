"""Deterministic remediation Policy Engine rules and evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from agentops_incident_commander.domain import (
    MAX_APPROVAL_TTL,
    MIN_APPROVAL_TTL,
    EvidenceGateOutcome,
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
    RiskLevel,
    Role,
    SemanticVersion,
)

from .evidence_gate import evidence_gate_decision_fingerprint
from .remediation_gate import EvidenceBoundRemediationProposal

MAX_POLICY_SERVICES = 128


@dataclass(frozen=True, slots=True)
class PolicyRules:
    """Server-owned ruleset; empty allowlists provide an explicit kill switch."""

    version: SemanticVersion
    allowed_environments: frozenset[PolicyEnvironment]
    allowed_requester_roles: frozenset[Role]
    allowed_actions: frozenset[PolicyAction]
    allowed_services: frozenset[str]
    allowed_blast_radii: frozenset[PolicyBlastRadius]
    require_active_maintenance_window: bool
    require_separation_of_duties: bool
    approval_ttl: timedelta

    def __post_init__(self) -> None:
        collections = (
            (self.allowed_environments, PolicyEnvironment),
            (self.allowed_requester_roles, Role),
            (self.allowed_actions, PolicyAction),
            (self.allowed_blast_radii, PolicyBlastRadius),
        )
        if not isinstance(self.version, SemanticVersion) or any(
            not isinstance(values, frozenset)
            or any(not isinstance(value, expected) for value in values)
            for values, expected in collections
        ):
            raise InvalidDomainValueError("Policy Engine ruleset types are invalid")
        if (
            not isinstance(self.allowed_services, frozenset)
            or len(self.allowed_services) > MAX_POLICY_SERVICES
            or any(not _is_normalized_service(service) for service in self.allowed_services)
        ):
            raise InvalidDomainValueError("Policy Engine service allowlist is invalid")
        if not isinstance(self.require_active_maintenance_window, bool) or not isinstance(
            self.require_separation_of_duties, bool
        ):
            raise InvalidDomainValueError("Policy Engine rule switches are invalid")
        if not isinstance(self.approval_ttl, timedelta) or not (
            MIN_APPROVAL_TTL <= self.approval_ttl <= MAX_APPROVAL_TTL
        ):
            raise InvalidDomainValueError("Policy Engine approval lifetime is invalid")


def evaluate_remediation_policy(
    policy_input: PolicyEvaluationInput,
    admitted: EvidenceBoundRemediationProposal,
    *,
    rules: PolicyRules,
    decision_id: OpaqueIdentifier,
    evaluated_at: datetime,
) -> PolicyDecision:
    """Evaluate every rule in stable order and never authorize execution directly."""

    if (
        not isinstance(policy_input, PolicyEvaluationInput)
        or not isinstance(admitted, EvidenceBoundRemediationProposal)
        or not isinstance(rules, PolicyRules)
        or not isinstance(decision_id, OpaqueIdentifier)
        or not isinstance(evaluated_at, datetime)
    ):
        raise InvalidDomainValueError("Policy Engine evaluation arguments are invalid")

    proposal = admitted.proposal
    reasons: list[PolicyReason] = []
    if policy_input.environment not in rules.allowed_environments:
        reasons.append(_reason(PolicyReasonCode.ENVIRONMENT_DENIED))
    if not policy_input.requester_roles.intersection(rules.allowed_requester_roles):
        reasons.append(_reason(PolicyReasonCode.ROLE_DENIED))
    if not _action_is_allowed(policy_input.action, rules.allowed_actions):
        reasons.append(_reason(PolicyReasonCode.ACTION_NOT_ALLOWED))
    if (
        policy_input.service not in rules.allowed_services
        or policy_input.service != proposal.parameters.service
        or policy_input.action.value != proposal.action.value
    ):
        reasons.append(_reason(PolicyReasonCode.TARGET_NOT_ALLOWED))
    if not _has_exact_evidence_binding(policy_input, admitted):
        reasons.append(_reason(PolicyReasonCode.EVIDENCE_GATE_INVALID))
    if policy_input.blast_radius not in rules.allowed_blast_radii:
        reasons.append(_reason(PolicyReasonCode.BLAST_RADIUS_EXCEEDED))
    if (
        rules.require_active_maintenance_window
        and policy_input.maintenance_window is not MaintenanceWindowStatus.ACTIVE
    ):
        reasons.append(_reason(PolicyReasonCode.MAINTENANCE_WINDOW_REQUIRED))
    if rules.require_separation_of_duties and not policy_input.separation_of_duties_required:
        reasons.append(_reason(PolicyReasonCode.SEPARATION_OF_DUTIES_REQUIRED))

    risk = _risk_level(policy_input)
    if reasons:
        return PolicyDecision(
            id=decision_id,
            policy_version=rules.version,
            input_fingerprint=policy_input.fingerprint,
            proposal_fingerprint=proposal.fingerprint,
            outcome=PolicyOutcome.DENY,
            risk_level=risk,
            reasons=tuple(reasons),
            evaluated_at=evaluated_at,
        )
    return PolicyDecision(
        id=decision_id,
        policy_version=rules.version,
        input_fingerprint=policy_input.fingerprint,
        proposal_fingerprint=proposal.fingerprint,
        outcome=PolicyOutcome.APPROVAL_REQUIRED,
        risk_level=risk,
        reasons=(_reason(PolicyReasonCode.APPROVAL_REQUIRED),),
        evaluated_at=evaluated_at,
        approval_ttl=rules.approval_ttl,
    )


def _has_exact_evidence_binding(
    policy_input: PolicyEvaluationInput,
    admitted: EvidenceBoundRemediationProposal,
) -> bool:
    proposal = admitted.proposal
    decision = admitted.evidence_gate_decision
    return (
        admitted.tenant_id == policy_input.tenant_id
        and proposal.incident_id == policy_input.incident_id.value
        and proposal.proposal_id == policy_input.proposal_id.value
        and proposal.proposal_version == policy_input.proposal_version
        and proposal.fingerprint == policy_input.proposal_fingerprint
        and proposal.evidence_gate_input_fingerprint == decision.input_fingerprint.value
        and proposal.candidate_id == decision.candidate_id
        and IncidentId(proposal.incident_id) == decision.incident_id
        and decision.outcome is EvidenceGateOutcome.PASS
        and evidence_gate_decision_fingerprint(decision)
        == policy_input.evidence_gate_decision_fingerprint
        and proposal.evidence_gate_decision_fingerprint
        == policy_input.evidence_gate_decision_fingerprint.value
    )


def _risk_level(policy_input: PolicyEvaluationInput) -> RiskLevel:
    if policy_input.blast_radius is PolicyBlastRadius.MULTI_SERVICE:
        return RiskLevel.CRITICAL
    if policy_input.environment is PolicyEnvironment.PRODUCTION:
        return RiskLevel.HIGH
    if policy_input.environment is PolicyEnvironment.STAGING:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _action_is_allowed(action: object, allowed: frozenset[PolicyAction]) -> bool:
    """Keep the server-side action kill switch explicit despite the closed MVP enum."""

    return action in allowed


_REASON_DETAILS = {
    PolicyReasonCode.APPROVAL_REQUIRED: "Human approval is required before rollback execution.",
    PolicyReasonCode.ENVIRONMENT_DENIED: "The target environment is not allowed by policy.",
    PolicyReasonCode.ROLE_DENIED: "The requester role is not allowed to request remediation.",
    PolicyReasonCode.ACTION_NOT_ALLOWED: "The remediation action is not allowed by policy.",
    PolicyReasonCode.TARGET_NOT_ALLOWED: "The service target or proposal binding is not allowed.",
    PolicyReasonCode.EVIDENCE_GATE_INVALID: "The passing Evidence Gate binding is invalid.",
    PolicyReasonCode.BLAST_RADIUS_EXCEEDED: "The requested blast radius exceeds policy.",
    PolicyReasonCode.MAINTENANCE_WINDOW_REQUIRED: "An active maintenance window is required.",
    PolicyReasonCode.SEPARATION_OF_DUTIES_REQUIRED: "Separation of duties is required.",
}


def _reason(code: PolicyReasonCode) -> PolicyReason:
    return PolicyReason(code, _REASON_DETAILS[code])


def _is_normalized_service(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= 128
        and all(ord(character) >= 32 for character in value)
    )
