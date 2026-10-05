"""Versioned Incident-memory embedding metadata and vector invariants."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .errors import InvalidDomainValueError
from .values import IncidentId, IncidentMemoryId, OpaqueIdentifier, Sha256Digest, TenantId, as_utc

MAX_EMBEDDING_DIMENSIONS = 16_000
MAX_SIMILAR_INCIDENT_RESULTS = 20
MAX_MEMORY_LOOKBACK = timedelta(days=3650)
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
        _validate_model_identity(
            (
                ("provider", self.provider),
                ("model", self.model),
                ("model version", self.model_version),
                ("content schema version", self.content_schema_version),
                ("normalization version", self.normalization_version),
            )
        )
        _validate_vector(self.vector)
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


@dataclass(frozen=True, slots=True)
class IncidentMemorySearchQuery:
    """Tenant-bound vector query with an explicit historical freshness window."""

    tenant_id: TenantId
    current_incident_id: IncidentId
    provider: str
    model: str
    model_version: str
    content_schema_version: str
    normalization_version: str
    vector: tuple[float, ...]
    max_results: int
    requested_at: datetime
    max_age: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, TenantId) or not isinstance(
            self.current_incident_id, IncidentId
        ):
            raise InvalidDomainValueError("Incident memory search scope is invalid")
        _validate_model_identity(
            (
                ("provider", self.provider),
                ("model", self.model),
                ("model version", self.model_version),
                ("content schema version", self.content_schema_version),
                ("normalization version", self.normalization_version),
            )
        )
        _validate_vector(self.vector)
        if (
            not isinstance(self.max_results, int)
            or isinstance(self.max_results, bool)
            or not 1 <= self.max_results <= MAX_SIMILAR_INCIDENT_RESULTS
        ):
            raise InvalidDomainValueError("similar Incident result limit is invalid")
        if (
            not isinstance(self.max_age, timedelta)
            or not timedelta(0) < self.max_age <= MAX_MEMORY_LOOKBACK
        ):
            raise InvalidDomainValueError("similar Incident freshness window is invalid")
        object.__setattr__(self, "requested_at", as_utc(self.requested_at))

    @property
    def dimensions(self) -> int:
        return len(self.vector)

    @property
    def freshness_cutoff(self) -> datetime:
        return self.requested_at - self.max_age


@dataclass(frozen=True, slots=True)
class SimilarIncidentReference:
    """Minimal same-tenant historical result; never current-Incident Evidence."""

    incident_id: IncidentId
    service: str
    root_cause_summary: str
    outcome: str
    outcome_summary: str
    closed_at: datetime
    similarity: float
    historical_reference_only: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.incident_id, IncidentId):
            raise InvalidDomainValueError("similar Incident identity is invalid")
        if (
            not isinstance(self.service, str)
            or not self.service
            or not isinstance(self.root_cause_summary, str)
            or not self.root_cause_summary
            or not isinstance(self.outcome, str)
            or not self.outcome
            or not isinstance(self.outcome_summary, str)
            or not self.outcome_summary
        ):
            raise InvalidDomainValueError("similar Incident summary is invalid")
        if (
            not isinstance(self.similarity, float)
            or not math.isfinite(self.similarity)
            or not 0.0 <= self.similarity <= 1.0
        ):
            raise InvalidDomainValueError("similar Incident score is invalid")
        if self.historical_reference_only is not True:
            raise InvalidDomainValueError("similar Incident must remain historical reference only")
        object.__setattr__(self, "closed_at", as_utc(self.closed_at))


def _validate_model_identity(values: tuple[tuple[str, object], ...]) -> None:
    for name, value in values:
        if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
            raise InvalidDomainValueError(f"Incident memory embedding {name} is invalid")


def _validate_vector(vector: object) -> None:
    if (
        not isinstance(vector, tuple)
        or not 1 <= len(vector) <= MAX_EMBEDDING_DIMENSIONS
        or any(not isinstance(value, float) or not math.isfinite(value) for value in vector)
        or math.sqrt(sum(value * value for value in vector)) == 0.0
    ):
        raise InvalidDomainValueError("Incident memory embedding vector is invalid")
