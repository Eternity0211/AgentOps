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


class ArtifactError(DomainError):
    """Base class for an Artifact contract or storage failure."""


class ArtifactAlreadyExistsError(ArtifactError):
    """An immutable Artifact identity was already assigned."""


class ArtifactNotFoundError(ArtifactError):
    """An Artifact identity cannot be resolved by the configured store."""


class ArtifactExpiredError(ArtifactError):
    """Artifact content is no longer retrievable under its retention policy."""


class ArtifactIntegrityError(ArtifactError):
    """Stored Artifact bytes or metadata do not match their immutable digest."""


class ToolRegistryError(DomainError):
    """A versioned ToolDefinition could not be resolved safely."""


class ToolNotFoundError(ToolRegistryError):
    """The exact server-owned tool name/version is not registered."""


class ToolVersionDisabledError(ToolRegistryError):
    """The exact registered tool version is outside the enabled range."""


class PromptRegistryError(DomainError):
    """A versioned Prompt definition could not be configured or resolved safely."""


class PromptNotFoundError(PromptRegistryError):
    """A requested Prompt identity/version or active version is unavailable."""
