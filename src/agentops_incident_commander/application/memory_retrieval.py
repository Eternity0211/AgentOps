"""Authorized retrieval of reference-only similar confirmed Incidents."""

from __future__ import annotations

from typing import Protocol

from agentops_incident_commander.domain import (
    IncidentMemorySearchQuery,
    Permission,
    Principal,
    SimilarIncidentReference,
    require_permission,
)


class IncidentMemorySearchStore(Protocol):
    async def search(
        self, query: IncidentMemorySearchQuery
    ) -> tuple[SimilarIncidentReference, ...]: ...


class SimilarIncidentRetriever:
    """Apply RBAC before a tenant-bound historical-memory lookup."""

    def __init__(self, store: IncidentMemorySearchStore) -> None:
        self._store = store

    async def search(
        self,
        principal: Principal | None,
        query: IncidentMemorySearchQuery,
    ) -> tuple[SimilarIncidentReference, ...]:
        require_permission(principal, Permission.EVIDENCE_READ, tenant_id=query.tenant_id)
        return await self._store.search(query)
