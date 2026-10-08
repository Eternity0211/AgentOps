"""Local simulator-only deterministic rollback backend tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast

import pytest

from agentops_incident_commander.domain import (
    IdempotencyKey,
    InvalidDomainValueError,
    OpaqueIdentifier,
    PolicyEnvironment,
    ResolvedRollbackTarget,
    SemanticVersion,
    TenantId,
)
from agentops_incident_commander.infrastructure import LocalSimulatorRollbackBackend
from agentops_incident_commander.simulator.deployment import (
    DeploymentMarker,
    SimulatorDeploymentState,
)


def target() -> ResolvedRollbackTarget:
    return ResolvedRollbackTarget(
        TenantId("tenant-1"),
        "order",
        PolicyEnvironment.PRODUCTION,
        OpaqueIdentifier("simulator-order-production"),
        SemanticVersion("2.0.0"),
        SemanticVersion("1.0.0"),
    )


def state() -> SimulatorDeploymentState:
    return SimulatorDeploymentState(DeploymentMarker("order", "fault-release-2", "2.0.0", "1.0.0"))


@pytest.mark.anyio
async def test_concurrent_identical_rollbacks_mutate_once_and_replay() -> None:
    configured = target()
    deployment = state()
    backend = LocalSimulatorRollbackBackend(deployment, configured)
    key = IdempotencyKey("rollback-request-1")

    operations = await asyncio.gather(
        *(backend.rollback(configured, idempotency_key=key) for _ in range(8))
    )
    replay = await backend.rollback(configured, idempotency_key=key)

    assert len(set(operations)) == 1
    assert replay == operations[0]
    assert deployment.transition_count == 1
    assert deployment.current() == DeploymentMarker(
        "order",
        operations[0].value,
        "1.0.0",
        "2.0.0",
    )
    assert await backend.deployed_version(configured) == configured.stable_version


@pytest.mark.anyio
async def test_new_key_cannot_mutate_an_already_changed_deployment() -> None:
    configured = target()
    deployment = state()
    backend = LocalSimulatorRollbackBackend(deployment, configured)
    await backend.rollback(configured, idempotency_key=IdempotencyKey("first"))

    with pytest.raises(InvalidDomainValueError, match="state changed"):
        await backend.rollback(configured, idempotency_key=IdempotencyKey("second"))
    assert deployment.transition_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changed",
    [
        replace(target(), tenant_id=TenantId("tenant-2")),
        replace(target(), service="payment"),
        replace(target(), environment=PolicyEnvironment.STAGING),
        replace(target(), target_reference=OpaqueIdentifier("different-target")),
        replace(target(), expected_current_version=SemanticVersion("3.0.0")),
        replace(target(), stable_version=SemanticVersion("0.9.0")),
    ],
)
async def test_backend_rejects_any_target_substitution(
    changed: ResolvedRollbackTarget,
) -> None:
    deployment = state()
    backend = LocalSimulatorRollbackBackend(deployment, target())
    with pytest.raises(InvalidDomainValueError, match="not server-configured"):
        await backend.rollback(changed, idempotency_key=IdempotencyKey("request"))
    assert deployment.transition_count == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("supplied_target", "key"),
    [("invalid", IdempotencyKey("key")), (target(), "invalid")],
)
async def test_backend_rejects_untyped_inputs(
    supplied_target: object,
    key: object,
) -> None:
    backend = LocalSimulatorRollbackBackend(state(), target())
    with pytest.raises(InvalidDomainValueError, match="not server-configured"):
        await backend.rollback(
            cast(ResolvedRollbackTarget, supplied_target),
            idempotency_key=cast(IdempotencyKey, key),
        )


def test_backend_rejects_untyped_configuration() -> None:
    with pytest.raises(InvalidDomainValueError, match="configured target"):
        LocalSimulatorRollbackBackend(state(), cast(ResolvedRollbackTarget, "invalid"))


class BrokenState:
    def __init__(self, current: object, transition: object = None) -> None:
        self.current_value = current
        self.transition_value = transition

    def current(self) -> object:
        return self.current_value

    def transition(self, **_: str) -> object:
        if isinstance(self.transition_value, Exception):
            raise self.transition_value
        return self.transition_value


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("current", "message"),
    [
        (object(), "state is invalid"),
        (DeploymentMarker("payment", "release", "2.0.0", None), "state changed"),
    ],
)
async def test_backend_rejects_invalid_current_state(current: object, message: str) -> None:
    backend = LocalSimulatorRollbackBackend(BrokenState(current), target())
    with pytest.raises(InvalidDomainValueError, match=message):
        await backend.rollback(target(), idempotency_key=IdempotencyKey("request"))


@pytest.mark.anyio
async def test_backend_classifies_refused_or_invalid_transition() -> None:
    configured = target()
    current = DeploymentMarker("order", "release", "2.0.0", None)
    refused = LocalSimulatorRollbackBackend(BrokenState(current, ValueError("refused")), configured)
    with pytest.raises(InvalidDomainValueError, match="transition was refused"):
        await refused.rollback(configured, idempotency_key=IdempotencyKey("refused"))

    invalid = LocalSimulatorRollbackBackend(BrokenState(current, object()), configured)
    with pytest.raises(InvalidDomainValueError, match="transition result is invalid"):
        await invalid.rollback(configured, idempotency_key=IdempotencyKey("invalid-result"))

    substituted = LocalSimulatorRollbackBackend(
        BrokenState(current, DeploymentMarker("order", "other", "3.0.0", "2.0.0")),
        configured,
    )
    with pytest.raises(InvalidDomainValueError, match="transition result is invalid"):
        await substituted.rollback(
            configured,
            idempotency_key=IdempotencyKey("substituted-result"),
        )


@pytest.mark.anyio
async def test_observation_rejects_target_and_state_substitution() -> None:
    configured = target()
    backend = LocalSimulatorRollbackBackend(state(), configured)
    with pytest.raises(InvalidDomainValueError, match="observation target"):
        await backend.deployed_version(replace(configured, service="payment"))

    wrong_service = BrokenState(DeploymentMarker("payment", "release", "2.0.0", None))
    backend = LocalSimulatorRollbackBackend(wrong_service, configured)
    with pytest.raises(InvalidDomainValueError, match="observation scope"):
        await backend.deployed_version(configured)
