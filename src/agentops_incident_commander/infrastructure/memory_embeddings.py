"""Credential-free deterministic embedding adapter for tests and mock-model mode."""

from __future__ import annotations

import math
from datetime import datetime
from hashlib import sha256

from agentops_incident_commander.domain import (
    INCIDENT_MEMORY_SCHEMA_VERSION,
    MAX_EMBEDDING_DIMENSIONS,
    IncidentMemoryEmbedding,
    IncidentMemoryProjection,
    InvalidDomainValueError,
    OpaqueIdentifier,
)


class DeterministicIncidentMemoryEmbedder:
    """Create stable normalized vectors without provider calls or source-text retention."""

    def __init__(self, *, dimensions: int = 16, model_version: str = "1.0.0") -> None:
        if (
            not isinstance(dimensions, int)
            or isinstance(dimensions, bool)
            or not 1 <= dimensions <= MAX_EMBEDDING_DIMENSIONS
        ):
            raise InvalidDomainValueError("deterministic embedding dimensions are invalid")
        self._dimensions = dimensions
        self._model_version = model_version

    async def generate(
        self,
        projection: IncidentMemoryProjection,
        *,
        embedding_id: OpaqueIdentifier,
        created_at: datetime,
    ) -> IncidentMemoryEmbedding:
        seed = projection.content_fingerprint.value.encode("ascii")
        values: list[float] = []
        counter = 0
        while len(values) < self._dimensions:
            digest = sha256(seed + counter.to_bytes(4, "big")).digest()
            values.extend((byte - 127.5) / 127.5 for byte in digest)
            counter += 1
        vector = values[: self._dimensions]
        magnitude = math.sqrt(sum(value * value for value in vector))
        normalized = tuple(value / magnitude for value in vector)
        return IncidentMemoryEmbedding(
            id=embedding_id,
            tenant_id=projection.tenant_id,
            memory_id=projection.id,
            incident_id=projection.source_incident_id,
            source_content_fingerprint=projection.content_fingerprint,
            provider="agentops-mock",
            model="deterministic-sha256",
            model_version=self._model_version,
            content_schema_version=INCIDENT_MEMORY_SCHEMA_VERSION,
            normalization_version="l2-v1",
            vector=normalized,
            created_at=created_at,
        )
