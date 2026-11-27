"""PostgreSQL storage for one-time OIDC transactions and revocable browser sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.application.browser_auth import (
    BrowserAuthStore,
    BrowserSession,
    LoginAttempt,
)
from agentops_incident_commander.domain import (
    ActorId,
    AuthenticationError,
    Principal,
    Role,
    TenantId,
)

from .models import (
    BrowserSessionRow,
    IdentityUserRow,
    OidcLoginAttemptRow,
    TenantMembershipRow,
    TenantRow,
)


class PostgresBrowserAuthStore(BrowserAuthStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_login_attempt(self, attempt: LoginAttempt, *, now: datetime) -> None:
        self._session.add(
            OidcLoginAttemptRow(
                state_hash=attempt.state_hash,
                transaction_hash=attempt.transaction_hash,
                tenant_id=attempt.tenant_id.value,
                nonce=attempt.nonce,
                code_verifier=attempt.code_verifier,
                created_at=now,
                expires_at=attempt.expires_at,
                consumed_at=None,
            )
        )
        await self._session.flush()

    async def consume_login_attempt(
        self, *, state_hash: str, transaction_hash: str, now: datetime
    ) -> LoginAttempt | None:
        row = await self._session.scalar(
            select(OidcLoginAttemptRow)
            .where(
                OidcLoginAttemptRow.state_hash == state_hash,
                OidcLoginAttemptRow.transaction_hash == transaction_hash,
                OidcLoginAttemptRow.consumed_at.is_(None),
                OidcLoginAttemptRow.expires_at > now,
            )
            .with_for_update()
        )
        if row is None:
            return None
        row.consumed_at = now
        await self._session.flush()
        return LoginAttempt(
            state_hash=row.state_hash,
            transaction_hash=row.transaction_hash,
            tenant_id=TenantId(row.tenant_id),
            nonce=row.nonce,
            code_verifier=row.code_verifier,
            expires_at=row.expires_at,
        )

    async def create_session(self, session: BrowserSession, *, now: datetime) -> None:
        self._session.add(
            BrowserSessionRow(
                id_hash=session.session_hash,
                csrf_hash=session.csrf_hash,
                actor_id=session.principal.actor_id.value,
                tenant_id=session.principal.tenant_id.value,
                created_at=now,
                expires_at=session.expires_at,
                revoked_at=None,
            )
        )
        await self._session.flush()

    async def resolve_session(self, *, session_hash: str, now: datetime) -> BrowserSession | None:
        row = await self._session.execute(
            select(BrowserSessionRow, TenantMembershipRow)
            .join(IdentityUserRow, IdentityUserRow.id == BrowserSessionRow.actor_id)
            .join(TenantRow, TenantRow.id == BrowserSessionRow.tenant_id)
            .join(
                TenantMembershipRow,
                (TenantMembershipRow.actor_id == BrowserSessionRow.actor_id)
                & (TenantMembershipRow.tenant_id == BrowserSessionRow.tenant_id),
            )
            .where(
                BrowserSessionRow.id_hash == session_hash,
                BrowserSessionRow.revoked_at.is_(None),
                BrowserSessionRow.expires_at > now,
                IdentityUserRow.active.is_(True),
                TenantRow.active.is_(True),
                TenantMembershipRow.active.is_(True),
            )
        )
        values = row.one_or_none()
        if values is None:
            return None
        session_row, membership_row = values
        try:
            roles = frozenset(Role(item) for item in membership_row.roles)
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("persisted browser session roles are invalid") from exc
        if not roles or len(roles) != len(membership_row.roles):
            raise AuthenticationError("persisted browser session roles are invalid")
        return BrowserSession(
            session_hash=session_row.id_hash,
            csrf_hash=session_row.csrf_hash,
            principal=Principal(
                ActorId(session_row.actor_id), TenantId(session_row.tenant_id), roles
            ),
            expires_at=session_row.expires_at,
        )

    async def revoke_session(self, *, session_hash: str, now: datetime) -> None:
        await self._session.execute(
            update(BrowserSessionRow)
            .where(
                BrowserSessionRow.id_hash == session_hash,
                BrowserSessionRow.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self._session.flush()
