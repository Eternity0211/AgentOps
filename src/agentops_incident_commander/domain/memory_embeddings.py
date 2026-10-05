"""Versioned Incident-memory embedding metadata and vector invariants."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

from .errors import InvalidDomainValueError
from .values import IncidentId, IncidentMemoryId, OpaqueIdentifier, Sha256Digest, TenantId, as_utc

MAX_EMBEDDING_DIMENSIONS = 16_000
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


@dataclass(frozen=True, slots=True)
class IncidentMemoryEmbedding:
    """One reproducible vector derived from an immutable memory projection."""

    id: OpaqueIdentifier
    tenant_id: TenantId
    memory_id: IncidentMemoryId
    incident_id: IncidentId
    source_content_fingerprint: Sha256Digest
    provider: str
    model: str
    model_version: str
    content_schema_version: str
    normalization_version: str
    vector: tuple[float, ...]
    created_at: datetime
    reindex_required: bool = False

    def __post_init__(self) -> None:
        typed = (
            (self.id, OpaqueIdentifier),
            (self.tenant_id, TenantId),
            (self.memory_id, IncidentMemoryId),
            (self.incident_id, IncidentId),
            (self.source_content_fingerprint, Sha256Digest),
        )
        if any(not isinstance(value, expected) for value, expected in typed):
            raise InvalidDomainValueError("Incident memory embedding identity is invalid")
        for name, value in (
            ("provider", self.provider),
            ("model", self.model),
            ("model version", self.model_version),
            ("content schema version", self.content_schema_version),
            ("normalization version", self.normalization_version),
        ):
            if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
                raise InvalidDomainValueError(f"Incident memory embedding {name} is invalid")
        if (
            not isinstance(self.vector, tuple)
            or not 1 <= len(self.vector) <= MAX_EMBEDDING_DIMENSIONS
            or any(
                not isinstance(value, float) or not math.isfinite(value) for value in self.vector
            )
        ):
            raise InvalidDomainValueError("Incident memory embedding vector is invalid")
        if not isinstance(self.reindex_required, bool):
            raise InvalidDomainValueError("Incident memory embedding reindex flag is invalid")
        object.__setattr__(self, "created_at", as_utc(self.created_at))

    @property
    def dimensions(self) -> int:
        return len(self.vector)

    @property
    def version_identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.provider,
            self.model,
            self.model_version,
            self.content_schema_version,
            self.normalization_version,
        )
