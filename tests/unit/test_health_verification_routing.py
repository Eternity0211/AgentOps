"""Authorized deterministic successful-verification routing tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from test_health_verification import decision, observation

from agentops_incident_commander.application import (
    HEALTH_VERIFICATION_CLOSURE_AUDIT_SCHEMA_VERSION,
    SuccessfulHealthVerificationRouter,
    health_verification_closure_fingerprint,
)
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    AuditEvent,
    AuditEventId,
    CorrelationId,
    EventMetadata,
    HealthVerificationDecision,
    HealthVerificationOutcome,
    HealthVerificationReasonCode,
    Incident,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Principal,
    Role,
    TenantId,
)

NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
CORRELATION = CorrelationId("correlation-verification-closure")


def principal(role: Role = Role.OPERATOR) -> Principal:
    return Principal(
        ActorId(f"actor-{role.value.lower()}"), TenantId("tenant-verification"), frozenset({role})
    )


def verifying_incident() -> Incident:
    return Incident(
        id=IncidentId("incident-verification"),
        tenant_id=TenantId("tenant-verification"),
        severity=IncidentSeverity.SEV2,
        opened_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(minutes=1),
        state=IncidentState.VERIFYING,
    )


class Store:
    def __init__(
        self,
        stored: tuple[Any, HealthVerificationDecision] | None,
    ) -> None:
        self.stored = stored
        self.calls: list[tuple[HealthVerificationDecision, EventMetadata, AuditEvent]] = []

    async def get(
        self,
        decision_id: OpaqueIdentifier,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
    ) -> tuple[Any, HealthVerificationDecision] | None:
        del decision_id, tenant_id, incident_id
        return self.stored

    async def resolve_and_close(
        self,
        verification: HealthVerificationDecision,
        *,
        metadata: EventMetadata,
        audit_event: AuditEvent,
    ) -> Incident:
        self.calls.append((verification, metadata, audit_event))
        current = verifying_incident()
        resolved = current.transition(
            IncidentState.RESOLVED,
            expected_version=current.version,
            metadata=metadata,
        ).incident
        return resolved.transition(
            IncidentState.CLOSED,
            expected_version=resolved.version,
            metadata=metadata,
        ).incident


def router(
    store: Store,
    *,
    now: datetime = NOW,
    audit_id: object = AuditEventId("audit-verification-closure"),
) -> SuccessfulHealthVerificationRouter:
    return SuccessfulHealthVerificationRouter(
        store,
        clock=lambda: now,
        audit_event_id_factory=lambda: cast(AuditEventId, audit_id),
    )


@pytest.mark.anyio
async def test_persisted_pass_routes_through_resolved_to_closed_with_bound_audit() -> None:
    passed = decision(evaluated_at=NOW - timedelta(seconds=1))
    store = Store((observation(), passed))

    closed = await router(store).close(
        passed.id,
        passed.incident_id,
        principal=principal(),
        correlation_id=CORRELATION,
    )

    assert closed.state is IncidentState.CLOSED
    assert closed.version == AggregateVersion(3)
    assert closed.closed_at == NOW
    assert len(store.calls) == 1
    routed, metadata, audit = store.calls[0]
    assert routed == passed
    assert metadata.actor_id == principal().actor_id
    assert metadata.causation_id.value == passed.id.value
    assert audit.type == "health.verification_succeeded"
    assert audit.payload_schema_version == HEALTH_VERIFICATION_CLOSURE_AUDIT_SCHEMA_VERSION
    assert audit.request_hash == passed.fingerprint
    assert audit.result_hash == health_verification_closure_fingerprint(passed)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("decision_id", "incident_id", "correlation_id"),
    [
        ("bad", IncidentId("incident-verification"), CORRELATION),
        (OpaqueIdentifier("decision-verification"), "bad", CORRELATION),
        (OpaqueIdentifier("decision-verification"), IncidentId("incident-verification"), "bad"),
    ],
)
async def test_invalid_route_inputs_fail_closed(
    decision_id: object, incident_id: object, correlation_id: object
) -> None:
    with pytest.raises(InvalidDomainValueError, match="inputs"):
        await router(Store(None)).close(
            cast(OpaqueIdentifier, decision_id),
            cast(IncidentId, incident_id),
            principal=principal(),
            correlation_id=cast(CorrelationId, correlation_id),
        )


@pytest.mark.anyio
async def test_route_requires_authorized_operator_and_persisted_pass() -> None:
    passed = decision(evaluated_at=NOW - timedelta(seconds=1))
    with pytest.raises(Exception, match="authentication"):
        await router(Store((observation(), passed))).close(
            passed.id, passed.incident_id, principal=None, correlation_id=CORRELATION
        )
    with pytest.raises(Exception, match="permission"):
        await router(Store((observation(), passed))).close(
            passed.id,
            passed.incident_id,
            principal=principal(Role.VIEWER),
            correlation_id=CORRELATION,
        )
    with pytest.raises(InvalidDomainValueError, match="not found"):
        await router(Store(None)).close(
            passed.id, passed.incident_id, principal=principal(), correlation_id=CORRELATION
        )
    failed = replace(
        passed,
        outcome=HealthVerificationOutcome.FAIL,
        reasons=(HealthVerificationReasonCode.P95_LATENCY_ABOVE_LIMIT,),
    )
    with pytest.raises(InvalidDomainValueError, match="passing"):
        await router(Store((observation(), failed))).close(
            failed.id, failed.incident_id, principal=principal(), correlation_id=CORRELATION
        )


@pytest.mark.anyio
async def test_route_rejects_time_regression_and_invalid_audit_identity() -> None:
    passed = decision(evaluated_at=NOW)
    with pytest.raises(InvalidDomainValueError, match="predate"):
        await router(Store((observation(), passed)), now=NOW - timedelta(seconds=1)).close(
            passed.id, passed.incident_id, principal=principal(), correlation_id=CORRELATION
        )
    with pytest.raises(InvalidDomainValueError, match="audit identity"):
        await router(Store((observation(), passed)), audit_id="bad").close(
            passed.id, passed.incident_id, principal=principal(), correlation_id=CORRELATION
        )


def test_closure_fingerprint_rejects_invalid_decision() -> None:
    with pytest.raises(InvalidDomainValueError, match="decision"):
        health_verification_closure_fingerprint(cast(HealthVerificationDecision, "bad"))
