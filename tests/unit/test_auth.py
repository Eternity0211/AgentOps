"""Tests for tenant-scoped authentication and fail-closed RBAC."""

from __future__ import annotations

import pytest

from agentops_incident_commander.domain import (
    ROLE_PERMISSIONS,
    ActorId,
    AuthenticationError,
    AuthorizationError,
    InvalidDomainValueError,
    Permission,
    Principal,
    Role,
    TenantId,
    require_authenticated,
    require_independent_approver,
    require_permission,
)


def principal(actor: str, *roles: Role, tenant: str = "tenant-1") -> Principal:
    return Principal(ActorId(actor), TenantId(tenant), frozenset(roles))


def test_every_role_has_an_explicit_least_privilege_matrix() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)
    assert ROLE_PERMISSIONS[Role.VIEWER] == {
        Permission.INCIDENT_READ,
        Permission.EVIDENCE_READ,
        Permission.AUDIT_READ,
    }
    assert Permission.APPROVAL_DECIDE in ROLE_PERMISSIONS[Role.APPROVER]
    assert Permission.APPROVED_ACTION_EXECUTE in ROLE_PERMISSIONS[Role.OPERATOR]
    assert ROLE_PERMISSIONS[Role.ADMIN] - ROLE_PERMISSIONS[Role.VIEWER] == {Permission.ADMIN_MANAGE}


def test_multiple_roles_union_permissions_without_implicit_grants() -> None:
    value = principal("dual-role", Role.OPERATOR, Role.APPROVER)
    assert Permission.APPROVAL_DECIDE in value.permissions
    assert Permission.APPROVED_ACTION_EXECUTE in value.permissions
    assert Permission.ADMIN_MANAGE not in value.permissions


def test_principal_requires_at_least_one_role() -> None:
    with pytest.raises(InvalidDomainValueError, match="at least one role"):
        principal("roleless")


def test_anonymous_request_is_rejected() -> None:
    with pytest.raises(AuthenticationError, match="required"):
        require_authenticated(None)
    with pytest.raises(AuthenticationError, match="required"):
        require_permission(None, Permission.INCIDENT_READ, tenant_id=TenantId("tenant-1"))


def test_permission_is_tenant_scoped_and_defaults_to_deny() -> None:
    viewer = principal("viewer", Role.VIEWER)
    assert (
        require_permission(viewer, Permission.INCIDENT_READ, tenant_id=TenantId("tenant-1"))
        is viewer
    )
    with pytest.raises(AuthorizationError, match="another tenant"):
        require_permission(viewer, Permission.INCIDENT_READ, tenant_id=TenantId("tenant-2"))
    with pytest.raises(AuthorizationError, match="lacks permission"):
        require_permission(viewer, Permission.INVESTIGATION_START, tenant_id=TenantId("tenant-1"))


def test_independent_approver_enforces_tenant_role_and_separation() -> None:
    proposer = principal("operator", Role.OPERATOR)
    require_independent_approver(proposer, principal("approver", Role.APPROVER))

    with pytest.raises(AuthorizationError, match="same tenant"):
        require_independent_approver(
            proposer, principal("approver", Role.APPROVER, tenant="tenant-2")
        )
    with pytest.raises(AuthorizationError, match="own action"):
        require_independent_approver(proposer, principal("operator", Role.APPROVER))
    with pytest.raises(AuthorizationError, match="lacks permission"):
        require_independent_approver(proposer, principal("viewer", Role.VIEWER))


def test_require_authenticated_returns_valid_principal() -> None:
    value = principal("viewer", Role.VIEWER)
    assert require_authenticated(value) is value
