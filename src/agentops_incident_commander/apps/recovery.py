"""Worker-owned composition for the non-bypassable rollback recovery route."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application import (
    NOOP_CONTROL_PLANE_OBSERVER,
    BoundedRollbackDispatcher,
    ControlPlaneObserver,
    PersistedRollbackHealthVerifier,
    RecoveryMutationCapability,
    RollbackActionExecutor,
    RollbackPreflight,
    RollbackRecoveryCoordinator,
)
from agentops_incident_commander.domain import (
    ArtifactStorage,
    AuditEventId,
    InvalidDomainValueError,
    OpaqueIdentifier,
)
from agentops_incident_commander.infrastructure.action_snapshots import (
    ImmutableActionSnapshotWriter,
)
from agentops_incident_commander.infrastructure.persistence import (
    PostgresFailedHealthVerificationRouter,
    PostgresLifecycleActionExecutionStore,
    PostgresSuccessfulHealthVerificationRouter,
)
from agentops_incident_commander.infrastructure.rollback_adapter import (
    DeploymentRollbackBackend,
    ServerBoundRollbackAdapter,
)

from .config import WorkerSettings


@dataclass(frozen=True, slots=True)
class RollbackRecoveryRuntime:
    """Composed route plus its observable server-side capability state."""

    coordinator: RollbackRecoveryCoordinator
    capability: RecoveryMutationCapability
    observer: ControlPlaneObserver = NOOP_CONTROL_PLANE_OBSERVER

    def __post_init__(self) -> None:
        if (
            not isinstance(self.coordinator, RollbackRecoveryCoordinator)
            or not isinstance(self.capability, RecoveryMutationCapability)
            or not callable(getattr(self.observer, "record", None))
        ):
            raise InvalidDomainValueError("rollback recovery runtime is invalid")


def compose_rollback_recovery_runtime(
    settings: WorkerSettings,
    *,
    sessions: async_sessionmaker[AsyncSession],
    preflight: RollbackPreflight,
    backend: DeploymentRollbackBackend,
    artifact_storage: ArtifactStorage,
    verifier_factory: Callable[[ControlPlaneObserver], PersistedRollbackHealthVerifier],
    execution_id_factory: Callable[[], OpaqueIdentifier],
    audit_event_id_factory: Callable[[], AuditEventId],
    clock: Callable[[], datetime],
    observer: ControlPlaneObserver = NOOP_CONTROL_PLANE_OBSERVER,
) -> RollbackRecoveryRuntime:
    """Wire the only write route; the capability remains false unless explicitly configured."""
    if not isinstance(settings, WorkerSettings):
        raise InvalidDomainValueError("rollback recovery worker settings are invalid")
    if not callable(verifier_factory) or not callable(getattr(observer, "record", None)):
        raise InvalidDomainValueError("rollback recovery observer composition is invalid")
    capability = RecoveryMutationCapability(settings.recovery_mutation_enabled)
    snapshots = ImmutableActionSnapshotWriter(backend, artifact_storage)
    dispatcher = BoundedRollbackDispatcher(
        ServerBoundRollbackAdapter(backend),
        snapshots,
        capability,
        timeout_seconds=settings.recovery_dispatch_timeout_seconds,
        clock=clock,
    )
    executor = RollbackActionExecutor(
        preflight,
        snapshots,
        PostgresLifecycleActionExecutionStore(sessions),
        dispatcher,
        execution_id_factory=execution_id_factory,
        audit_event_id_factory=audit_event_id_factory,
        clock=clock,
        observer=observer,
    )
    success = PostgresSuccessfulHealthVerificationRouter(
        sessions,
        clock=clock,
        audit_event_id_factory=audit_event_id_factory,
    )
    failure = PostgresFailedHealthVerificationRouter(
        sessions,
        clock=clock,
        audit_event_id_factory=audit_event_id_factory,
        observer=observer,
    )
    verifier = verifier_factory(observer)
    if not callable(getattr(verifier, "verify", None)):
        raise InvalidDomainValueError("rollback recovery verifier composition is invalid")
    return RollbackRecoveryRuntime(
        RollbackRecoveryCoordinator(executor, verifier, success, failure),
        capability,
        observer,
    )
