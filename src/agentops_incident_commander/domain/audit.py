"""Pure append-only audit event contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .errors import InvalidDomainValueError
from .values import (
    ActorId,
    AuditEventId,
    CausationId,
    CorrelationId,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    as_utc,
)

_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*){1,7}$")
_VERSION_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}/v[1-9][0-9]*$")


@dataclass(frozen=True, slots=True)
class AuditTarget:
    """Typed target reference without embedding mutable target content."""

    type: str
    id: OpaqueIdentifier

    def __post_init__(self) -> None:
        if _TYPE_PATTERN.fullmatch(self.type) is None:
            raise InvalidDomainValueError("audit target type must be a dotted lowercase name")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Immutable audit event staged for database sequence assignment."""

    id: AuditEventId
    tenant_id: TenantId
    type: str
    event_version: int
    payload_schema_version: str
    actor_id: ActorId
    correlation_id: CorrelationId
    causation_id: CausationId
    target: AuditTarget
    occurred_at: datetime
    request_hash: Sha256Digest | None = None
    result_hash: Sha256Digest | None = None

    def __post_init__(self) -> None:
        if _TYPE_PATTERN.fullmatch(self.type) is None:
            raise InvalidDomainValueError("audit event type must be a dotted lowercase name")
        if (
            not isinstance(self.event_version, int)
            or isinstance(self.event_version, bool)
            or self.event_version < 1
        ):
            raise InvalidDomainValueError("audit event version must be a positive integer")
        if _VERSION_PATTERN.fullmatch(self.payload_schema_version) is None:
            raise InvalidDomainValueError("payload schema version must use name/vN format")
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))


@dataclass(frozen=True, slots=True)
class StoredAuditEvent:
    """Audit event with its database-assigned global sequence."""

    sequence: int
    event: AuditEvent

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 1
        ):
            raise InvalidDomainValueError("audit sequence must be a positive integer")
