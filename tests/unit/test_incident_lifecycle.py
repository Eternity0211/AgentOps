"""Exhaustive tests for the Incident lifecycle aggregate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from agentops_incident_commander.domain import (
    ALLOWED_TRANSITIONS,
    CANCELLABLE_STATES,
    DEFERRED_CANCELLATION_STATES,
    DURABLE_WAIT_STATES,
    TERMINAL_STATES,
    ActorId,
    AggregateVersion,
    CancellationDisposition,
    CausationId,
    CorrelationId,
    EventMetadata,
    EventReason,
    Incident,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidIncidentTransitionError,
    NaiveDateTimeError,
    NonMonotonicTimeError,
    OptimisticVersionError,
    TenantId,
)

OPENED_AT = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
EVENT_AT = OPENED_AT + timedelta(minutes=1)

EXPECTED_TRANSITIONS = {
    IncidentState.DETECTED: {IncidentState.TRIAGED, IncidentState.CANCELLED},
    IncidentState.TRIAGED: {IncidentState.INVESTIGATING, IncidentState.CANCELLED},
    IncidentState.INVESTIGATING: {IncidentState.EVIDENCE_REVIEW, IncidentState.CANCELLED},
    IncidentState.EVIDENCE_REVIEW: {
        IncidentState.INVESTIGATING,
        IncidentState.NEEDS_HUMAN,
        IncidentState.PLANNING_REMEDIATION,
        IncidentState.CANCELLED,
    },
    IncidentState.NEEDS_HUMAN: {
        IncidentState.INVESTIGATING,
        IncidentState.PLANNING_REMEDIATION,
        IncidentState.VERIFYING,
        IncidentState.CANCELLED,
    },
    IncidentState.PLANNING_REMEDIATION: {
        IncidentState.POLICY_REVIEW,
        IncidentState.INVESTIGATING,
        IncidentState.NEEDS_HUMAN,
        IncidentState.CANCELLED,
    },
    IncidentState.POLICY_REVIEW: {
        IncidentState.PLANNING_REMEDIATION,
        IncidentState.NEEDS_HUMAN,
        IncidentState.AWAITING_APPROVAL,
        IncidentState.READY_TO_EXECUTE,
        IncidentState.CANCELLED,
    },
    IncidentState.AWAITING_APPROVAL: {
        IncidentState.PLANNING_REMEDIATION,
        IncidentState.NEEDS_HUMAN,
        IncidentState.READY_TO_EXECUTE,
        IncidentState.CANCELLED,
    },
    IncidentState.READY_TO_EXECUTE: {IncidentState.EXECUTING, IncidentState.CANCELLED},
    IncidentState.EXECUTING: {
        IncidentState.VERIFYING,
        IncidentState.INVESTIGATING,
        IncidentState.NEEDS_HUMAN,
    },
    IncidentState.VERIFYING: {
        IncidentState.RESOLVED,
        IncidentState.INVESTIGATING,
        IncidentState.NEEDS_HUMAN,
        IncidentState.COMPENSATING,
    },
    IncidentState.COMPENSATING: {
        IncidentState.VERIFYING_COMPENSATION,
        IncidentState.NEEDS_HUMAN,
    },
    IncidentState.VERIFYING_COMPENSATION: {
        IncidentState.INVESTIGATING,
        IncidentState.NEEDS_HUMAN,
    },
    IncidentState.RESOLVED: {IncidentState.CLOSED},
    IncidentState.CLOSED: set(),
    IncidentState.CANCELLED: set(),
}


def metadata(at: datetime = EVENT_AT) -> EventMetadata:
    """Build complete audit metadata for one lifecycle command."""
    return EventMetadata(
        actor_id=ActorId("actor-1"),
        reason=EventReason("test transition"),
        correlation_id=CorrelationId("correlation-1"),
        causation_id=CausationId("causation-1"),
        occurred_at=at,
    )


def incident_in(state: IncidentState, *, updated_at: datetime = OPENED_AT) -> Incident:
    """Build a valid aggregate at any state for transition-table tests."""
    return Incident(
        id=IncidentId("incident-1"),
        tenant_id=TenantId("tenant-1"),
        severity=IncidentSeverity.SEV2,
        opened_at=OPENED_AT,
        updated_at=updated_at,
        state=state,
        closed_at=updated_at if state is IncidentState.CLOSED else None,
        cancelled_at=updated_at if state is IncidentState.CANCELLED else None,
    )


def test_state_sets_and_transition_table_exactly_match_the_specification() -> None:
    """The code table cannot silently add, remove, or rename lifecycle routes."""
    assert set(ALLOWED_TRANSITIONS) == set(IncidentState)
    assert {state: set(targets) for state, targets in ALLOWED_TRANSITIONS.items()} == (
        EXPECTED_TRANSITIONS
    )
    assert {IncidentState.CLOSED, IncidentState.CANCELLED} == TERMINAL_STATES
    assert {
        IncidentState.AWAITING_APPROVAL,
        IncidentState.NEEDS_HUMAN,
    } == DURABLE_WAIT_STATES
    assert {
        state
        for state, targets in EXPECTED_TRANSITIONS.items()
        if IncidentState.CANCELLED in targets
    } == CANCELLABLE_STATES
    assert {
        IncidentState.EXECUTING,
        IncidentState.VERIFYING,
        IncidentState.COMPENSATING,
        IncidentState.VERIFYING_COMPENSATION,
    } == DEFERRED_CANCELLATION_STATES


def test_every_non_terminal_state_has_an_outgoing_transition() -> None:
    """No active or waiting state is a workflow dead end."""
    assert all(ALLOWED_TRANSITIONS[state] for state in set(IncidentState) - TERMINAL_STATES)
    assert all(not ALLOWED_TRANSITIONS[state] for state in TERMINAL_STATES)


@pytest.mark.parametrize(
    ("prior_state", "new_state"),
    [
        (prior_state, new_state)
        for prior_state, targets in EXPECTED_TRANSITIONS.items()
        for new_state in targets
    ],
)
def test_every_declared_transition_succeeds(
    prior_state: IncidentState, new_state: IncidentState
) -> None:
    """Every edge in the complete state graph is executable and auditable."""
    prior = incident_in(prior_state)

    change = prior.transition(new_state, expected_version=AggregateVersion(1), metadata=metadata())

    assert change.incident.state is new_state
    assert change.incident.version == AggregateVersion(2)
    assert change.incident.updated_at == EVENT_AT
    assert change.cancellation_request is None
    assert len(change.transitions) == 1
    event = change.transitions[0]
    assert event.incident_id == prior.id
    assert event.prior_state is prior_state
    assert event.new_state is new_state
    assert event.prior_version == AggregateVersion(1)
    assert event.new_version == AggregateVersion(2)
    assert event.metadata == metadata()
    assert change.incident.closed_at == (EVENT_AT if new_state is IncidentState.CLOSED else None)
    assert change.incident.cancelled_at == (
        EVENT_AT if new_state is IncidentState.CANCELLED else None
    )


@pytest.mark.parametrize(
    ("prior_state", "new_state"),
    [
        (prior_state, new_state)
        for prior_state in IncidentState
        for new_state in IncidentState
        if new_state not in EXPECTED_TRANSITIONS[prior_state]
    ],
)
def test_every_undeclared_transition_is_rejected(
    prior_state: IncidentState, new_state: IncidentState
) -> None:
    """All graph jumps outside the declared edge set fail closed."""
    with pytest.raises(InvalidIncidentTransitionError, match="is not allowed"):
        incident_in(prior_state).transition(
            new_state, expected_version=AggregateVersion(1), metadata=metadata()
        )


def test_open_creates_a_detected_version_one_incident_and_normalizes_time() -> None:
    """New aggregate state and time representation are deterministic."""
    local_time = datetime(2026, 10, 2, 16, 0, tzinfo=timezone(timedelta(hours=8)))

    incident = Incident.open(
        IncidentId("incident-1"), TenantId("tenant-1"), IncidentSeverity.SEV1, opened_at=local_time
    )

    assert incident.state is IncidentState.DETECTED
    assert incident.version == AggregateVersion.initial()
    assert incident.opened_at == OPENED_AT
    assert incident.updated_at == OPENED_AT


def test_event_metadata_normalizes_time_and_rejects_naive_time() -> None:
    """Lifecycle records always carry UTC-aware audit time."""
    local_time = datetime(2026, 10, 2, 16, 1, tzinfo=timezone(timedelta(hours=8)))
    assert metadata(local_time).occurred_at == EVENT_AT

    with pytest.raises(NaiveDateTimeError):
        metadata(datetime(2026, 10, 2, 8, 1))


def test_stale_optimistic_version_is_rejected_before_transition() -> None:
    """Concurrent writers cannot silently overwrite a newer aggregate."""
    with pytest.raises(OptimisticVersionError, match="expected version 2, current version 1"):
        incident_in(IncidentState.DETECTED).transition(
            IncidentState.TRIAGED,
            expected_version=AggregateVersion(2),
            metadata=metadata(),
        )


def test_event_time_cannot_move_backwards() -> None:
    """Audit history remains chronological even under delayed commands."""
    with pytest.raises(NonMonotonicTimeError, match="latest aggregate event"):
        incident_in(IncidentState.DETECTED, updated_at=EVENT_AT).transition(
            IncidentState.TRIAGED,
            expected_version=AggregateVersion(1),
            metadata=metadata(OPENED_AT),
        )


@pytest.mark.parametrize("state", sorted(CANCELLABLE_STATES, key=str))
def test_cancellation_is_immediate_only_from_explicit_safe_states(state: IncidentState) -> None:
    """Safe states create both a request record and terminal transition."""
    change = incident_in(state).request_cancellation(
        expected_version=AggregateVersion(1), metadata=metadata()
    )

    assert change.incident.state is IncidentState.CANCELLED
    assert change.incident.cancelled_at == EVENT_AT
    assert change.cancellation_request is not None
    assert change.cancellation_request.disposition is CancellationDisposition.CANCELLED
    assert change.cancellation_request.state_when_requested is state
    assert change.cancellation_request.prior_version == AggregateVersion(1)
    assert change.cancellation_request.new_version == AggregateVersion(2)
    assert change.transitions[0].new_state is IncidentState.CANCELLED


@pytest.mark.parametrize("state", sorted(DEFERRED_CANCELLATION_STATES, key=str))
def test_cancellation_during_deterministic_work_is_recorded_and_deferred(
    state: IncidentState,
) -> None:
    """Side effects and observations are never interrupted mid-operation."""
    change = incident_in(state).request_cancellation(
        expected_version=AggregateVersion(1), metadata=metadata()
    )

    assert change.incident.state is state
    assert change.incident.version == AggregateVersion(2)
    assert change.incident.cancellation_requested_at == EVENT_AT
    assert change.transitions == ()
    assert change.cancellation_request is not None
    assert change.cancellation_request.disposition is CancellationDisposition.DEFERRED


@pytest.mark.parametrize("state", [IncidentState.RESOLVED, *TERMINAL_STATES])
def test_cancellation_request_is_rejected_after_recovery_or_terminal_state(
    state: IncidentState,
) -> None:
    """Successful recovery proceeds to closure and terminals cannot mutate."""
    with pytest.raises(InvalidIncidentTransitionError, match="cannot be requested"):
        incident_in(state).request_cancellation(
            expected_version=AggregateVersion(1), metadata=metadata()
        )


def test_deferred_cancellation_is_applied_after_safe_failure_route() -> None:
    """The deterministic result is recorded before cancellation at the safe boundary."""
    deferred = (
        incident_in(IncidentState.EXECUTING)
        .request_cancellation(expected_version=AggregateVersion(1), metadata=metadata())
        .incident
    )
    routed_at = EVENT_AT + timedelta(seconds=1)

    change = deferred.transition(
        IncidentState.NEEDS_HUMAN,
        expected_version=AggregateVersion(2),
        metadata=metadata(routed_at),
    )

    assert change.incident.state is IncidentState.CANCELLED
    assert change.incident.version == AggregateVersion(4)
    assert change.incident.cancellation_requested_at is None
    assert [event.new_state for event in change.transitions] == [
        IncidentState.NEEDS_HUMAN,
        IncidentState.CANCELLED,
    ]
    assert [event.new_version for event in change.transitions] == [
        AggregateVersion(3),
        AggregateVersion(4),
    ]


def test_deferred_cancellation_remains_pending_across_another_unsafe_state() -> None:
    """A request waits while deterministic execution advances to verification."""
    deferred = (
        incident_in(IncidentState.EXECUTING)
        .request_cancellation(expected_version=AggregateVersion(1), metadata=metadata())
        .incident
    )

    change = deferred.transition(
        IncidentState.VERIFYING,
        expected_version=AggregateVersion(2),
        metadata=metadata(EVENT_AT + timedelta(seconds=1)),
    )

    assert change.incident.state is IncidentState.VERIFYING
    assert change.incident.cancellation_requested_at == EVENT_AT
    assert len(change.transitions) == 1


def test_successful_recovery_ignores_deferred_cancel_and_continues_to_closure() -> None:
    """A completed recovery is resolved rather than retroactively cancelled."""
    deferred = (
        incident_in(IncidentState.VERIFYING)
        .request_cancellation(expected_version=AggregateVersion(1), metadata=metadata())
        .incident
    )
    resolved = deferred.transition(
        IncidentState.RESOLVED,
        expected_version=AggregateVersion(2),
        metadata=metadata(EVENT_AT + timedelta(seconds=1)),
    ).incident

    assert resolved.state is IncidentState.RESOLVED
    assert resolved.cancellation_requested_at == EVENT_AT

    closed = resolved.transition(
        IncidentState.CLOSED,
        expected_version=AggregateVersion(3),
        metadata=metadata(EVENT_AT + timedelta(seconds=2)),
    ).incident
    assert closed.state is IncidentState.CLOSED
    assert closed.cancellation_requested_at is None


def test_cancellation_request_enforces_version_and_event_order() -> None:
    """Cancellation uses the same concurrency and chronology guards as transitions."""
    incident = incident_in(IncidentState.EXECUTING, updated_at=EVENT_AT)
    with pytest.raises(OptimisticVersionError):
        incident.request_cancellation(
            expected_version=AggregateVersion(2), metadata=metadata(EVENT_AT)
        )
    with pytest.raises(NonMonotonicTimeError):
        incident.request_cancellation(
            expected_version=AggregateVersion(1), metadata=metadata(OPENED_AT)
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"opened_at": EVENT_AT, "updated_at": OPENED_AT},
        {"closed_at": OPENED_AT},
        {"state": IncidentState.CLOSED},
        {"state": IncidentState.CANCELLED},
        {"cancelled_at": OPENED_AT},
        {"cancellation_requested_at": EVENT_AT + timedelta(seconds=1)},
    ],
)
def test_direct_construction_rejects_inconsistent_time_and_terminal_fields(
    kwargs: dict[str, object],
) -> None:
    """Repository hydration cannot create internally inconsistent aggregates."""
    defaults: dict[str, object] = {
        "id": IncidentId("incident-1"),
        "tenant_id": TenantId("tenant-1"),
        "severity": IncidentSeverity.SEV3,
        "opened_at": OPENED_AT,
        "updated_at": EVENT_AT,
    }
    defaults.update(kwargs)

    with pytest.raises((NonMonotonicTimeError, InvalidIncidentTransitionError)):
        Incident(**defaults)  # type: ignore[arg-type]


def test_direct_construction_normalizes_optional_timestamps() -> None:
    """Hydrated terminal timestamps use the same UTC normalization as event time."""
    local = datetime(2026, 10, 2, 16, 1, tzinfo=timezone(timedelta(hours=8)))
    incident = Incident(
        id=IncidentId("incident-1"),
        tenant_id=TenantId("tenant-1"),
        severity=IncidentSeverity.SEV4,
        opened_at=OPENED_AT,
        updated_at=local,
        state=IncidentState.CANCELLED,
        cancelled_at=local,
    )

    assert incident.updated_at == EVENT_AT
    assert incident.cancelled_at == EVENT_AT


def test_severity_enum_has_only_the_four_documented_tiers() -> None:
    """Severity values remain a closed domain vocabulary."""
    assert [severity.value for severity in IncidentSeverity] == ["SEV1", "SEV2", "SEV3", "SEV4"]
