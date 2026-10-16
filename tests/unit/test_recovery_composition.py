"""Tests for the worker-owned recovery composition boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application import (
    NOOP_CONTROL_PLANE_OBSERVER,
    ControlPlaneObservation,
    ControlPlaneObserver,
    PersistedRollbackHealthVerifier,
    RecoveryMutationCapability,
    RollbackPreflight,
    RollbackRecoveryCoordinator,
)
from agentops_incident_commander.apps.config import WorkerSettings
from agentops_incident_commander.apps.recovery import (
    RollbackRecoveryRuntime,
    compose_rollback_recovery_runtime,
)
from agentops_incident_commander.domain import (
    AuditEventId,
    InvalidDomainValueError,
    OpaqueIdentifier,
)
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage
from agentops_incident_commander.infrastructure.rollback_adapter import DeploymentRollbackBackend

NOW = datetime(2026, 10, 9, tzinfo=UTC)


class RecordingObserver:
    def __init__(self) -> None:
        self.values: list[ControlPlaneObservation] = []

    def record(self, value: ControlPlaneObservation) -> None:
        self.values.append(value)


class Verifier:
    async def verify(self, *_: object, **__: object) -> object:
        return object()


def compose(
    tmp_path: Path,
    *,
    enabled: bool,
    observer: ControlPlaneObserver = NOOP_CONTROL_PLANE_OBSERVER,
) -> RollbackRecoveryRuntime:
    def verifier_factory(selected: ControlPlaneObserver) -> PersistedRollbackHealthVerifier:
        assert selected is observer
        return cast(PersistedRollbackHealthVerifier, Verifier())

    return compose_rollback_recovery_runtime(
        WorkerSettings(
            "postgresql+asyncpg://agentops:local-only@postgres/agentops",
            "worker-1",
            1,
            recovery_mutation_enabled=enabled,
            recovery_dispatch_timeout_seconds=17,
        ),
        sessions=cast(async_sessionmaker[AsyncSession], object()),
        preflight=cast(RollbackPreflight, object()),
        backend=cast(DeploymentRollbackBackend, object()),
        artifact_storage=LocalArtifactStorage(tmp_path),
        verifier_factory=verifier_factory,
        execution_id_factory=lambda: OpaqueIdentifier("execution-1"),
        audit_event_id_factory=lambda: AuditEventId("audit-1"),
        clock=lambda: NOW,
        observer=observer,
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_recovery_runtime_uses_only_explicit_worker_capability(
    tmp_path: Path, enabled: bool
) -> None:
    observer = RecordingObserver()
    runtime = compose(tmp_path, enabled=enabled, observer=observer)

    assert isinstance(runtime.coordinator, RollbackRecoveryCoordinator)
    assert runtime.capability == RecoveryMutationCapability(enabled)
    assert runtime.observer is observer


def test_recovery_runtime_rejects_invalid_composition_values(tmp_path: Path) -> None:
    with pytest.raises(InvalidDomainValueError, match="worker settings"):
        compose_rollback_recovery_runtime(
            cast(WorkerSettings, "invalid"),
            sessions=cast(async_sessionmaker[AsyncSession], object()),
            preflight=cast(RollbackPreflight, object()),
            backend=cast(DeploymentRollbackBackend, object()),
            artifact_storage=LocalArtifactStorage(tmp_path),
            verifier_factory=lambda _: cast(PersistedRollbackHealthVerifier, Verifier()),
            execution_id_factory=lambda: OpaqueIdentifier("execution-1"),
            audit_event_id_factory=lambda: AuditEventId("audit-1"),
            clock=lambda: NOW,
        )
    with pytest.raises(InvalidDomainValueError, match="runtime is invalid"):
        RollbackRecoveryRuntime(
            cast(RollbackRecoveryCoordinator, "invalid"),
            RecoveryMutationCapability(False),
        )
    with pytest.raises(InvalidDomainValueError, match="runtime is invalid"):
        RollbackRecoveryRuntime(
            compose(tmp_path, enabled=False).coordinator,
            cast(RecoveryMutationCapability, "invalid"),
        )
    with pytest.raises(InvalidDomainValueError, match="runtime is invalid"):
        RollbackRecoveryRuntime(
            compose(tmp_path, enabled=False).coordinator,
            RecoveryMutationCapability(False),
            cast(ControlPlaneObserver, object()),
        )
    with pytest.raises(InvalidDomainValueError, match="observer composition"):
        compose_rollback_recovery_runtime(
            WorkerSettings(
                "postgresql+asyncpg://agentops:local-only@postgres/agentops",
                "worker-1",
                1,
            ),
            sessions=cast(async_sessionmaker[AsyncSession], object()),
            preflight=cast(RollbackPreflight, object()),
            backend=cast(DeploymentRollbackBackend, object()),
            artifact_storage=LocalArtifactStorage(tmp_path),
            verifier_factory=cast(Any, object()),
            execution_id_factory=lambda: OpaqueIdentifier("execution-1"),
            audit_event_id_factory=lambda: AuditEventId("audit-1"),
            clock=lambda: NOW,
        )
    with pytest.raises(InvalidDomainValueError, match="verifier composition"):
        compose_rollback_recovery_runtime(
            WorkerSettings(
                "postgresql+asyncpg://agentops:local-only@postgres/agentops",
                "worker-1",
                1,
            ),
            sessions=cast(async_sessionmaker[AsyncSession], object()),
            preflight=cast(RollbackPreflight, object()),
            backend=cast(DeploymentRollbackBackend, object()),
            artifact_storage=LocalArtifactStorage(tmp_path),
            verifier_factory=lambda _: cast(PersistedRollbackHealthVerifier, object()),
            execution_id_factory=lambda: OpaqueIdentifier("execution-1"),
            audit_event_id_factory=lambda: AuditEventId("audit-1"),
            clock=lambda: NOW,
        )
