"""Pure contracts for transactional cross-process event intent."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self

from .errors import InvalidDomainValueError
from .values import (
    CausationId,
    CorrelationId,
    OpaqueIdentifier,
    OutboxEventId,
    Sha256Digest,
    as_utc,
)

_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*){1,7}$")
_VERSION_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}/v[1-9][0-9]*$")
_MAX_PAYLOAD_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class OutboxPayload:
    """Canonical bounded JSON object safe for hashing and durable transport."""

    canonical_json: str

    def __post_init__(self) -> None:
        try:
            value = json.loads(self.canonical_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise InvalidDomainValueError("outbox payload must be valid JSON") from exc
        if not isinstance(value, dict):
            raise InvalidDomainValueError("outbox payload must be a JSON object")
        canonical = self._encode(value)
        if canonical != self.canonical_json:
            raise InvalidDomainValueError("outbox payload must use canonical JSON encoding")

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Self:
        """Encode a JSON-compatible mapping deterministically."""
        try:
            encoded = cls._encode(value)
        except InvalidDomainValueError:
            raise
        except (TypeError, ValueError) as exc:
            raise InvalidDomainValueError("outbox payload must contain finite JSON values") from exc
        return cls(encoded)

    @staticmethod
    def _encode(value: dict[str, Any]) -> str:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise InvalidDomainValueError("outbox payload exceeds 65536 UTF-8 bytes")
        return encoded

    @property
    def sha256(self) -> Sha256Digest:
        """Return the digest used to detect storage or transport drift."""
        return Sha256Digest(hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest())

    def as_mapping(self) -> dict[str, Any]:
        """Return a detached JSON object for persistence or publication."""
        value: dict[str, Any] = json.loads(self.canonical_json)
        return value


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """One idempotent event intent staged in an aggregate transaction."""

    id: OutboxEventId
    topic: str
    schema_version: str
    aggregate_type: str
    aggregate_id: OpaqueIdentifier
    aggregate_version: int
    correlation_id: CorrelationId
    causation_id: CausationId
    payload: OutboxPayload
    occurred_at: datetime
    available_at: datetime
    max_attempts: int = 8

    def __post_init__(self) -> None:
        for label, value in (("topic", self.topic), ("aggregate type", self.aggregate_type)):
            if _TYPE_PATTERN.fullmatch(value) is None:
                raise InvalidDomainValueError(f"outbox {label} must be a dotted lowercase name")
        if _VERSION_PATTERN.fullmatch(self.schema_version) is None:
            raise InvalidDomainValueError("outbox schema version must use name/vN format")
        for label, int_value in (
            ("aggregate version", self.aggregate_version),
            ("max attempts", self.max_attempts),
        ):
            if not isinstance(int_value, int) or isinstance(int_value, bool) or int_value < 1:
                raise InvalidDomainValueError(f"outbox {label} must be a positive integer")
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))
        object.__setattr__(self, "available_at", as_utc(self.available_at))
        if self.available_at < self.occurred_at:
            raise InvalidDomainValueError("outbox availability cannot predate occurrence")


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    """A delivery attempt held by one worker until a UTC lease deadline."""

    sequence: int
    event: OutboxEvent
    attempt: int
    worker_id: OpaqueIdentifier
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        for label, value in (("sequence", self.sequence), ("attempt", self.attempt)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise InvalidDomainValueError(f"outbox {label} must be a positive integer")
        object.__setattr__(self, "lease_expires_at", as_utc(self.lease_expires_at))
