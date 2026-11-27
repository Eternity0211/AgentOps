"""Tests for persistence mapping of OIDC attempts and revocable sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.application.browser_auth import BrowserSession, LoginAttempt
from agentops_incident_commander.domain import (
    ActorId,
    AuthenticationError,
    Principal,
    Role,
    TenantId,
)
from agentops_incident_commander.infrastructure.persistence import (
    BrowserSessionRow,
    OidcLoginAttemptRow,
    PostgresBrowserAuthStore,
)

NOW = datetime(2026, 11, 27, 8, 0, tzinfo=UTC)
PRINCIPAL = Principal(ActorId("actor-1"), TenantId("tenant-1"), frozenset({Role.VIEWER}))


class Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def one_or_none(self) -> object:
        return self.value


class Session:
    def __init__(self, *, scalars: list[object] | None = None, results: list[object] | None = None):
        self.scalar_values = list(scalars or [])
        self.results = list(results or [])
        self.added: list[object] = []
        self.statements: list[object] = []
        self.flushes = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1

    async def scalar(self, statement: object) -> object:
        self.statements.append(statement)
        return self.scalar_values.pop(0)

    async def execute(self, statement: object) -> Result:
        self.statements.append(statement)
        return Result(self.results.pop(0) if self.results else None)


def store(session: Session) -> PostgresBrowserAuthStore:
    return PostgresBrowserAuthStore(cast(AsyncSession, cast(Any, session)))


def attempt() -> LoginAttempt:
    return LoginAttempt(
        "a" * 64,
        "b" * 64,
        TenantId("tenant-1"),
        "n" * 43,
        "v" * 86,
        NOW + timedelta(minutes=5),
    )


def browser_session() -> BrowserSession:
    return BrowserSession("c" * 64, "d" * 64, PRINCIPAL, NOW + timedelta(hours=8))


@pytest.mark.anyio
async def test_login_attempt_save_consume_and_missing_paths() -> None:
    fake = Session()
    repository = store(fake)
    await repository.save_login_attempt(attempt(), now=NOW)
    row = fake.added[0]
    assert isinstance(row, OidcLoginAttemptRow)
    assert row.tenant_id == "tenant-1" and row.consumed_at is None

    persisted = SimpleNamespace(
        state_hash="a" * 64,
        transaction_hash="b" * 64,
        tenant_id="tenant-1",
        nonce="n" * 43,
        code_verifier="v" * 86,
        expires_at=NOW + timedelta(minutes=5),
        consumed_at=None,
    )
    fake = Session(scalars=[persisted, None])
    repository = store(fake)
    assert (
        await repository.consume_login_attempt(
            state_hash="a" * 64, transaction_hash="b" * 64, now=NOW
        )
        == attempt()
    )
    assert persisted.consumed_at == NOW
    assert (
        await repository.consume_login_attempt(
            state_hash="x" * 64, transaction_hash="y" * 64, now=NOW
        )
        is None
    )


@pytest.mark.anyio
async def test_session_create_resolve_revoke_and_missing_paths() -> None:
    fake = Session()
    repository = store(fake)
    await repository.create_session(browser_session(), now=NOW)
    row = fake.added[0]
    assert isinstance(row, BrowserSessionRow)
    assert row.actor_id == "actor-1" and row.revoked_at is None

    session_row = SimpleNamespace(
        id_hash="c" * 64,
        csrf_hash="d" * 64,
        actor_id="actor-1",
        tenant_id="tenant-1",
        expires_at=NOW + timedelta(hours=8),
    )
    membership = SimpleNamespace(roles=["VIEWER"])
    fake = Session(results=[(session_row, membership), None])
    repository = store(fake)
    assert await repository.resolve_session(session_hash="c" * 64, now=NOW) == browser_session()
    assert await repository.resolve_session(session_hash="x" * 64, now=NOW) is None
    await repository.revoke_session(session_hash="c" * 64, now=NOW)
    assert fake.flushes == 1


@pytest.mark.anyio
@pytest.mark.parametrize("roles", [["ROOT"], None, [], ["VIEWER", "VIEWER"]])
async def test_session_resolver_rejects_corrupt_roles(roles: object) -> None:
    session_row = SimpleNamespace(
        id_hash="c" * 64,
        csrf_hash="d" * 64,
        actor_id="actor-1",
        tenant_id="tenant-1",
        expires_at=NOW + timedelta(hours=8),
    )
    repository = store(Session(results=[(session_row, SimpleNamespace(roles=roles))]))
    with pytest.raises(AuthenticationError, match="roles are invalid"):
        await repository.resolve_session(session_hash="c" * 64, now=NOW)
