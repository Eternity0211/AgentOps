"""Deterministic non-compensable routing after failed rollback verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol

from agentops_incident_commander.domain import (
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    EventMetadata,
    EventReason,
    HealthVerificationDecision,
    HealthVerificationObservation,
    HealthVerificationOutcome,
    Incident,
    IncidentId,
    IncidentState,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Permission,
    Principal,
    Sha256Digest,
    TenantId,
    as_utc,
    require_authenticated,
    require_permission,
)
from agentops_incident_commander.workflows import (
    RecoveryAction,
    RemediationFailureRoute,
    RemediationProposal,
)

HEALTH_VERIFICATION_FAILURE_AUDIT_SCHEMA_VERSION: Final = "health_verification_failure/v1"


class VerificationFailureOutcome(StrEnum):
    REDIAGNOSE = "REDIAGNOSE"
    NEEDS_HUMAN = "NEEDS_HUMAN"


@dataclass(frozen=True, slots=True)
class VerificationFailureDecision:
    verification_decision_id: OpaqueIdentifier
    verification_fingerprint: Sha256Digest
    proposal_fingerprint: Sha256Digest
    outcome: VerificationFailureOutcome
    target_state: IncidentState
    used_rediagnosis_attempts: int
    max_rediagnosis_attempts: int
    next_used_rediagnosis_attempts: int

    def __post_init__(self) -> None:
        expected_state = (
            IncidentState.INVESTIGATING
            if self.outcome is VerificationFailureOutcome.REDIAGNOSE
            else IncidentState.NEEDS_HUMAN
        )
        if self.target_state is not expected_state:
            raise InvalidDomainValueError("verification failure outcome and target state differ")
        values = (
            self.used_rediagnosis_attempts,
            self.max_rediagnosis_attempts,
            self.next_used_rediagnosis_attempts,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise InvalidDomainValueError("verification failure budget is invalid")
        if not 0 <= self.used_rediagnosis_attempts <= self.max_rediagnosis_attempts <= 3:
            raise InvalidDomainValueError("verification failure budget is outside bounds")
        expected_next = self.used_rediagnosis_attempts + (
            1 if self.outcome is VerificationFailureOutcome.REDIAGNOSE else 0
        )
        if self.next_used_rediagnosis_attempts != expected_next:
            raise InvalidDomainValueError("verification failure budget consumption is invalid")

    @property
    def fingerprint(self) -> Sha256Digest:
        document = {
            "max_rediagnosis_attempts": self.max_rediagnosis_attempts,
            "next_used_rediagnosis_attempts": self.next_used_rediagnosis_attempts,
            "outcome": self.outcome.value,
            "proposal_fingerprint": self.proposal_fingerprint.value,
            "target_state": self.target_state.value,
            "used_rediagnosis_attempts": self.used_rediagnosis_attempts,
            "verification_decision_id": self.verification_decision_id.value,
            "verification_fingerprint": self.verification_fingerprint.value,
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(canonical).hexdigest())


class HealthVerificationFailureStore(Protocol):
    async def get(
        self,
        decision_id: OpaqueIdentifier,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
    ) -> tuple[HealthVerificationObservation, HealthVerificationDecision] | None: ...

    async def route_failure(
        self,
        decision: HealthVerificationDecision,
        proposal: RemediationProposal,
        route: VerificationFailureDecision,
        *,
        metadata: EventMetadata,
        audit_event: AuditEvent,
    ) -> Incident: ...


def decide_verification_failure_route(
    decision: HealthVerificationDecision,
    proposal: RemediationProposal,
    *,
    used_rediagnosis_attempts: int,
) -> VerificationFailureDecision:
    if not isinstance(decision, HealthVerificationDecision) or not isinstance(
        proposal, RemediationProposal
    ):
        raise InvalidDomainValueError("verification failure routing inputs are invalid")
    if decision.outcome is not HealthVerificationOutcome.FAIL:
        raise InvalidDomainValueError("verification failure routing requires FAIL")
    if proposal.incident_id != decision.incident_id.value:
        raise InvalidDomainValueError("verification failure proposal scope differs")
    if (
        proposal.action is not RecoveryAction.ROLLBACK_SERVICE
        or proposal.compensation_eligible
        or proposal.failure_handling.redeploy_faulty_version
    ):
        raise InvalidDomainValueError("rollback_service failure is non-compensable")
    maximum = proposal.failure_handling.max_rediagnosis_attempts
    if (
        not isinstance(used_rediagnosis_attempts, int)
        or isinstance(used_rediagnosis_attempts, bool)
        or not 0 <= used_rediagnosis_attempts <= maximum
    ):
        raise InvalidDomainValueError("verification failure used budget is invalid")
    rediagnose = (
        proposal.failure_handling.route
        is RemediationFailureRoute.BOUNDED_REDIAGNOSIS_THEN_HUMAN_HANDOFF
        and used_rediagnosis_attempts < maximum
    )
    outcome = (
        VerificationFailureOutcome.REDIAGNOSE
        if rediagnose
        else VerificationFailureOutcome.NEEDS_HUMAN
    )
    return VerificationFailureDecision(
        decision.id,
        decision.fingerprint,
        proposal.fingerprint,
        outcome,
        IncidentState.INVESTIGATING if rediagnose else IncidentState.NEEDS_HUMAN,
        used_rediagnosis_attempts,
        maximum,
        used_rediagnosis_attempts + (1 if rediagnose else 0),
    )


class FailedHealthVerificationRouter:
    def __init__(
        self,
        store: HealthVerificationFailureStore,
        *,
        clock: Callable[[], datetime],
        audit_event_id_factory: Callable[[], AuditEventId],
    ) -> None:
        self._store = store
        self._clock = clock
        self._audit_event_id_factory = audit_event_id_factory

    async def route(
        self,
        decision_id: OpaqueIdentifier,
        incident_id: IncidentId,
        proposal: RemediationProposal,
        *,
        used_rediagnosis_attempts: int,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> Incident:
        authenticated = require_authenticated(principal)
        actor = require_permission(
            authenticated,
            Permission.APPROVED_ACTION_EXECUTE,
            tenant_id=authenticated.tenant_id,
        )
        stored = await self._store.get(
            decision_id, tenant_id=actor.tenant_id, incident_id=incident_id
        )
        if stored is None:
            raise InvalidDomainValueError("failed health verification was not found")
        _, decision = stored
        route = decide_verification_failure_route(
            decision,
            proposal,
            used_rediagnosis_attempts=used_rediagnosis_attempts,
        )
        occurred_at = as_utc(self._clock())
        if occurred_at < decision.evaluated_at:
            raise InvalidDomainValueError("verification failure route predates its decision")
        audit_id = self._audit_event_id_factory()
        if not isinstance(audit_id, AuditEventId):
            raise InvalidDomainValueError("verification failure audit identity is invalid")
        metadata = EventMetadata(
            actor.actor_id,
            EventReason(
                f"failed rollback verification; route={route.outcome.value}; "
                f"rediagnosis={route.next_used_rediagnosis_attempts}/"
                f"{route.max_rediagnosis_attempts}; compensation=forbidden"
            ),
            correlation_id,
            CausationId(decision.id.value),
            occurred_at,
        )
        audit = AuditEvent(
            audit_id,
            decision.tenant_id,
            "health.verification_failed",
            1,
            HEALTH_VERIFICATION_FAILURE_AUDIT_SCHEMA_VERSION,
            actor.actor_id,
            correlation_id,
            metadata.causation_id,
            AuditTarget("incident.lifecycle", decision.incident_id),
            occurred_at,
            decision.fingerprint,
            route.fingerprint,
        )
        return await self._store.route_failure(
            decision, proposal, route, metadata=metadata, audit_event=audit
        )
