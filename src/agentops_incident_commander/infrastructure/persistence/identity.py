"""PostgreSQL resolution of verified external identities to tenant memberships."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.application import TenantMembership
from agentops_incident_commander.domain import (
    ActorId,
    AuthenticationError,
    FederatedIdentity,
    Role,
    TenantId,
)

from .models import FederatedIdentityRow, IdentityUserRow, TenantMembershipRow, TenantRow


class PostgresTenantMembershipStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_membership(
        self, identity: FederatedIdentity, *, tenant_id: TenantId
    ) -> TenantMembership | None:
        statement = (
            select(TenantMembershipRow)
            .join(IdentityUserRow, IdentityUserRow.id == TenantMembershipRow.actor_id)
            .join(TenantRow, TenantRow.id == TenantMembershipRow.tenant_id)
            .join(
                FederatedIdentityRow,
                FederatedIdentityRow.actor_id == TenantMembershipRow.actor_id,
            )
            .where(
                FederatedIdentityRow.issuer == identity.issuer,
                FederatedIdentityRow.subject == identity.subject,
                TenantMembershipRow.tenant_id == tenant_id.value,
                IdentityUserRow.active.is_(True),
                TenantRow.active.is_(True),
                TenantMembershipRow.active.is_(True),
            )
        )
        row = await self._session.scalar(statement)
        if row is None:
            return None
        try:
            roles = tuple(Role(value) for value in row.roles)
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("persisted tenant membership roles are invalid") from exc
        if not roles or len(roles) != len(set(roles)):
            raise AuthenticationError("persisted tenant membership roles are invalid")
        return TenantMembership(
            actor_id=ActorId(row.actor_id),
            tenant_id=TenantId(row.tenant_id),
            roles=frozenset(roles),
        )
