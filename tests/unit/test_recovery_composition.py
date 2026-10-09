"""Tests for the worker-owned recovery composition boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application import (
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


def compose(tmp_path: Path, *, enabled: bool) -> RollbackRecoveryRuntime:
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
        verifier=cast(PersistedRollbackHealthVerifier, object()),
        execution_id_factory=lambda: OpaqueIdentifier("execution-1"),
        audit_event_id_factory=lambda: AuditEventId("audit-1"),
        clock=lambda: NOW,
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_recovery_runtime_uses_only_explicit_worker_capability(
    tmp_path: Path, enabled: bool
) -> None:
    runtime = compose(tmp_path, enabled=enabled)

    assert isinstance(runtime.coordinator, RollbackRecoveryCoordinator)
    assert runtime.capability == RecoveryMutationCapability(enabled)


def test_recovery_runtime_rejects_invalid_composition_values(tmp_path: Path) -> None:
    with pytest.raises(InvalidDomainValueError, match="worker settings"):
        compose_rollback_recovery_runtime(
            cast(WorkerSettings, "invalid"),
            sessions=cast(async_sessionmaker[AsyncSession], object()),
            preflight=cast(RollbackPreflight, object()),
            backend=cast(DeploymentRollbackBackend, object()),
            artifact_storage=LocalArtifactStorage(tmp_path),
            verifier=cast(PersistedRollbackHealthVerifier, object()),
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
