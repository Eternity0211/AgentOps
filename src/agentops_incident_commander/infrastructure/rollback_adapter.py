"""Typed deployment-control adapter for the single allowlisted rollback action."""

from __future__ import annotations

from typing import Protocol

from agentops_incident_commander.application import (
    AuthorizedRollbackExecution,
    RollbackAdapterResult,
)
from agentops_incident_commander.domain import (
    IdempotencyKey,
    InvalidDomainValueError,
    OpaqueIdentifier,
    ResolvedRollbackTarget,
    SemanticVersion,
)


class DeploymentRollbackBackend(Protocol):
    """Narrow deployment port; it admits no URL, command, manifest, or free-form target."""

    async def rollback(
        self,
        target: ResolvedRollbackTarget,
        *,
        idempotency_key: IdempotencyKey,
    ) -> OpaqueIdentifier: ...

    async def deployed_version(
        self,
        target: ResolvedRollbackTarget,
    ) -> SemanticVersion: ...


class ServerBoundRollbackAdapter:
    """Apply exactly the preflight-resolved target and observe the resulting version."""

    def __init__(self, backend: DeploymentRollbackBackend) -> None:
        self._backend = backend

    async def rollback(
        self,
        authority: AuthorizedRollbackExecution,
    ) -> RollbackAdapterResult:
        if not isinstance(authority, AuthorizedRollbackExecution):
            raise InvalidDomainValueError("rollback adapter authority is invalid")
        operation = await self._backend.rollback(
            authority.target,
            idempotency_key=authority.request.idempotency_key,
        )
        if not isinstance(operation, OpaqueIdentifier):
            raise InvalidDomainValueError("rollback backend operation identity is invalid")
        deployed = await self._backend.deployed_version(authority.target)
        if not isinstance(deployed, SemanticVersion):
            raise InvalidDomainValueError("rollback backend deployed version is invalid")
        return RollbackAdapterResult(
            authority.target.service,
            deployed,
            operation,
        )
