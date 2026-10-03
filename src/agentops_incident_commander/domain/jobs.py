"""Pure contracts for the durable PostgreSQL worker queue."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import InvalidDomainValueError
from .values import CausationId, CorrelationId, JobId, OpaqueIdentifier, as_utc

_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*){1,7}$")
_VERSION_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}/v[1-9][0-9]*$")


class JobFailureRoute(StrEnum):
    """Terminal destination after all bounded attempts are consumed."""

    DEAD_LETTER = "DEAD_LETTER"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class JobStatus(StrEnum):
    """Persisted queue state owned by deterministic worker coordination."""

    PENDING = "PENDING"
    LEASED = "LEASED"
    COMPLETED = "COMPLETED"
    DEAD_LETTER = "DEAD_LETTER"
    NEEDS_HUMAN = "NEEDS_HUMAN"


@dataclass(frozen=True, slots=True)
class Job:
    """One bounded unit of workflow work referring to a durable payload."""

    id: JobId
    type: str
    schema_version: str
    payload_ref: OpaqueIdentifier
    correlation_id: CorrelationId
    causation_id: CausationId
    priority: int
    created_at: datetime
    available_at: datetime
    max_attempts: int
    failure_route: JobFailureRoute

    def __post_init__(self) -> None:
        if _TYPE_PATTERN.fullmatch(self.type) is None:
            raise InvalidDomainValueError("job type must be a dotted lowercase name")
        if _VERSION_PATTERN.fullmatch(self.schema_version) is None:
            raise InvalidDomainValueError("job schema version must use name/vN format")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise InvalidDomainValueError("job priority must be an integer")
        if not 0 <= self.priority <= 100:
            raise InvalidDomainValueError("job priority must be between 0 and 100")
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or self.max_attempts < 1
        ):
            raise InvalidDomainValueError("job max attempts must be a positive integer")
        object.__setattr__(self, "created_at", as_utc(self.created_at))
        object.__setattr__(self, "available_at", as_utc(self.available_at))
        if self.available_at < self.created_at:
            raise InvalidDomainValueError("job availability cannot predate creation")


@dataclass(frozen=True, slots=True)
class JobLease:
    """A live, worker-owned attempt to process one durable job."""

    job: Job
    attempt: int
    worker_id: OpaqueIdentifier
    leased_at: datetime
    heartbeat_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool) or self.attempt < 1:
            raise InvalidDomainValueError("job lease attempt must be a positive integer")
        for name in ("leased_at", "heartbeat_at", "expires_at"):
            object.__setattr__(self, name, as_utc(getattr(self, name)))
        if not self.leased_at <= self.heartbeat_at < self.expires_at:
            raise InvalidDomainValueError("job lease timestamps must be ordered and active")
