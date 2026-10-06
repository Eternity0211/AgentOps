"""Versioned deterministic Policy Engine contract tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import pytest

from agentops_incident_commander.domain import (
    MAX_APPROVAL_TTL,
    MAX_POLICY_REASON_DETAIL,
    MAX_POLICY_REASONS,
    MIN_APPROVAL_TTL,
    POLICY_DECISION_SCHEMA_VERSION,
    POLICY_INPUT_SCHEMA_VERSION,
    ActorId,
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
    Sha256Digest,
    TenantId,
)

NOW = datetime(2026, 10, 6, 13, 0, tzinfo=UTC)


def policy_input(**overrides: Any) -> PolicyEvaluationInput:
    values: dict[str, Any] = {
        "tenant_id": TenantId("tenant-policy"),
        "incident_id": IncidentId("incident-policy"),
        "proposal_id": OpaqueIdentifier("remediation-1"),
        "proposal_version": 1,
        "proposal_fingerprint": Sha256Digest("a" * 64),
        "evidence_gate_decision_fingerprint": Sha256Digest("b" * 64),
        "requester_actor_id": ActorId("operator-policy"),
        "requester_roles": frozenset({Role.OPERATOR}),
        "environment": PolicyEnvironment.PRODUCTION,
        "action": PolicyAction.ROLLBACK_SERVICE,
        "service": " orders ",
        "blast_radius": PolicyBlastRadius.SINGLE_SERVICE,
        "maintenance_window": MaintenanceWindowStatus.ACTIVE,
        "separation_of_duties_required": True,
        "requested_at": NOW,
    }
    values.update(overrides)
    return PolicyEvaluationInput(**values)


def reason(
    code: PolicyReasonCode = PolicyReasonCode.APPROVAL_REQUIRED,
    detail: str = "Human approval is required for production rollback.",
) -> PolicyReason:
    return PolicyReason(code, detail)


def decision(**overrides: Any) -> PolicyDecision:
    values: dict[str, Any] = {
        "id": OpaqueIdentifier("policy-decision-1"),
        "policy_version": SemanticVersion("1.0.0"),
        "input_fingerprint": policy_input().fingerprint,
        "proposal_fingerprint": Sha256Digest("a" * 64),
        "outcome": PolicyOutcome.APPROVAL_REQUIRED,
        "risk_level": RiskLevel.HIGH,
        "reasons": (reason(),),
        "evaluated_at": NOW,
        "approval_ttl": timedelta(minutes=30),
    }
    values.update(overrides)
    return PolicyDecision(**values)


def test_policy_input_is_complete_normalized_immutable_and_hash_bound() -> None:
    value = policy_input()
    assert value.schema_version == POLICY_INPUT_SCHEMA_VERSION
    assert value.service == "orders"
    assert value.requester_roles == frozenset({Role.OPERATOR})
    assert len(value.fingerprint.value) == 64
    shifted = policy_input(requested_at=NOW.astimezone(timezone(timedelta(hours=8))))
    assert shifted.requested_at == NOW
    assert shifted.fingerprint == value.fingerprint
    with pytest.raises(FrozenInstanceError):
        value.service = "inventory"  # type: ignore[misc]


def test_policy_input_fingerprint_changes_for_every_material_decision_dimension() -> None:
    original = policy_input()
    changed = (
        policy_input(proposal_version=2),
        policy_input(requester_roles=frozenset({Role.ADMIN})),
        policy_input(environment=PolicyEnvironment.STAGING),
        policy_input(service="inventory"),
        policy_input(blast_radius=PolicyBlastRadius.MULTI_SERVICE),
        policy_input(maintenance_window=MaintenanceWindowStatus.INACTIVE),
        policy_input(separation_of_duties_required=False),
    )
    assert len({original.fingerprint, *(item.fingerprint for item in changed)}) == 8


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant_id": "tenant"}, "types"),
        ({"incident_id": "incident"}, "types"),
        ({"proposal_id": "proposal"}, "types"),
        ({"proposal_fingerprint": "a" * 64}, "types"),
        ({"evidence_gate_decision_fingerprint": "b" * 64}, "types"),
        ({"requester_actor_id": "actor"}, "types"),
        ({"environment": "PRODUCTION"}, "types"),
        ({"action": "rollback_service"}, "types"),
        ({"blast_radius": "SINGLE_SERVICE"}, "types"),
        ({"maintenance_window": "ACTIVE"}, "types"),
        ({"proposal_version": True}, "proposal version"),
        ({"proposal_version": 0}, "proposal version"),
        ({"requester_roles": set()}, "requester roles"),
        ({"requester_roles": frozenset()}, "requester roles"),
        ({"requester_roles": frozenset({"OPERATOR"})}, "requester roles"),
        ({"service": "bad\nservice"}, "service"),
        ({"service": "x" * 129}, "service"),
        ({"separation_of_duties_required": 1}, "separation flag"),
        ({"schema_version": "2.0.0"}, "schema version"),
    ],
)
def test_policy_input_rejects_untyped_ambiguous_or_unbounded_values(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        policy_input(**overrides)


def test_policy_decision_is_versioned_immutable_bounded_and_fingerprinted() -> None:
    value = decision()
    assert value.schema_version == POLICY_DECISION_SCHEMA_VERSION
    assert value.risk_level is RiskLevel.HIGH
    assert value.approval_ttl == timedelta(minutes=30)
    assert len(value.fingerprint.value) == 64
    shifted = decision(evaluated_at=NOW.astimezone(timezone(timedelta(hours=-4))))
    assert shifted.evaluated_at == NOW
    assert shifted.fingerprint == value.fingerprint
    with pytest.raises(FrozenInstanceError):
        value.outcome = PolicyOutcome.DENY  # type: ignore[misc]


def test_policy_outcomes_require_consistent_reasons_and_approval_lifetime() -> None:
    allowed = decision(
        outcome=PolicyOutcome.ALLOW,
        risk_level=RiskLevel.LOW,
        reasons=(reason(PolicyReasonCode.POLICY_SATISFIED, "All rules passed."),),
        approval_ttl=None,
    )
    denied = decision(
        outcome=PolicyOutcome.DENY,
        reasons=(reason(PolicyReasonCode.ENVIRONMENT_DENIED, "Environment is denied."),),
        approval_ttl=None,
    )
    assert allowed.outcome is PolicyOutcome.ALLOW
    assert denied.outcome is PolicyOutcome.DENY
    invalid = (
        {"outcome": PolicyOutcome.ALLOW, "reasons": (reason(),), "approval_ttl": None},
        {
            "outcome": PolicyOutcome.APPROVAL_REQUIRED,
            "reasons": (reason(PolicyReasonCode.ROLE_DENIED, "Role denied."),),
        },
        {
            "outcome": PolicyOutcome.DENY,
            "reasons": (reason(PolicyReasonCode.POLICY_SATISFIED, "Conflict."),),
            "approval_ttl": None,
        },
        {"approval_ttl": None},
        {"approval_ttl": MIN_APPROVAL_TTL - timedelta(seconds=1)},
        {"approval_ttl": MAX_APPROVAL_TTL + timedelta(seconds=1)},
        {
            "outcome": PolicyOutcome.DENY,
            "reasons": (reason(PolicyReasonCode.ROLE_DENIED, "Role denied."),),
            "approval_ttl": timedelta(minutes=5),
        },
    )
    for overrides in invalid:
        with pytest.raises(InvalidDomainValueError):
            decision(**overrides)


def test_policy_reasons_and_decision_types_are_strict_unique_and_bounded() -> None:
    assert reason(detail=" bounded ").detail == "bounded"
    for code, detail in (("ROLE_DENIED", "denied"), (PolicyReasonCode.ROLE_DENIED, "")):
        with pytest.raises(InvalidDomainValueError):
            PolicyReason(cast(Any, code), detail)
    with pytest.raises(InvalidDomainValueError, match="reason"):
        reason(detail="x" * (MAX_POLICY_REASON_DETAIL + 1))

    valid = reason()
    invalid_reasons: tuple[Any, ...] = (
        (),
        (valid, valid),
        tuple(
            reason(PolicyReasonCode.APPROVAL_REQUIRED, f"reason-{index}")
            for index in range(MAX_POLICY_REASONS + 1)
        ),
        ("bad",),
    )
    for reasons in invalid_reasons:
        with pytest.raises(InvalidDomainValueError, match="unique and bounded"):
            decision(reasons=reasons)

    type_overrides = (
        {"id": "decision"},
        {"policy_version": "1.0.0"},
        {"input_fingerprint": "c" * 64},
        {"proposal_fingerprint": "a" * 64},
        {"outcome": "APPROVAL_REQUIRED"},
        {"risk_level": "HIGH"},
    )
    for overrides in type_overrides:
        with pytest.raises(InvalidDomainValueError, match="types"):
            decision(**overrides)
    with pytest.raises(InvalidDomainValueError, match="schema version"):
        decision(schema_version="2.0.0")


def test_policy_decision_fingerprint_changes_with_result() -> None:
    original = decision()
    changed = replace(original, risk_level=RiskLevel.CRITICAL)
    assert changed.fingerprint != original.fingerprint
