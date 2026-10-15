"""Crash-safe orchestration for one authorized rollback execution attempt."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    ActionSnapshot,
    ActorId,
    AggregateVersion,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    PolicyDecision,
    PolicyEvaluationInput,
    Principal,
    RollbackServiceRequest,
    Sha256Digest,
    TenantId,
    as_utc,
)
from agentops_incident_commander.workflows import RemediationProposal

from .action_execution import AuthorizedRollbackExecution
from .control_plane_observability import (
    NOOP_CONTROL_PLANE_OBSERVER,
    ControlPlaneComponent,
    ControlPlaneObservation,
    ControlPlaneObserver,
    ControlPlaneOperation,
    ControlPlaneOutcome,
    safely_record,
    utc_observation_time,
)

ACTION_EXECUTION_AUDIT_SCHEMA_VERSION = "action_execution/v1"


class RollbackPreflight(Protocol):
    async def authorize(
        self,
        request: RollbackServiceRequest,
        proposal: RemediationProposal,
        policy_input: PolicyEvaluationInput,
        policy_decision: PolicyDecision,
        *,
        principal: Principal | None,
    ) -> AuthorizedRollbackExecution: ...


class BeforeActionSnapshotWriter(Protocol):
    async def persist_before_snapshot(
        self,
        authority: AuthorizedRollbackExecution,
        *,
        observed_at: datetime,
    ) -> ActionSnapshot: ...


class DurableActionExecutionStore(Protocol):
    """Each method must commit its lifecycle event and audit atomically before returning."""

    async def claim(
        self,
        execution: ActionExecution,
        audit_event: AuditEvent,
        replay_audit_factory: Callable[[ActionExecution], AuditEvent],
    ) -> tuple[ActionExecution, bool]: ...

    async def finish(
        self,
        expected: ActionExecution,
        completed: ActionExecution,
        audit_event: AuditEvent,
    ) -> ActionExecution: ...


class RollbackDispatcher(Protocol):
    def ensure_enabled(self) -> None: ...

    async def dispatch(
        self,
        authority: AuthorizedRollbackExecution,
        execution: ActionExecution,
    ) -> ActionExecution: ...


class RollbackActionExecutor:
    """Durably claim before dispatch and never redispatch an observed replay."""

    def __init__(
        self,
        preflight: RollbackPreflight,
        snapshots: BeforeActionSnapshotWriter,
        store: DurableActionExecutionStore,
        dispatcher: RollbackDispatcher,
        *,
        execution_id_factory: Callable[[], OpaqueIdentifier],
        audit_event_id_factory: Callable[[], AuditEventId],
        clock: Callable[[], datetime],
        observer: ControlPlaneObserver = NOOP_CONTROL_PLANE_OBSERVER,
    ) -> None:
        self._preflight = preflight
        self._snapshots = snapshots
        self._store = store
        self._dispatcher = dispatcher
        self._execution_id_factory = execution_id_factory
        self._audit_event_id_factory = audit_event_id_factory
        self._clock = clock
        self._observer = observer

    async def execute(
        self,
        request: RollbackServiceRequest,
        proposal: RemediationProposal,
        policy_input: PolicyEvaluationInput,
        policy_decision: PolicyDecision,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> ActionExecution:
        if not isinstance(correlation_id, CorrelationId) or not isinstance(
            causation_id, CausationId
        ):
            raise InvalidDomainValueError("rollback execution trace identities are invalid")
        started_ns = time.monotonic_ns()
        observation_scope = self._observation_scope(request, policy_input)
        self._observe(
            observation_scope,
            ControlPlaneOutcome.STARTED,
            correlation_id=correlation_id,
            causation_id=causation_id,
            started_ns=started_ns,
            route="EXECUTION",
            result_code="STARTED",
        )
        try:
            self._dispatcher.ensure_enabled()
        except Exception:
            self._observe(
                observation_scope,
                ControlPlaneOutcome.REFUSED,
                correlation_id=correlation_id,
                causation_id=causation_id,
                started_ns=started_ns,
                route="DISABLED",
                result_code="CAPABILITY_DISABLED",
            )
            raise
        try:
            completed, replayed = await self._execute_enabled(
                request,
                proposal,
                policy_input,
                policy_decision,
                principal=principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        except asyncio.CancelledError:
            self._observe(
                observation_scope,
                ControlPlaneOutcome.CANCELLED,
                correlation_id=correlation_id,
                causation_id=causation_id,
                started_ns=started_ns,
                route="SAFE_BOUNDARY",
                result_code="CANCELLED",
            )
            raise
        except TimeoutError:
            self._observe(
                observation_scope,
                ControlPlaneOutcome.TIMED_OUT,
                correlation_id=correlation_id,
                causation_id=causation_id,
                started_ns=started_ns,
                route="NEEDS_HUMAN",
                result_code="EXECUTION_TIMEOUT",
            )
            raise
        except Exception:
            self._observe(
                observation_scope,
                ControlPlaneOutcome.FAILED,
                correlation_id=correlation_id,
                causation_id=causation_id,
                started_ns=started_ns,
                route="FAIL_CLOSED",
                result_code="EXECUTION_FAILED",
            )
            raise
        outcome, route = self._terminal_observation(completed, replayed=replayed)
        self._observe(
            observation_scope,
            outcome,
            correlation_id=correlation_id,
            causation_id=causation_id,
            started_ns=started_ns,
            route=route,
            result_code=(
                f"REPLAY_{completed.status.value}"
                if replayed
                else completed.failure_code or completed.status.value
            ),
        )
        return completed

    async def _execute_enabled(
        self,
        request: RollbackServiceRequest,
        proposal: RemediationProposal,
        policy_input: PolicyEvaluationInput,
        policy_decision: PolicyDecision,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> tuple[ActionExecution, bool]:
        authority = await self._preflight.authorize(
            request,
            proposal,
            policy_input,
            policy_decision,
            principal=principal,
        )
        observed_at = as_utc(self._clock())
        before = await self._snapshots.persist_before_snapshot(
            authority,
            observed_at=observed_at,
        )
        started_at = as_utc(self._clock())
        execution_id = self._execution_id_factory()
        if not isinstance(execution_id, OpaqueIdentifier):
            raise InvalidDomainValueError("rollback execution identity is invalid")
        incoming = ActionExecution(
            id=execution_id,
            tenant_id=authority.incident.tenant_id,
            incident_id=authority.incident.id,
            approval_id=authority.approval.id,
            idempotency_key=authority.request.idempotency_key,
            actor_id=authority.actor_id,
            proposal_fingerprint=authority.admitted.proposal.fingerprint,
            policy_decision_fingerprint=authority.policy_decision.fingerprint,
            target=authority.target,
            before_snapshot=before,
            status=ActionExecutionStatus.STARTED,
            version=AggregateVersion.initial(),
            started_at=started_at,
        )
        claimed, replayed = await self._store.claim(
            incoming,
            self._audit(
                incoming,
                event_type="action.execution_started",
                correlation_id=correlation_id,
                causation_id=causation_id,
                occurred_at=incoming.started_at,
                request_hash=incoming.request_fingerprint,
                result_hash=incoming.fingerprint,
            ),
            lambda stored: self._audit(
                stored,
                event_type="action.execution_replayed",
                correlation_id=correlation_id,
                causation_id=causation_id,
                occurred_at=as_utc(self._clock()),
                request_hash=incoming.request_fingerprint,
                result_hash=stored.fingerprint,
                actor_id=incoming.actor_id,
            ),
        )
        if replayed:
            return claimed, True

        completed = await self._dispatcher.dispatch(authority, claimed)
        if completed.status is ActionExecutionStatus.STARTED or completed.completed_at is None:
            raise InvalidDomainValueError("rollback dispatcher returned a non-terminal result")
        stored = await self._store.finish(
            claimed,
            completed,
            self._audit(
                completed,
                event_type="action.execution_finished",
                correlation_id=correlation_id,
                causation_id=causation_id,
                occurred_at=completed.completed_at,
                request_hash=claimed.fingerprint,
                result_hash=completed.fingerprint,
            ),
        )
        return stored, False

    @staticmethod
    def _observation_scope(
        request: object,
        policy_input: object,
    ) -> tuple[TenantId, IncidentId, OpaqueIdentifier, str] | None:
        tenant_id = getattr(policy_input, "tenant_id", None)
        incident_id = getattr(request, "incident_id", None)
        idempotency_key = getattr(request, "idempotency_key", None)
        schema_version = getattr(request, "schema_version", None)
        if (
            not isinstance(tenant_id, TenantId)
            or not isinstance(incident_id, IncidentId)
            or not isinstance(idempotency_key, OpaqueIdentifier)
            or not isinstance(schema_version, str)
        ):
            return None
        return tenant_id, incident_id, OpaqueIdentifier(idempotency_key.value), schema_version

    @staticmethod
    def _terminal_observation(
        execution: ActionExecution,
        *,
        replayed: bool,
    ) -> tuple[ControlPlaneOutcome, str]:
        if replayed:
            return ControlPlaneOutcome.REPLAYED, "REPLAY"
        return {
            ActionExecutionStatus.SUCCEEDED: (ControlPlaneOutcome.SUCCEEDED, "VERIFYING"),
            ActionExecutionStatus.FAILED: (ControlPlaneOutcome.FAILED, "INVESTIGATING"),
            ActionExecutionStatus.TIMED_OUT: (ControlPlaneOutcome.TIMED_OUT, "NEEDS_HUMAN"),
            ActionExecutionStatus.UNCERTAIN: (ControlPlaneOutcome.HANDED_OFF, "NEEDS_HUMAN"),
        }[execution.status]

    def _observe(
        self,
        scope: tuple[TenantId, IncidentId, OpaqueIdentifier, str] | None,
        outcome: ControlPlaneOutcome,
        *,
        correlation_id: CorrelationId,
        causation_id: CausationId,
        started_ns: int,
        route: str,
        result_code: str,
    ) -> None:
        if scope is None:
            return
        tenant_id, incident_id, operation_id, schema_version = scope
        safely_record(
            self._observer,
            ControlPlaneObservation(
                component=ControlPlaneComponent.RECOVERY_EXECUTION,
                operation=ControlPlaneOperation.RECOVERY_EXECUTE,
                outcome=outcome,
                occurred_at=utc_observation_time(),
                tenant_id=tenant_id,
                incident_id=incident_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                operation_id=operation_id,
                duration_ms=(
                    None
                    if outcome is ControlPlaneOutcome.STARTED
                    else max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
                ),
                route=route,
                result_code=result_code,
                subject_name="rollback_service",
                subject_version=schema_version,
            ),
        )

    def _audit(
        self,
        execution: ActionExecution,
        *,
        event_type: str,
        correlation_id: CorrelationId,
        causation_id: CausationId,
        occurred_at: datetime,
        request_hash: Sha256Digest,
        result_hash: Sha256Digest,
        actor_id: ActorId | None = None,
    ) -> AuditEvent:
        audit_id = self._audit_event_id_factory()
        if not isinstance(audit_id, AuditEventId):
            raise InvalidDomainValueError("rollback audit identity is invalid")
        return AuditEvent(
            id=audit_id,
            tenant_id=execution.tenant_id,
            type=event_type,
            event_version=1,
            payload_schema_version=ACTION_EXECUTION_AUDIT_SCHEMA_VERSION,
            actor_id=execution.actor_id if actor_id is None else actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            target=AuditTarget("action.execution", execution.id),
            occurred_at=occurred_at,
            request_hash=request_hash,
            result_hash=result_hash,
        )
