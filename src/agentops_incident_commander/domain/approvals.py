"""Proposal-bound human Approval aggregate and finite lifecycle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .errors import InvalidDomainValueError
from .policy import RiskLevel
from .values import (
    ActorId,
    AggregateVersion,
    ApprovalId,
    EventReason,
    IncidentId,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    as_utc,
)

APPROVAL_SCHEMA_VERSION = "1.0.0"
APPROVAL_INVALIDATION_SCHEMA_VERSION = "1.0.0"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class Approval:
    id: ApprovalId
    tenant_id: TenantId
    incident_id: IncidentId
    proposal_id: OpaqueIdentifier
    proposal_version: int
    proposal_fingerprint: Sha256Digest
    policy_decision_id: OpaqueIdentifier
    policy_decision_fingerprint: Sha256Digest
    policy_input_fingerprint: Sha256Digest
    proposer_actor_id: ActorId
    risk_level: RiskLevel
    independent_approver_required: bool
    status: ApprovalStatus
    version: AggregateVersion
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    decided_by: ActorId | None = None
    decision_reason: EventReason | None = None
    schema_version: str = APPROVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.id, ApprovalId),
            (self.tenant_id, TenantId),
            (self.incident_id, IncidentId),
            (self.proposal_id, OpaqueIdentifier),
            (self.proposal_fingerprint, Sha256Digest),
            (self.policy_decision_id, OpaqueIdentifier),
            (self.policy_decision_fingerprint, Sha256Digest),
            (self.policy_input_fingerprint, Sha256Digest),
            (self.proposer_actor_id, ActorId),
            (self.risk_level, RiskLevel),
            (self.status, ApprovalStatus),
            (self.version, AggregateVersion),
            (self.requested_at, datetime),
            (self.expires_at, datetime),
        )
        if any(not isinstance(value, kind) for value, kind in expected):
            raise InvalidDomainValueError("Approval field types are invalid")
        if (
            not isinstance(self.proposal_version, int)
            or isinstance(self.proposal_version, bool)
            or self.proposal_version < 1
        ):
            raise InvalidDomainValueError("Approval proposal version is invalid")
        if not isinstance(self.independent_approver_required, bool):
            raise InvalidDomainValueError("Approval separation flag is invalid")
        if (
            (self.decided_at is not None and not isinstance(self.decided_at, datetime))
            or (self.decided_by is not None and not isinstance(self.decided_by, ActorId))
            or (
                self.decision_reason is not None
                and not isinstance(self.decision_reason, EventReason)
            )
        ):
            raise InvalidDomainValueError("Approval decision field types are invalid")
        requested_at = as_utc(self.requested_at)
        expires_at = as_utc(self.expires_at)
        decided_at = None if self.decided_at is None else as_utc(self.decided_at)
        if expires_at <= requested_at:
            raise InvalidDomainValueError("Approval expiry must follow its request time")
        terminal = self.status is not ApprovalStatus.PENDING
        decision_fields = (decided_at, self.decided_by, self.decision_reason)
        if terminal != all(value is not None for value in decision_fields):
            raise InvalidDomainValueError("Approval decision fields must match terminal status")
        if terminal and decided_at is not None:
            if decided_at < requested_at:
                raise InvalidDomainValueError("Approval decision cannot precede its request")
            if self.status is ApprovalStatus.EXPIRED and decided_at < expires_at:
                raise InvalidDomainValueError("Approval cannot expire before its deadline")
            if self.status is not ApprovalStatus.EXPIRED and decided_at >= expires_at:
                raise InvalidDomainValueError("Approval cannot be decided at or after expiry")
        if self.schema_version != APPROVAL_SCHEMA_VERSION:
            raise InvalidDomainValueError("Approval schema version is unsupported")
        object.__setattr__(self, "requested_at", requested_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "decided_at", decided_at)

    @property
    def fingerprint(self) -> Sha256Digest:
        document = {
            "decided_at": None if self.decided_at is None else self.decided_at.isoformat(),
            "decided_by": None if self.decided_by is None else self.decided_by.value,
            "decision_reason": (
                None if self.decision_reason is None else self.decision_reason.value
            ),
            "expires_at": self.expires_at.isoformat(),
            "id": self.id.value,
            "incident_id": self.incident_id.value,
            "independent_approver_required": self.independent_approver_required,
            "policy_decision_fingerprint": self.policy_decision_fingerprint.value,
            "policy_decision_id": self.policy_decision_id.value,
            "policy_input_fingerprint": self.policy_input_fingerprint.value,
            "proposal_fingerprint": self.proposal_fingerprint.value,
            "proposal_id": self.proposal_id.value,
            "proposal_version": self.proposal_version,
            "proposer_actor_id": self.proposer_actor_id.value,
            "requested_at": self.requested_at.isoformat(),
            "risk_level": self.risk_level.value,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "tenant_id": self.tenant_id.value,
            "version": self.version.value,
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(canonical).hexdigest())

    def decide(
        self,
        status: ApprovalStatus,
        *,
        actor_id: ActorId,
        reason: EventReason,
        at: datetime,
    ) -> Approval:
        if self.status is not ApprovalStatus.PENDING:
            raise InvalidDomainValueError("only a pending Approval can be decided")
        if status not in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
        }:
            raise InvalidDomainValueError("Approval terminal status is invalid")
        return replace(
            self,
            status=status,
            version=self.version.next(),
            decided_at=at,
            decided_by=actor_id,
            decision_reason=reason,
        )


@dataclass(frozen=True, slots=True)
class ApprovalInvalidation:
    approval_id: ApprovalId
    tenant_id: TenantId
    incident_id: IncidentId
    approval_fingerprint: Sha256Digest
    prior_proposal_fingerprint: Sha256Digest
    replacement_proposal_id: OpaqueIdentifier
    replacement_proposal_version: int
    replacement_proposal_fingerprint: Sha256Digest
    replacement_material_fingerprint: Sha256Digest
    invalidated_by: ActorId
    invalidated_at: datetime
    schema_version: str = APPROVAL_INVALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.approval_id, ApprovalId),
            (self.tenant_id, TenantId),
            (self.incident_id, IncidentId),
            (self.approval_fingerprint, Sha256Digest),
            (self.prior_proposal_fingerprint, Sha256Digest),
            (self.replacement_proposal_id, OpaqueIdentifier),
            (self.replacement_proposal_fingerprint, Sha256Digest),
            (self.replacement_material_fingerprint, Sha256Digest),
            (self.invalidated_by, ActorId),
            (self.invalidated_at, datetime),
        )
        if any(not isinstance(value, kind) for value, kind in expected):
            raise InvalidDomainValueError("Approval invalidation field types are invalid")
        if (
            not isinstance(self.replacement_proposal_version, int)
            or isinstance(self.replacement_proposal_version, bool)
            or self.replacement_proposal_version < 1
        ):
            raise InvalidDomainValueError("replacement proposal version is invalid")
        if self.schema_version != APPROVAL_INVALIDATION_SCHEMA_VERSION:
            raise InvalidDomainValueError("Approval invalidation schema version is unsupported")
        object.__setattr__(self, "invalidated_at", as_utc(self.invalidated_at))

    @property
    def fingerprint(self) -> Sha256Digest:
        document = {
            "approval_fingerprint": self.approval_fingerprint.value,
            "approval_id": self.approval_id.value,
            "incident_id": self.incident_id.value,
            "invalidated_at": self.invalidated_at.isoformat(),
            "invalidated_by": self.invalidated_by.value,
            "prior_proposal_fingerprint": self.prior_proposal_fingerprint.value,
            "replacement_material_fingerprint": self.replacement_material_fingerprint.value,
            "replacement_proposal_fingerprint": self.replacement_proposal_fingerprint.value,
            "replacement_proposal_id": self.replacement_proposal_id.value,
            "replacement_proposal_version": self.replacement_proposal_version,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id.value,
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(canonical).hexdigest())
