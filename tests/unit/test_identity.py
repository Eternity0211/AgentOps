"""Tests for verified identity and server-owned tenant authority resolution."""

from __future__ import annotations

from dataclasses import replace

import pytest

from agentops_incident_commander.application import (
    FederatedPrincipalResolver,
    TenantMembership,
)
from agentops_incident_commander.domain import (
    ActorId,
    AuthenticationError,
    FederatedIdentity,
    InvalidDomainValueError,
    Role,
    TenantId,
)


class MembershipStore:
    def __init__(self, membership: TenantMembership | None) -> None:
        self.membership = membership
        self.requests: list[tuple[FederatedIdentity, TenantId]] = []

    async def get_active_membership(
        self, identity: FederatedIdentity, *, tenant_id: TenantId
    ) -> TenantMembership | None:
        self.requests.append((identity, tenant_id))
        return self.membership


@pytest.mark.parametrize(
    ("issuer", "subject", "message"),
    [
        ("http://id.example.test", "user", "HTTPS"),
        ("https://user:password@id.example.test", "user", "HTTPS"),
        ("https://id.example.test?query=yes", "user", "HTTPS"),
        ("https://id.example.test#fragment", "user", "HTTPS"),
        (" https://id.example.test", "user", "HTTPS"),
        (f"https://{'a' * 2040}.test", "user", "HTTPS"),
        ("https://id.example.test", "", "between 1 and 255"),
        ("https://id.example.test", " user", "between 1 and 255"),
        ("https://id.example.test", "x" * 256, "between 1 and 255"),
        ("https://id.example.test", "user\n", "between 1 and 255"),
        ("https://id.example.test", "user\x7f", "control"),
    ],
)
def test_federated_identity_rejects_unbounded_values(
    issuer: str, subject: str, message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        FederatedIdentity(issuer, subject)


def test_federated_identity_rejects_invalid_types_and_url_syntax() -> None:
    with pytest.raises(InvalidDomainValueError, match="valid strings"):
        FederatedIdentity("https://[invalid", "user")
    with pytest.raises(InvalidDomainValueError, match="valid strings"):
        FederatedIdentity("https://id.example.test", None)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_resolver_creates_principal_only_from_server_membership() -> None:
    identity = FederatedIdentity("https://id.example.test", "external-user")
    membership = TenantMembership(
        ActorId("actor-1"), TenantId("tenant-1"), frozenset({Role.OPERATOR})
    )
    store = MembershipStore(membership)

    principal = await FederatedPrincipalResolver(store).resolve(
        identity, tenant_id=TenantId("tenant-1")
    )

    assert principal.actor_id == ActorId("actor-1")
    assert principal.roles == {Role.OPERATOR}
    assert store.requests == [(identity, TenantId("tenant-1"))]


@pytest.mark.anyio
async def test_resolver_rejects_missing_or_cross_tenant_memberships() -> None:
    identity = FederatedIdentity("https://id.example.test", "external-user")
    with pytest.raises(AuthenticationError, match="no active tenant"):
        await FederatedPrincipalResolver(MembershipStore(None)).resolve(
            identity, tenant_id=TenantId("tenant-1")
        )

    cross_tenant = replace(
        TenantMembership(ActorId("actor-1"), TenantId("tenant-1"), frozenset({Role.VIEWER})),
        tenant_id=TenantId("tenant-2"),
    )
    with pytest.raises(AuthenticationError, match="different tenant"):
        await FederatedPrincipalResolver(MembershipStore(cross_tenant)).resolve(
            identity, tenant_id=TenantId("tenant-1")
        )
