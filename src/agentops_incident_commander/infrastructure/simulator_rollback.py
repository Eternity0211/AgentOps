"""Deterministic deployment backend restricted to local simulator recovery E2E."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Protocol

from agentops_incident_commander.domain import (
    IdempotencyKey,
    InvalidDomainValueError,
    OpaqueIdentifier,
    ResolvedRollbackTarget,
    SemanticVersion,
)


class SimulatorDeploymentStatePort(Protocol):
    def current(self) -> object: ...

    def transition(
        self,
        *,
        service: str,
        expected_version: str,
        stable_version: str,
        deployment_id: str,
    ) -> object: ...


class LocalSimulatorRollbackBackend:
    """Apply one exact configured target without exposing provider or shell controls."""

    def __init__(
        self,
        state: SimulatorDeploymentStatePort,
        configured_target: ResolvedRollbackTarget,
    ) -> None:
        if not isinstance(configured_target, ResolvedRollbackTarget):
            raise InvalidDomainValueError("simulator rollback configured target is invalid")
        self._state = state
        self._configured_target = configured_target
        self._results: dict[IdempotencyKey, OpaqueIdentifier] = {}
        self._lock = asyncio.Lock()

    async def rollback(
        self,
        target: ResolvedRollbackTarget,
        *,
        idempotency_key: IdempotencyKey,
    ) -> OpaqueIdentifier:
        self._validate_inputs(target, idempotency_key)
        async with self._lock:
            replay = self._results.get(idempotency_key)
            if replay is not None:
                return replay
            marker = self._state.current()
            if self._marker_scope(marker) != (
                target.service,
                target.expected_current_version.value,
            ):
                raise InvalidDomainValueError("simulator deployment state changed before rollback")
            operation = self._operation(target, idempotency_key)
            try:
                transitioned = self._state.transition(
                    service=target.service,
                    expected_version=target.expected_current_version.value,
                    stable_version=target.stable_version.value,
                    deployment_id=operation.value,
                )
            except ValueError as error:
                raise InvalidDomainValueError(
                    "simulator deployment transition was refused"
                ) from error
            try:
                transitioned_scope = self._marker_scope(transitioned)
            except InvalidDomainValueError:
                raise InvalidDomainValueError(
                    "simulator deployment transition result is invalid"
                ) from None
            if transitioned_scope != (target.service, target.stable_version.value):
                raise InvalidDomainValueError("simulator deployment transition result is invalid")
            self._results[idempotency_key] = operation
            return operation

    async def deployed_version(self, target: ResolvedRollbackTarget) -> SemanticVersion:
        if not isinstance(target, ResolvedRollbackTarget) or target != self._configured_target:
            raise InvalidDomainValueError("simulator deployment observation target is invalid")
        marker = self._state.current()
        service, version = self._marker_scope(marker)
        if service != target.service:
            raise InvalidDomainValueError("simulator deployment observation scope is invalid")
        return SemanticVersion(version)

    def _validate_inputs(
        self,
        target: ResolvedRollbackTarget,
        idempotency_key: IdempotencyKey,
    ) -> None:
        if (
            not isinstance(target, ResolvedRollbackTarget)
            or not isinstance(idempotency_key, IdempotencyKey)
            or target != self._configured_target
        ):
            raise InvalidDomainValueError("simulator rollback request is not server-configured")

    @staticmethod
    def _marker_scope(marker: object) -> tuple[str, str]:
        service = getattr(marker, "service", None)
        version = getattr(marker, "version", None)
        if not isinstance(service, str) or not isinstance(version, str):
            raise InvalidDomainValueError("simulator deployment state is invalid")
        return service, SemanticVersion(version).value

    @staticmethod
    def _operation(
        target: ResolvedRollbackTarget,
        idempotency_key: IdempotencyKey,
    ) -> OpaqueIdentifier:
        document = {
            "environment": target.environment.value,
            "idempotency_key": idempotency_key.value,
            "service": target.service,
            "stable_version": target.stable_version.value,
            "target_reference": target.target_reference.value,
            "tenant_id": target.tenant_id.value,
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return OpaqueIdentifier(f"sim-rollback-{hashlib.sha256(canonical).hexdigest()}")
