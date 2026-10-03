"""Incident lifecycle aggregate and exhaustive transition policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .errors import (
    InvalidIncidentTransitionError,
    NonMonotonicTimeError,
    OptimisticVersionError,
)
from .values import (
    ActorId,
    AggregateVersion,
    CausationId,
    CorrelationId,
    EventReason,
    IncidentId,
    TenantId,
    as_utc,
)


class IncidentSeverity(StrEnum):
    """Operator-facing impact tier, ordered from most to least severe."""

    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class IncidentState(StrEnum):
    """Complete set of Incident lifecycle states."""

    DETECTED = "DETECTED"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    PLANNING_REMEDIATION = "PLANNING_REMEDIATION"
    POLICY_REVIEW = "POLICY_REVIEW"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPENSATING = "COMPENSATING"
    VERIFYING_COMPENSATION = "VERIFYING_COMPENSATION"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CancellationDisposition(StrEnum):
    """Deterministic result of asking to cancel an Incident."""

    CANCELLED = "CANCELLED"
    DEFERRED = "DEFERRED"


_TRANSITIONS: Final[dict[IncidentState, frozenset[IncidentState]]] = {
    IncidentState.DETECTED: frozenset({IncidentState.TRIAGED, IncidentState.CANCELLED}),
    IncidentState.TRIAGED: frozenset({IncidentState.INVESTIGATING, IncidentState.CANCELLED}),
    IncidentState.INVESTIGATING: frozenset(
        {IncidentState.EVIDENCE_REVIEW, IncidentState.CANCELLED}
    ),
    IncidentState.EVIDENCE_REVIEW: frozenset(
        {
            IncidentState.INVESTIGATING,
            IncidentState.NEEDS_HUMAN,
            IncidentState.PLANNING_REMEDIATION,
            IncidentState.CANCELLED,
        }
    ),
    IncidentState.NEEDS_HUMAN: frozenset(
        {
            IncidentState.INVESTIGATING,
            IncidentState.PLANNING_REMEDIATION,
            IncidentState.VERIFYING,
            IncidentState.CANCELLED,
        }
    ),
    IncidentState.PLANNING_REMEDIATION: frozenset(
        {
            IncidentState.POLICY_REVIEW,
            IncidentState.INVESTIGATING,
            IncidentState.NEEDS_HUMAN,
            IncidentState.CANCELLED,
        }
    ),
    IncidentState.POLICY_REVIEW: frozenset(
        {
            IncidentState.PLANNING_REMEDIATION,
            IncidentState.NEEDS_HUMAN,
            IncidentState.AWAITING_APPROVAL,
            IncidentState.READY_TO_EXECUTE,
            IncidentState.CANCELLED,
        }
    ),
    IncidentState.AWAITING_APPROVAL: frozenset(
        {
            IncidentState.PLANNING_REMEDIATION,
            IncidentState.NEEDS_HUMAN,
            IncidentState.READY_TO_EXECUTE,
            IncidentState.CANCELLED,
        }
    ),
    IncidentState.READY_TO_EXECUTE: frozenset({IncidentState.EXECUTING, IncidentState.CANCELLED}),
    IncidentState.EXECUTING: frozenset(
        {IncidentState.VERIFYING, IncidentState.INVESTIGATING, IncidentState.NEEDS_HUMAN}
    ),
    IncidentState.VERIFYING: frozenset(
        {
            IncidentState.RESOLVED,
            IncidentState.INVESTIGATING,
            IncidentState.NEEDS_HUMAN,
            IncidentState.COMPENSATING,
        }
    ),
    IncidentState.COMPENSATING: frozenset(
        {IncidentState.VERIFYING_COMPENSATION, IncidentState.NEEDS_HUMAN}
    ),
    IncidentState.VERIFYING_COMPENSATION: frozenset(
        {IncidentState.INVESTIGATING, IncidentState.NEEDS_HUMAN}
    ),
    IncidentState.RESOLVED: frozenset({IncidentState.CLOSED}),
    IncidentState.CLOSED: frozenset(),
    IncidentState.CANCELLED: frozenset(),
}

ALLOWED_TRANSITIONS: Final[Mapping[IncidentState, frozenset[IncidentState]]] = MappingProxyType(
    _TRANSITIONS
)
TERMINAL_STATES: Final[frozenset[IncidentState]] = frozenset(
    {IncidentState.CLOSED, IncidentState.CANCELLED}
)
DURABLE_WAIT_STATES: Final[frozenset[IncidentState]] = frozenset(
    {IncidentState.AWAITING_APPROVAL, IncidentState.NEEDS_HUMAN}
)
CANCELLABLE_STATES: Final[frozenset[IncidentState]] = frozenset(
    state for state, targets in _TRANSITIONS.items() if IncidentState.CANCELLED in targets
)
DEFERRED_CANCELLATION_STATES: Final[frozenset[IncidentState]] = frozenset(
    {
        IncidentState.EXECUTING,
        IncidentState.VERIFYING,
        IncidentState.COMPENSATING,
        IncidentState.VERIFYING_COMPENSATION,
    }
)


@dataclass(frozen=True, slots=True)
class EventMetadata:
    """Required audit context shared by lifecycle commands."""

    actor_id: ActorId
    reason: EventReason
    correlation_id: CorrelationId
    causation_id: CausationId
    occurred_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))


@dataclass(frozen=True, slots=True)
class IncidentTransition:
    """Immutable evidence of one accepted state change."""

    incident_id: IncidentId
    prior_state: IncidentState
    new_state: IncidentState
    prior_version: AggregateVersion
    new_version: AggregateVersion
    metadata: EventMetadata


@dataclass(frozen=True, slots=True)
class IncidentCancellationRequest:
    """Immutable record of a cancellation request, including deferred ones."""

    incident_id: IncidentId
    state_when_requested: IncidentState
    prior_version: AggregateVersion
    new_version: AggregateVersion
    disposition: CancellationDisposition
    metadata: EventMetadata


@dataclass(frozen=True, slots=True)
class IncidentChange:
    """New aggregate plus all records created by a single domain command."""

    incident: Incident
    transitions: tuple[IncidentTransition, ...] = ()
    cancellation_request: IncidentCancellationRequest | None = None


@dataclass(frozen=True, slots=True)
class Incident:
    """Immutable Incident aggregate with optimistic versioning."""

    id: IncidentId
    tenant_id: TenantId
    severity: IncidentSeverity
    opened_at: datetime
    updated_at: datetime
    state: IncidentState = IncidentState.DETECTED
    version: AggregateVersion = field(default_factory=AggregateVersion.initial)
    closed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_requested_at: datetime | None = None

    def __post_init__(self) -> None:
        opened_at = as_utc(self.opened_at)
        updated_at = as_utc(self.updated_at)
        if updated_at < opened_at:
            raise NonMonotonicTimeError("updated_at cannot predate opened_at")
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "updated_at", updated_at)
        for field_name in ("closed_at", "cancelled_at", "cancellation_requested_at"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = as_utc(value)
                if normalized < opened_at or normalized > updated_at:
                    raise NonMonotonicTimeError(
                        f"{field_name} must be within the aggregate event time range"
                    )
                object.__setattr__(self, field_name, normalized)
        if (self.state is IncidentState.CLOSED) != (self.closed_at is not None):
            raise InvalidIncidentTransitionError("only CLOSED incidents have closed_at")
        if (self.state is IncidentState.CANCELLED) != (self.cancelled_at is not None):
            raise InvalidIncidentTransitionError("only CANCELLED incidents have cancelled_at")

    @classmethod
    def open(
        cls,
        incident_id: IncidentId,
        tenant_id: TenantId,
        severity: IncidentSeverity,
        *,
        opened_at: datetime,
    ) -> Incident:
        """Create a new DETECTED Incident at optimistic version one."""
        timestamp = as_utc(opened_at)
        return cls(
            id=incident_id,
            tenant_id=tenant_id,
            severity=severity,
            opened_at=timestamp,
            updated_at=timestamp,
        )

    def transition(
        self,
        new_state: IncidentState,
        *,
        expected_version: AggregateVersion,
        metadata: EventMetadata,
    ) -> IncidentChange:
        """Apply one legal state change and honor a deferred cancellation at a safe boundary."""
        self._validate_command(expected_version, metadata.occurred_at)
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidIncidentTransitionError(
                f"transition {self.state.value} -> {new_state.value} is not allowed"
            )

        transitioned, first_event = self._apply_transition(new_state, metadata)
        transitions = (first_event,)
        if (
            self.cancellation_requested_at is not None
            and new_state in CANCELLABLE_STATES
            and new_state is not IncidentState.CANCELLED
        ):
            cancelled, cancellation_event = transitioned._apply_transition(
                IncidentState.CANCELLED, metadata
            )
            return IncidentChange(cancelled, (*transitions, cancellation_event))
        return IncidentChange(transitioned, transitions)

    def request_cancellation(
        self, *, expected_version: AggregateVersion, metadata: EventMetadata
    ) -> IncidentChange:
        """Cancel immediately at a safe state or durably defer during deterministic work."""
        self._validate_command(expected_version, metadata.occurred_at)
        if self.state in CANCELLABLE_STATES:
            cancelled, event = self._apply_transition(IncidentState.CANCELLED, metadata)
            request = IncidentCancellationRequest(
                incident_id=self.id,
                state_when_requested=self.state,
                prior_version=self.version,
                new_version=cancelled.version,
                disposition=CancellationDisposition.CANCELLED,
                metadata=metadata,
            )
            return IncidentChange(cancelled, (event,), request)
        if self.state not in DEFERRED_CANCELLATION_STATES:
            raise InvalidIncidentTransitionError(
                f"cancellation cannot be requested from {self.state.value}"
            )

        next_version = self.version.next()
        deferred = replace(
            self,
            version=next_version,
            updated_at=metadata.occurred_at,
            cancellation_requested_at=metadata.occurred_at,
        )
        request = IncidentCancellationRequest(
            incident_id=self.id,
            state_when_requested=self.state,
            prior_version=self.version,
            new_version=next_version,
            disposition=CancellationDisposition.DEFERRED,
            metadata=metadata,
        )
        return IncidentChange(deferred, cancellation_request=request)

    def _validate_command(self, expected_version: AggregateVersion, occurred_at: datetime) -> None:
        if expected_version != self.version:
            raise OptimisticVersionError(
                f"expected version {expected_version.value}, current version {self.version.value}"
            )
        if occurred_at < self.updated_at:
            raise NonMonotonicTimeError("event timestamp cannot predate the latest aggregate event")

    def _apply_transition(
        self, new_state: IncidentState, metadata: EventMetadata
    ) -> tuple[Incident, IncidentTransition]:
        next_version = self.version.next()
        incident = replace(
            self,
            state=new_state,
            version=next_version,
            updated_at=metadata.occurred_at,
            closed_at=metadata.occurred_at if new_state is IncidentState.CLOSED else None,
            cancelled_at=(metadata.occurred_at if new_state is IncidentState.CANCELLED else None),
            cancellation_requested_at=(
                None
                if new_state in {IncidentState.CLOSED, IncidentState.CANCELLED}
                else self.cancellation_requested_at
            ),
        )
        event = IncidentTransition(
            incident_id=self.id,
            prior_state=self.state,
            new_state=new_state,
            prior_version=self.version,
            new_version=next_version,
            metadata=metadata,
        )
        return incident, event
