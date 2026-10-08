"""Authorized deterministic routing after a persisted successful health verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
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

HEALTH_VERIFICATION_CLOSURE_AUDIT_SCHEMA_VERSION: Final = "health_verification_closure/v1"
_CLOSURE_REASON: Final = EventReason("deterministic health verification passed")


class HealthVerificationClosureStore(Protocol):
    """Transaction-scoped port for loading and applying one success route."""

    async def get(
        self,
        decision_id: OpaqueIdentifier,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
    ) -> tuple[HealthVerificationObservation, HealthVerificationDecision] | None: ...

    async def resolve_and_close(
        self,
        decision: HealthVerificationDecision,
        *,
        metadata: EventMetadata,
        audit_event: AuditEvent,
    ) -> Incident: ...


class SuccessfulHealthVerificationRouter:
    """Turn only a persisted PASS into the legal VERIFYING -> RESOLVED -> CLOSED route."""

    def __init__(
        self,
        store: HealthVerificationClosureStore,
        *,
        clock: Callable[[], datetime],
        audit_event_id_factory: Callable[[], AuditEventId],
    ) -> None:
        self._store = store
        self._clock = clock
        self._audit_event_id_factory = audit_event_id_factory

    async def close(
        self,
        decision_id: OpaqueIdentifier,
        incident_id: IncidentId,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> Incident:
        if (
            not isinstance(decision_id, OpaqueIdentifier)
            or not isinstance(incident_id, IncidentId)
            or not isinstance(correlation_id, CorrelationId)
        ):
            raise InvalidDomainValueError("health verification closure inputs are invalid")
        authenticated = require_authenticated(principal)
        actor = require_permission(
            authenticated,
            Permission.APPROVED_ACTION_EXECUTE,
            tenant_id=authenticated.tenant_id,
        )
        stored = await self._store.get(
            decision_id,
            tenant_id=actor.tenant_id,
            incident_id=incident_id,
        )
        if stored is None:
            raise InvalidDomainValueError("successful health verification was not found")
        _, decision = stored
        if decision.outcome is not HealthVerificationOutcome.PASS:
            raise InvalidDomainValueError(
                "only a passing health verification can close an Incident"
            )
        occurred_at = as_utc(self._clock())
        if occurred_at < decision.evaluated_at:
            raise InvalidDomainValueError("health verification closure cannot predate its decision")
        audit_id = self._audit_event_id_factory()
        if not isinstance(audit_id, AuditEventId):
            raise InvalidDomainValueError("health verification closure audit identity is invalid")
        metadata = EventMetadata(
            actor_id=actor.actor_id,
            reason=_CLOSURE_REASON,
            correlation_id=correlation_id,
            causation_id=CausationId(decision.id.value),
            occurred_at=occurred_at,
        )
        audit_event = AuditEvent(
            id=audit_id,
            tenant_id=decision.tenant_id,
            type="health.verification_succeeded",
            event_version=1,
            payload_schema_version=HEALTH_VERIFICATION_CLOSURE_AUDIT_SCHEMA_VERSION,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            causation_id=metadata.causation_id,
            target=AuditTarget("incident.lifecycle", decision.incident_id),
            occurred_at=occurred_at,
            request_hash=decision.fingerprint,
            result_hash=health_verification_closure_fingerprint(decision),
        )
        return await self._store.resolve_and_close(
            decision,
            metadata=metadata,
            audit_event=audit_event,
        )


def health_verification_closure_fingerprint(
    decision: HealthVerificationDecision,
) -> Sha256Digest:
    if not isinstance(decision, HealthVerificationDecision):
        raise InvalidDomainValueError("health verification closure decision is invalid")
    document = {
        "decision_fingerprint": decision.fingerprint.value,
        "decision_id": decision.id.value,
        "final_state": "CLOSED",
        "incident_id": decision.incident_id.value,
        "outcome": decision.outcome.value,
        "tenant_id": decision.tenant_id.value,
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return Sha256Digest(hashlib.sha256(canonical).hexdigest())
