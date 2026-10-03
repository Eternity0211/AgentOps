"""Pure immutable Artifact metadata and storage-port contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from .auth import Principal
from .errors import InvalidDomainValueError
from .values import ArtifactId, IncidentId, Sha256Digest, TenantId, as_utc

ARTIFACT_METADATA_SCHEMA_VERSION = "1.0.0"
_MEDIA_TYPE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_LOCATOR = re.compile(r"^local-artifact:v1:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RetentionClass(StrEnum):
    """Server-owned lifecycle class; expiry remains explicit metadata."""

    TRANSIENT = "TRANSIENT"
    INCIDENT = "INCIDENT"
    AUDIT = "AUDIT"


class RedactionStatus(StrEnum):
    """Whether sensitive values were removed before persistence."""

    NOT_REQUIRED = "NOT_REQUIRED"
    REDACTED = "REDACTED"


@dataclass(frozen=True, slots=True)
class Artifact:
    """Immutable metadata resolving a bounded payload in an Artifact store."""

    id: ArtifactId
    tenant_id: TenantId
    incident_id: IncidentId
    locator: str
    media_type: str
    content_schema_version: str
    content_hash: Sha256Digest
    size_bytes: int
    retention_class: RetentionClass
    created_at: datetime
    expires_at: datetime | None
    redaction_status: RedactionStatus
    encrypted: bool
    metadata_schema_version: str = ARTIFACT_METADATA_SCHEMA_VERSION

    def __post_init__(self) -> None:
        media_type = self.media_type.strip().lower()
        if _MEDIA_TYPE.fullmatch(media_type) is None:
            raise InvalidDomainValueError("artifact media type must be a bounded canonical type")
        if _VERSION.fullmatch(self.content_schema_version) is None:
            raise InvalidDomainValueError("artifact content schema version is invalid")
        if self.metadata_schema_version != ARTIFACT_METADATA_SCHEMA_VERSION:
            raise InvalidDomainValueError("artifact metadata schema version is unsupported")
        if (
            _LOCATOR.fullmatch(self.locator) is None
            or self.locator != f"local-artifact:v1:{self.id.value}"
        ):
            raise InvalidDomainValueError(
                "artifact locator must be server-generated for its identity"
            )
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            raise InvalidDomainValueError("artifact size must be an integer")
        if self.size_bytes < 0:
            raise InvalidDomainValueError("artifact size cannot be negative")
        created_at = as_utc(self.created_at)
        expires_at = as_utc(self.expires_at) if self.expires_at is not None else None
        if expires_at is not None and expires_at <= created_at:
            raise InvalidDomainValueError("artifact expiry must follow creation")
        if self.retention_class is RetentionClass.TRANSIENT and expires_at is None:
            raise InvalidDomainValueError("transient artifacts require an expiry")
        if not isinstance(self.encrypted, bool):
            raise InvalidDomainValueError("artifact encryption metadata must be boolean")
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "expires_at", expires_at)

    def is_expired(self, *, at: datetime) -> bool:
        """Return whether retrieval is forbidden at the supplied instant."""
        current = as_utc(at)
        return self.expires_at is not None and current >= self.expires_at


@dataclass(frozen=True, slots=True)
class ArtifactContent:
    """A verified Artifact metadata record and its immutable bytes."""

    artifact: Artifact
    content: bytes


class ArtifactStorage(Protocol):
    """Replaceable port for immutable, authorized Artifact persistence."""

    def store(self, artifact: Artifact, content: bytes) -> Artifact: ...

    def retrieve(
        self,
        artifact_id: ArtifactId,
        *,
        incident_id: IncidentId,
        principal: Principal | None,
        at: datetime,
    ) -> ArtifactContent: ...
