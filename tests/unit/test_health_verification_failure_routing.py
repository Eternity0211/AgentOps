"""Bounded non-compensable failed-verification routing tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from test_health_verification import decision, observation
from test_remediation_schemas import proposal

from agentops_incident_commander.application import (
    FailedHealthVerificationRouter,
    VerificationFailureDecision,
    VerificationFailureOutcome,
    decide_verification_failure_route,
)
from agentops_incident_commander.domain import (
    ActorId,
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
    Principal,
    Role,
    TenantId,
)
from agentops_incident_commander.workflows import (
    RemediationFailureHandling,
    RemediationFailureRoute,
    RemediationProposal,
)

NOW = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)


def failed_decision() -> HealthVerificationDecision:
    return replace(
        decision(evaluated_at=NOW - timedelta(seconds=1)),
        outcome=HealthVerificationOutcome.FAIL,
        reasons=(HealthVerificationReasonCode.P95_LATENCY_ABOVE_LIMIT,),
    )


def scoped_proposal(**overrides: Any) -> RemediationProposal:
    return proposal(incident_id="incident-verification", **overrides)


def operator() -> Principal:
    return Principal(
        ActorId("operator-verification-failure"),
        TenantId("tenant-verification"),
        frozenset({Role.OPERATOR}),
    )


class Store:
    def __init__(self, stored: tuple[Any, HealthVerificationDecision] | None) -> None:
        self.stored = stored
        self.call: tuple[VerificationFailureDecision, EventMetadata, AuditEvent] | None = None

    async def get(
        self, *args: object, **kwargs: object
    ) -> tuple[Any, HealthVerificationDecision] | None:
        del args, kwargs
        return self.stored

    async def route_failure(
        self,
        decision: HealthVerificationDecision,
        proposal: RemediationProposal,
        route: VerificationFailureDecision,
        *,
        metadata: EventMetadata,
        audit_event: AuditEvent,
    ) -> Incident:
        del decision, proposal
        self.call = (route, metadata, audit_event)
        incident = Incident(
            IncidentId("incident-verification"),
            TenantId("tenant-verification"),
            IncidentSeverity.SEV2,
            NOW - timedelta(hours=1),
            NOW - timedelta(minutes=1),
            IncidentState.VERIFYING,
        )
        return incident.transition(
            route.target_state,
            expected_version=incident.version,
            metadata=metadata,
        ).incident


def test_failure_decision_consumes_one_bounded_attempt_then_hands_off() -> None:
    failed = failed_decision()
    remediation = scoped_proposal()
    first = decide_verification_failure_route(failed, remediation, used_rediagnosis_attempts=0)
    assert first.outcome is VerificationFailureOutcome.REDIAGNOSE
    assert first.target_state is IncidentState.INVESTIGATING
    assert first.next_used_rediagnosis_attempts == 1
    exhausted = decide_verification_failure_route(failed, remediation, used_rediagnosis_attempts=2)
    assert exhausted.outcome is VerificationFailureOutcome.NEEDS_HUMAN
    assert exhausted.target_state is IncidentState.NEEDS_HUMAN
    assert exhausted.next_used_rediagnosis_attempts == 2
    handoff = scoped_proposal(
        failure_handling=RemediationFailureHandling(
            route=RemediationFailureRoute.HUMAN_HANDOFF,
            max_rediagnosis_attempts=0,
        )
    )
    assert (
        decide_verification_failure_route(failed, handoff, used_rediagnosis_attempts=0).target_state
        is IncidentState.NEEDS_HUMAN
    )
    assert first.fingerprint == first.fingerprint


def test_failure_decision_rejects_invalid_inputs_scope_status_and_budget() -> None:
    failed = failed_decision()
    with pytest.raises(InvalidDomainValueError, match="inputs"):
        decide_verification_failure_route(
            cast(HealthVerificationDecision, "bad"), scoped_proposal(), used_rediagnosis_attempts=0
        )
    with pytest.raises(InvalidDomainValueError, match="inputs"):
        decide_verification_failure_route(
            failed, cast(RemediationProposal, "bad"), used_rediagnosis_attempts=0
        )
    with pytest.raises(InvalidDomainValueError, match="requires FAIL"):
        decide_verification_failure_route(
            decision(), scoped_proposal(), used_rediagnosis_attempts=0
        )
    with pytest.raises(InvalidDomainValueError, match="scope"):
        decide_verification_failure_route(failed, proposal(), used_rediagnosis_attempts=0)
    unsafe = scoped_proposal().model_copy(update={"compensation_eligible": True})
    with pytest.raises(InvalidDomainValueError, match="non-compensable"):
        decide_verification_failure_route(failed, unsafe, used_rediagnosis_attempts=0)
    for used in (-1, 3, True):
        with pytest.raises(InvalidDomainValueError, match="used budget"):
            decide_verification_failure_route(
                failed, scoped_proposal(), used_rediagnosis_attempts=used
            )


def test_failure_decision_invariants_reject_inconsistent_state_and_budget() -> None:
    valid = decide_verification_failure_route(
        failed_decision(), scoped_proposal(), used_rediagnosis_attempts=0
    )
    for changes, message in (
        ({"target_state": IncidentState.COMPENSATING}, "target state"),
        ({"used_rediagnosis_attempts": True}, "budget is invalid"),
        ({"max_rediagnosis_attempts": 4}, "outside bounds"),
        ({"next_used_rediagnosis_attempts": 0}, "consumption"),
    ):
        with pytest.raises(InvalidDomainValueError, match=message):
            replace(valid, **changes)


@pytest.mark.anyio
async def test_failure_router_emits_bound_non_compensable_route() -> None:
    failed = failed_decision()
    store = Store((observation(), failed))
    router = FailedHealthVerificationRouter(
        store,
        clock=lambda: NOW,
        audit_event_id_factory=lambda: AuditEventId("audit-verification-failure"),
    )
    incident = await router.route(
        failed.id,
        failed.incident_id,
        scoped_proposal(),
        used_rediagnosis_attempts=0,
        principal=operator(),
        correlation_id=CorrelationId("correlation-verification-failure"),
    )
    assert incident.state is IncidentState.INVESTIGATING
    assert store.call is not None
    route, metadata, audit = store.call
    assert "compensation=forbidden" in metadata.reason.value
    assert audit.request_hash == failed.fingerprint
    assert audit.result_hash == route.fingerprint
    assert audit.type == "health.verification_failed"


@pytest.mark.anyio
async def test_failure_router_rejects_missing_time_regression_and_bad_audit_id() -> None:
    failed = failed_decision()
    with pytest.raises(InvalidDomainValueError, match="not found"):
        await FailedHealthVerificationRouter(
            Store(None), clock=lambda: NOW, audit_event_id_factory=lambda: AuditEventId("audit-a")
        ).route(
            failed.id,
            failed.incident_id,
            scoped_proposal(),
            used_rediagnosis_attempts=0,
            principal=operator(),
            correlation_id=CorrelationId("correlation-a"),
        )
    with pytest.raises(InvalidDomainValueError, match="predates"):
        await FailedHealthVerificationRouter(
            Store((observation(), failed)),
            clock=lambda: failed.evaluated_at - timedelta(seconds=1),
            audit_event_id_factory=lambda: AuditEventId("audit-b"),
        ).route(
            failed.id,
            failed.incident_id,
            scoped_proposal(),
            used_rediagnosis_attempts=0,
            principal=operator(),
            correlation_id=CorrelationId("correlation-b"),
        )
    with pytest.raises(InvalidDomainValueError, match="audit identity"):
        await FailedHealthVerificationRouter(
            Store((observation(), failed)),
            clock=lambda: NOW,
            audit_event_id_factory=lambda: cast(AuditEventId, "bad"),
        ).route(
            failed.id,
            failed.incident_id,
            scoped_proposal(),
            used_rediagnosis_attempts=0,
            principal=operator(),
            correlation_id=CorrelationId("correlation-c"),
        )
