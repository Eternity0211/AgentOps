"""Versioned deterministic Policy Engine input and decision contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .auth import Role
from .errors import InvalidDomainValueError
from .tools import SemanticVersion
from .values import (
    ActorId,
    IncidentId,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    as_utc,
)

POLICY_INPUT_SCHEMA_VERSION = "1.0.0"
POLICY_DECISION_SCHEMA_VERSION = "1.0.0"
MAX_POLICY_REASONS = 16
MAX_POLICY_REASON_DETAIL = 256
MAX_APPROVAL_TTL = timedelta(hours=24)
MIN_APPROVAL_TTL = timedelta(minutes=1)


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PolicyEnvironment(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"


class PolicyAction(StrEnum):
    ROLLBACK_SERVICE = "rollback_service"


class PolicyBlastRadius(StrEnum):
    SINGLE_INSTANCE = "SINGLE_INSTANCE"
    SINGLE_SERVICE = "SINGLE_SERVICE"
    MULTI_SERVICE = "MULTI_SERVICE"


class MaintenanceWindowStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    NOT_REQUIRED = "NOT_REQUIRED"


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class PolicyReasonCode(StrEnum):
    POLICY_SATISFIED = "POLICY_SATISFIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ENVIRONMENT_DENIED = "ENVIRONMENT_DENIED"
    ROLE_DENIED = "ROLE_DENIED"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    TARGET_NOT_ALLOWED = "TARGET_NOT_ALLOWED"
    EVIDENCE_GATE_INVALID = "EVIDENCE_GATE_INVALID"
    BLAST_RADIUS_EXCEEDED = "BLAST_RADIUS_EXCEEDED"
    MAINTENANCE_WINDOW_REQUIRED = "MAINTENANCE_WINDOW_REQUIRED"
    SEPARATION_OF_DUTIES_REQUIRED = "SEPARATION_OF_DUTIES_REQUIRED"


@dataclass(frozen=True, slots=True)
class PolicyEvaluationInput:
    tenant_id: TenantId
    incident_id: IncidentId
    proposal_id: OpaqueIdentifier
    proposal_version: int
    proposal_fingerprint: Sha256Digest
    evidence_gate_decision_fingerprint: Sha256Digest
    requester_actor_id: ActorId
    requester_roles: frozenset[Role]
    environment: PolicyEnvironment
    action: PolicyAction
    service: str
    blast_radius: PolicyBlastRadius
    maintenance_window: MaintenanceWindowStatus
    separation_of_duties_required: bool
    requested_at: datetime
    schema_version: str = POLICY_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.tenant_id, TenantId),
            (self.incident_id, IncidentId),
            (self.proposal_id, OpaqueIdentifier),
            (self.proposal_fingerprint, Sha256Digest),
            (self.evidence_gate_decision_fingerprint, Sha256Digest),
            (self.requester_actor_id, ActorId),
            (self.environment, PolicyEnvironment),
            (self.action, PolicyAction),
            (self.blast_radius, PolicyBlastRadius),
            (self.maintenance_window, MaintenanceWindowStatus),
        )
        if any(not isinstance(value, kind) for value, kind in expected):
            raise InvalidDomainValueError("Policy Engine input types are invalid")
        if (
            not isinstance(self.proposal_version, int)
            or isinstance(self.proposal_version, bool)
            or self.proposal_version < 1
        ):
            raise InvalidDomainValueError("Policy Engine proposal version is invalid")
        if (
            not isinstance(self.requester_roles, frozenset)
            or not self.requester_roles
            or any(not isinstance(role, Role) for role in self.requester_roles)
        ):
            raise InvalidDomainValueError("Policy Engine requester roles are invalid")
        normalized_service = _bounded_text(self.service, field="service", maximum=128)
        if not isinstance(self.separation_of_duties_required, bool):
            raise InvalidDomainValueError("Policy Engine separation flag is invalid")
        if self.schema_version != POLICY_INPUT_SCHEMA_VERSION:
            raise InvalidDomainValueError("Policy Engine input schema version is unsupported")
        object.__setattr__(self, "service", normalized_service)
        object.__setattr__(self, "requested_at", as_utc(self.requested_at))

    @property
    def fingerprint(self) -> Sha256Digest:
        document = {
            "action": self.action.value,
            "blast_radius": self.blast_radius.value,
            "environment": self.environment.value,
            "evidence_gate_decision_fingerprint": (self.evidence_gate_decision_fingerprint.value),
            "incident_id": self.incident_id.value,
            "maintenance_window": self.maintenance_window.value,
            "proposal_fingerprint": self.proposal_fingerprint.value,
            "proposal_id": self.proposal_id.value,
            "proposal_version": self.proposal_version,
            "requested_at": self.requested_at.isoformat(),
            "requester_actor_id": self.requester_actor_id.value,
            "requester_roles": sorted(role.value for role in self.requester_roles),
            "schema_version": self.schema_version,
            "separation_of_duties_required": self.separation_of_duties_required,
            "service": self.service,
            "tenant_id": self.tenant_id.value,
        }
        return _fingerprint(document)


@dataclass(frozen=True, slots=True)
class PolicyReason:
    code: PolicyReasonCode
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, PolicyReasonCode):
            raise InvalidDomainValueError("Policy Engine reason code is invalid")
        object.__setattr__(
            self,
            "detail",
            _bounded_text(self.detail, field="reason", maximum=MAX_POLICY_REASON_DETAIL),
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    id: OpaqueIdentifier
    policy_version: SemanticVersion
    input_fingerprint: Sha256Digest
    proposal_fingerprint: Sha256Digest
    outcome: PolicyOutcome
    risk_level: RiskLevel
    reasons: tuple[PolicyReason, ...]
    evaluated_at: datetime
    approval_ttl: timedelta | None = None
    schema_version: str = POLICY_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.id, OpaqueIdentifier),
            (self.policy_version, SemanticVersion),
            (self.input_fingerprint, Sha256Digest),
            (self.proposal_fingerprint, Sha256Digest),
            (self.outcome, PolicyOutcome),
            (self.risk_level, RiskLevel),
        )
        if any(not isinstance(value, kind) for value, kind in expected):
            raise InvalidDomainValueError("Policy Engine decision types are invalid")
        if (
            not isinstance(self.reasons, tuple)
            or not self.reasons
            or len(self.reasons) > MAX_POLICY_REASONS
            or any(not isinstance(reason, PolicyReason) for reason in self.reasons)
            or len(set(self.reasons)) != len(self.reasons)
        ):
            raise InvalidDomainValueError("Policy Engine reasons must be unique and bounded")
        reason_codes = {reason.code for reason in self.reasons}
        if self.outcome is PolicyOutcome.ALLOW and reason_codes != {
            PolicyReasonCode.POLICY_SATISFIED
        }:
            raise InvalidDomainValueError("allowed Policy decisions require a satisfied reason")
        if self.outcome is PolicyOutcome.APPROVAL_REQUIRED and (
            PolicyReasonCode.APPROVAL_REQUIRED not in reason_codes
        ):
            raise InvalidDomainValueError(
                "approval-required Policy decisions require an approval reason"
            )
        if self.outcome is PolicyOutcome.DENY and reason_codes & {
            PolicyReasonCode.POLICY_SATISFIED,
            PolicyReasonCode.APPROVAL_REQUIRED,
        }:
            raise InvalidDomainValueError("denied Policy decisions contain conflicting reasons")
        requires_approval = self.outcome is PolicyOutcome.APPROVAL_REQUIRED
        valid_ttl = isinstance(self.approval_ttl, timedelta) and (
            MIN_APPROVAL_TTL <= self.approval_ttl <= MAX_APPROVAL_TTL
        )
        if requires_approval != valid_ttl:
            raise InvalidDomainValueError(
                "Policy approval lifetime must match an approval-required outcome"
            )
        if self.schema_version != POLICY_DECISION_SCHEMA_VERSION:
            raise InvalidDomainValueError("Policy Engine decision schema version is unsupported")
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))

    @property
    def fingerprint(self) -> Sha256Digest:
        document = {
            "approval_ttl_seconds": (
                None if self.approval_ttl is None else int(self.approval_ttl.total_seconds())
            ),
            "evaluated_at": self.evaluated_at.isoformat(),
            "id": self.id.value,
            "input_fingerprint": self.input_fingerprint.value,
            "outcome": self.outcome.value,
            "policy_version": self.policy_version.value,
            "proposal_fingerprint": self.proposal_fingerprint.value,
            "reasons": [
                {"code": reason.code.value, "detail": reason.detail} for reason in self.reasons
            ],
            "risk_level": self.risk_level.value,
            "schema_version": self.schema_version,
        }
        return _fingerprint(document)


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or any(ord(character) < 32 for character in value):
        raise InvalidDomainValueError(f"Policy Engine {field} is invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise InvalidDomainValueError(f"Policy Engine {field} is invalid")
    return normalized


def _fingerprint(document: object) -> Sha256Digest:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return Sha256Digest(hashlib.sha256(canonical).hexdigest())
