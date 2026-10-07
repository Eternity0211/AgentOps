"""Single-attempt bounded dispatch for the disabled rollback mutation capability."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    ActionSnapshot,
    InvalidDomainValueError,
    OpaqueIdentifier,
    SemanticVersion,
    as_utc,
)

from .action_execution import AuthorizedRollbackExecution


@dataclass(frozen=True, slots=True)
class RecoveryMutationCapability:
    """Server-side kill switch; production composition remains disabled through Phase 9."""

    enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise InvalidDomainValueError("recovery mutation capability flag is invalid")


@dataclass(frozen=True, slots=True)
class RollbackAdapterResult:
    service: str
    deployed_version: SemanticVersion
    operation_reference: OpaqueIdentifier

    def __post_init__(self) -> None:
        if (
            not isinstance(self.service, str)
            or not self.service
            or len(self.service) > 128
            or not isinstance(self.deployed_version, SemanticVersion)
            or not isinstance(self.operation_reference, OpaqueIdentifier)
        ):
            raise InvalidDomainValueError("rollback adapter result is invalid")


class ConfirmedRollbackFailure(RuntimeError):
    """Adapter-confirmed refusal before any mutation took effect."""


class RollbackWriteAdapter(Protocol):
    async def rollback(
        self,
        authority: AuthorizedRollbackExecution,
    ) -> RollbackAdapterResult: ...


class ActionSnapshotWriter(Protocol):
    async def persist_after_snapshot(
        self,
        authority: AuthorizedRollbackExecution,
        result: RollbackAdapterResult,
        *,
        observed_at: datetime,
    ) -> ActionSnapshot: ...


class BoundedRollbackDispatcher:
    """Invoke one typed adapter once and classify its result without declaring recovery."""

    def __init__(
        self,
        adapter: RollbackWriteAdapter,
        snapshots: ActionSnapshotWriter,
        capability: RecoveryMutationCapability,
        *,
        timeout_seconds: float,
    ) -> None:
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
            or timeout_seconds > 300
        ):
            raise InvalidDomainValueError("rollback dispatch timeout is invalid")
        self._adapter = adapter
        self._snapshots = snapshots
        self._capability = capability
        self._timeout_seconds = float(timeout_seconds)

    async def dispatch(
        self,
        authority: AuthorizedRollbackExecution,
        execution: ActionExecution,
        *,
        completed_at: datetime,
    ) -> ActionExecution:
        if not isinstance(authority, AuthorizedRollbackExecution) or not isinstance(
            execution, ActionExecution
        ):
            raise InvalidDomainValueError("rollback dispatch inputs are invalid")
        if not self._capability.enabled:
            raise InvalidDomainValueError("rollback mutation capability is disabled")
        if execution.status is not ActionExecutionStatus.STARTED or (
            execution.tenant_id != authority.incident.tenant_id
            or execution.incident_id != authority.incident.id
            or execution.approval_id != authority.approval.id
            or execution.idempotency_key != authority.request.idempotency_key
            or execution.actor_id != authority.actor_id
            or execution.proposal_fingerprint != authority.admitted.proposal.fingerprint
            or execution.policy_decision_fingerprint != authority.policy_decision.fingerprint
            or execution.target != authority.target
        ):
            raise InvalidDomainValueError("rollback execution does not match preflight authority")
        finished_at = as_utc(completed_at)
        if finished_at < execution.started_at:
            raise InvalidDomainValueError("rollback completion cannot predate execution start")
        try:
            result = await asyncio.wait_for(
                self._adapter.rollback(authority),
                timeout=self._timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return execution.fail(
                ActionExecutionStatus.TIMED_OUT,
                failure_code="ADAPTER_TIMEOUT",
                at=finished_at,
            )
        except ConfirmedRollbackFailure:
            return execution.fail(
                ActionExecutionStatus.FAILED,
                failure_code="ADAPTER_REJECTED",
                at=finished_at,
            )
        except Exception:
            return execution.fail(
                ActionExecutionStatus.UNCERTAIN,
                failure_code="ADAPTER_RESULT_UNKNOWN",
                at=finished_at,
            )
        if (
            not isinstance(result, RollbackAdapterResult)
            or result.service != authority.target.service
            or result.deployed_version != authority.target.stable_version
        ):
            return execution.fail(
                ActionExecutionStatus.UNCERTAIN,
                failure_code="ADAPTER_RESULT_MISMATCH",
                at=finished_at,
            )
        try:
            after = await self._snapshots.persist_after_snapshot(
                authority,
                result,
                observed_at=finished_at,
            )
            return execution.succeed(after_snapshot=after, at=finished_at)
        except Exception:
            return execution.fail(
                ActionExecutionStatus.UNCERTAIN,
                failure_code="AFTER_SNAPSHOT_UNAVAILABLE",
                at=finished_at,
            )
