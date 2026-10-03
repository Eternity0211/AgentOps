"""Explicit failures raised by pure domain invariants."""

from __future__ import annotations


class DomainError(ValueError):
    """Base class for a rejected domain operation."""


class InvalidIdentifierError(DomainError):
    """An opaque identifier is empty, malformed, or too long."""


class InvalidDomainValueError(DomainError):
    """A bounded domain value violates its contract."""


class NaiveDateTimeError(DomainError):
    """A timestamp lacks timezone information."""


class InvalidIncidentTransitionError(DomainError):
    """An Incident transition is not in the complete transition table."""


class OptimisticVersionError(DomainError):
    """A command was based on a stale Incident aggregate version."""


class NonMonotonicTimeError(DomainError):
    """An Incident event predates the aggregate's latest event."""


class OutboxLeaseError(DomainError):
    """An outbox acknowledgement came from a missing, stale, or foreign lease."""


class JobLeaseError(DomainError):
    """A job command came from a missing, stale, or foreign lease."""


class AuthenticationError(DomainError):
    """A request has no validated principal."""


class AuthorizationError(DomainError):
    """A validated principal is not permitted to perform an operation."""
