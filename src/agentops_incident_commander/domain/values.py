"""Framework-free domain value objects and UTC handling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

from .errors import InvalidDomainValueError, InvalidIdentifierError, NaiveDateTimeError

_OPAQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def as_utc(value: datetime) -> datetime:
    """Reject naive timestamps and normalize aware timestamps to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise NaiveDateTimeError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class OpaqueIdentifier:
    """A conservative UUID/ULID-compatible opaque identifier."""

    value: str

    def __post_init__(self) -> None:
        if _OPAQUE_ID_PATTERN.fullmatch(self.value) is None:
            raise InvalidIdentifierError(
                "identifier must be 1-128 conservative characters and start alphanumeric"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class IncidentId(OpaqueIdentifier):
    """Identity of one Incident aggregate."""


@dataclass(frozen=True, slots=True)
class AlertId(OpaqueIdentifier):
    """Identity of one incoming or merged Alert."""


@dataclass(frozen=True, slots=True)
class AlertGroupId(OpaqueIdentifier):
    """Identity of one time-bounded deduplicated Alert group."""


@dataclass(frozen=True, slots=True)
class TenantId(OpaqueIdentifier):
    """Authorization and deduplication scope of a control-plane tenant."""


@dataclass(frozen=True, slots=True)
class AuditEventId(OpaqueIdentifier):
    """Immutable identity of one audit event."""


@dataclass(frozen=True, slots=True)
class OutboxEventId(OpaqueIdentifier):
    """Stable identity of one cross-process event intent."""


@dataclass(frozen=True, slots=True)
class Sha256Digest:
    """Validated lowercase SHA-256 digest used instead of sensitive payloads."""

    value: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.value) is None:
            raise InvalidDomainValueError("SHA-256 digest must contain 64 lowercase hex characters")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ActorId(OpaqueIdentifier):
    """Identity of a human or deterministic component causing an event."""


@dataclass(frozen=True, slots=True)
class CorrelationId(OpaqueIdentifier):
    """Identifier joining related work across process boundaries."""


@dataclass(frozen=True, slots=True)
class CausationId(OpaqueIdentifier):
    """Identifier of the command or event that directly caused another event."""


@dataclass(frozen=True, slots=True, order=True)
class AggregateVersion:
    """Positive optimistic version of a mutable aggregate."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or isinstance(self.value, bool) or self.value < 1:
            raise InvalidDomainValueError("aggregate version must be a positive integer")

    @classmethod
    def initial(cls) -> Self:
        """Return the version assigned to a newly created aggregate."""
        return cls(1)

    def next(self) -> Self:
        """Return the next optimistic version."""
        return type(self)(self.value + 1)


@dataclass(frozen=True, slots=True)
class EventReason:
    """A bounded, auditable human-readable reason for a domain event."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized or len(normalized) > 512:
            raise InvalidDomainValueError("event reason must contain 1-512 non-space characters")
        if any(character in normalized for character in ("\r", "\n", "\x00")):
            raise InvalidDomainValueError("event reason cannot contain line or null controls")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value
