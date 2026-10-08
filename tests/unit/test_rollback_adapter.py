"""Typed server-bound rollback adapter tests."""

from __future__ import annotations

from typing import Any, cast

import pytest
from test_action_dispatch import authority

from agentops_incident_commander.application import AuthorizedRollbackExecution
from agentops_incident_commander.domain import (
    IdempotencyKey,
    InvalidDomainValueError,
    OpaqueIdentifier,
    ResolvedRollbackTarget,
    SemanticVersion,
)
from agentops_incident_commander.infrastructure import ServerBoundRollbackAdapter


class Backend:
    def __init__(self, operation: object, version: object) -> None:
        self.operation = operation
        self.version = version
        self.rollback_calls: list[tuple[ResolvedRollbackTarget, IdempotencyKey]] = []
        self.version_calls: list[ResolvedRollbackTarget] = []

    async def rollback(
        self,
        target: ResolvedRollbackTarget,
        *,
        idempotency_key: IdempotencyKey,
    ) -> OpaqueIdentifier:
        self.rollback_calls.append((target, idempotency_key))
        return cast(OpaqueIdentifier, self.operation)

    async def deployed_version(
        self,
        target: ResolvedRollbackTarget,
    ) -> SemanticVersion:
        self.version_calls.append(target)
        return cast(SemanticVersion, self.version)


@pytest.mark.anyio
async def test_adapter_delegates_only_server_resolved_target_and_idempotency() -> None:
    authorized = authority()
    backend = Backend(OpaqueIdentifier("deployment-operation-1"), SemanticVersion("1.0.0"))

    result = await ServerBoundRollbackAdapter(backend).rollback(authorized)

    assert backend.rollback_calls == [(authorized.target, authorized.request.idempotency_key)]
    assert backend.version_calls == [authorized.target]
    assert result.service == authorized.target.service
    assert result.deployed_version == authorized.target.stable_version
    assert result.operation_reference == OpaqueIdentifier("deployment-operation-1")


@pytest.mark.anyio
async def test_adapter_rejects_untyped_authority_before_backend() -> None:
    backend = Backend(OpaqueIdentifier("unused-operation"), SemanticVersion("1.0.0"))
    with pytest.raises(InvalidDomainValueError, match="authority is invalid"):
        await ServerBoundRollbackAdapter(backend).rollback(cast(AuthorizedRollbackExecution, "bad"))
    assert backend.rollback_calls == []
    assert backend.version_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("operation", "version", "message", "version_calls"),
    [
        ("bad", SemanticVersion("1.0.0"), "operation identity", 0),
        (OpaqueIdentifier("operation-2"), "bad", "deployed version", 1),
    ],
)
async def test_adapter_rejects_untyped_backend_results(
    operation: object,
    version: object,
    message: str,
    version_calls: int,
) -> None:
    backend = Backend(operation, version)
    with pytest.raises(InvalidDomainValueError, match=message):
        await ServerBoundRollbackAdapter(backend).rollback(authority())
    assert len(backend.rollback_calls) == 1
    assert len(backend.version_calls) == version_calls


def test_adapter_exports_only_typed_backend_surface() -> None:
    public = set(ServerBoundRollbackAdapter.rollback.__annotations__)
    assert public == {"authority", "return"}
    assert not {"command", "url", "manifest", "namespace"} & public


@pytest.mark.parametrize("backend", [None, object()])
def test_constructor_defers_backend_behavior_to_protocol(backend: Any) -> None:
    assert isinstance(ServerBoundRollbackAdapter(backend), ServerBoundRollbackAdapter)
