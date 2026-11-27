"""Tests for fail-closed tenant membership persistence mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.domain import (
    ActorId,
    AuthenticationError,
    FederatedIdentity,
    Role,
    TenantId,
)
from agentops_incident_commander.infrastructure.persistence import PostgresTenantMembershipStore


class ScalarSession:
    def __init__(self, result: object) -> None:
        self.result = result
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> object:
        self.statements.append(statement)
        return self.result


def store(result: object) -> PostgresTenantMembershipStore:
    session = cast(AsyncSession, cast(Any, ScalarSession(result)))
    return PostgresTenantMembershipStore(session)


@pytest.mark.anyio
async def test_membership_store_maps_active_server_roles() -> None:
    repository = store(
        SimpleNamespace(actor_id="actor-1", tenant_id="tenant-1", roles=["OPERATOR", "APPROVER"])
    )
    membership = await repository.get_active_membership(
        FederatedIdentity("https://identity.example.test", "user-1"),
        tenant_id=TenantId("tenant-1"),
    )
    assert membership is not None
    assert membership.actor_id == ActorId("actor-1")
    assert membership.tenant_id == TenantId("tenant-1")
    assert membership.roles == {Role.OPERATOR, Role.APPROVER}


@pytest.mark.anyio
async def test_membership_store_returns_none_when_query_has_no_active_match() -> None:
    assert (
        await store(None).get_active_membership(
            FederatedIdentity("https://identity.example.test", "user-1"),
            tenant_id=TenantId("tenant-1"),
        )
        is None
    )


@pytest.mark.anyio
@pytest.mark.parametrize("roles", [["ROOT"], None, [], ["VIEWER", "VIEWER"]])
async def test_membership_store_rejects_corrupt_role_documents(roles: object) -> None:
    repository = store(SimpleNamespace(actor_id="actor-1", tenant_id="tenant-1", roles=roles))
    with pytest.raises(AuthenticationError, match="roles are invalid"):
        await repository.get_active_membership(
            FederatedIdentity("https://identity.example.test", "user-1"),
            tenant_id=TenantId("tenant-1"),
        )
