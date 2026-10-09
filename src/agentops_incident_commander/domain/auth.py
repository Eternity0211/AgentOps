"""Framework-free authentication principal and fail-closed RBAC contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import AuthenticationError, AuthorizationError, InvalidDomainValueError
from .values import ActorId, TenantId


class Role(StrEnum):
    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


class Permission(StrEnum):
    INCIDENT_READ = "incident:read"
    EVIDENCE_READ = "evidence:read"
    AUDIT_READ = "audit:read"
    INVESTIGATION_START = "investigation:start"
    INVESTIGATION_CANCEL = "investigation:cancel"
    REMEDIATION_REQUEST = "remediation:request"
    APPROVAL_DECIDE = "approval:decide"
    APPROVED_ACTION_EXECUTE = "approved_action:execute"
    POSTMORTEM_EDIT = "postmortem:edit"
    ADMIN_MANAGE = "admin:manage"


_READ = frozenset({Permission.INCIDENT_READ, Permission.EVIDENCE_READ, Permission.AUDIT_READ})
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _READ,
    Role.OPERATOR: _READ
    | {
        Permission.INVESTIGATION_START,
        Permission.INVESTIGATION_CANCEL,
        Permission.REMEDIATION_REQUEST,
        Permission.APPROVED_ACTION_EXECUTE,
        Permission.POSTMORTEM_EDIT,
    },
    Role.APPROVER: _READ | {Permission.APPROVAL_DECIDE},
    Role.ADMIN: _READ | {Permission.ADMIN_MANAGE},
}


@dataclass(frozen=True, slots=True)
class Principal:
    """One authenticated tenant-scoped identity with explicit assigned roles."""

    actor_id: ActorId
    tenant_id: TenantId
    roles: frozenset[Role]

    def __post_init__(self) -> None:
        if not self.roles:
            raise InvalidDomainValueError("authenticated principal must have at least one role")

    @property
    def permissions(self) -> frozenset[Permission]:
        granted: set[Permission] = set()
        for role in self.roles:
            granted.update(ROLE_PERMISSIONS[role])
        return frozenset(granted)


def require_authenticated(principal: Principal | None) -> Principal:
    if principal is None:
        raise AuthenticationError("authentication is required")
    return principal


def require_permission(
    principal: Principal | None, permission: Permission, *, tenant_id: TenantId
) -> Principal:
    authenticated = require_authenticated(principal)
    if authenticated.tenant_id != tenant_id:
        raise AuthorizationError("principal cannot access another tenant")
    if permission not in authenticated.permissions:
        raise AuthorizationError(f"principal lacks permission {permission.value}")
    return authenticated


def require_independent_approver(proposer: Principal, approver: Principal) -> None:
    if proposer.tenant_id != approver.tenant_id:
        raise AuthorizationError("approver and proposer must belong to the same tenant")
    if proposer.actor_id == approver.actor_id:
        raise AuthorizationError("proposer cannot approve their own action")
    require_permission(approver, Permission.APPROVAL_DECIDE, tenant_id=proposer.tenant_id)
