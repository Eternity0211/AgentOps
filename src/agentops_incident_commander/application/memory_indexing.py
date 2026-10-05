"""Incident-memory embedding generation use case and ports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    IncidentMemoryEmbedding,
    IncidentMemoryProjection,
    OpaqueIdentifier,
)


class IncidentMemoryEmbedder(Protocol):
    async def generate(
        self,
        projection: IncidentMemoryProjection,
        *,
        embedding_id: OpaqueIdentifier,
        created_at: datetime,
    ) -> IncidentMemoryEmbedding: ...


class IncidentMemoryIndexStore(Protocol):
    async def store(
        self,
        projection: IncidentMemoryProjection,
        embedding: IncidentMemoryEmbedding,
    ) -> IncidentMemoryEmbedding: ...


class IncidentMemoryIndexer:
    """Generate then transactionally persist one versioned memory vector."""

    def __init__(
        self,
        *,
        embedder: IncidentMemoryEmbedder,
        store: IncidentMemoryIndexStore,
        id_factory: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._id_factory = id_factory
        self._clock = clock

    async def index(self, projection: IncidentMemoryProjection) -> IncidentMemoryEmbedding:
        embedding = await self._embedder.generate(
            projection,
            embedding_id=OpaqueIdentifier(self._id_factory()),
            created_at=self._clock(),
        )
        return await self._store.store(projection, embedding)
