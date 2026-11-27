"""Resolve authenticated federated identities into server-owned tenant authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agentops_incident_commander.domain import (
    ActorId,
    AuthenticationError,
    FederatedIdentity,
    Principal,
    Role,
    TenantId,
)


@dataclass(frozen=True, slots=True)
class TenantMembership:
    """An active server-owned assignment; token claims never construct this value."""

    actor_id: ActorId
    tenant_id: TenantId
    roles: frozenset[Role]

    def principal(self) -> Principal:
        return Principal(self.actor_id, self.tenant_id, self.roles)


class TenantMembershipStore(Protocol):
    async def get_active_membership(
        self, identity: FederatedIdentity, *, tenant_id: TenantId
    ) -> TenantMembership | None: ...


class FederatedPrincipalResolver:
    """Map a verified subject to one explicitly requested active tenant membership."""

    def __init__(self, store: TenantMembershipStore) -> None:
        self._store = store

    async def resolve(self, identity: FederatedIdentity, *, tenant_id: TenantId) -> Principal:
        membership = await self._store.get_active_membership(identity, tenant_id=tenant_id)
        if membership is None:
            raise AuthenticationError("authenticated identity has no active tenant membership")
        if membership.tenant_id != tenant_id:
            raise AuthenticationError("membership resolver returned a different tenant")
        return membership.principal()
