"""Crash-safe rollback Executor composition and replay tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    AuthorizedRollbackExecution,
    ControlPlaneObservation,
    ControlPlaneOutcome,
    RollbackActionExecutor,
)
from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    ActionSnapshot,
    ActorId,
    ApprovalId,
    ArtifactId,
    AuditEvent,
    AuditEventId,
    CausationId,
    CorrelationId,
    IdempotencyKey,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    PolicyEnvironment,
    ResolvedRollbackTarget,
    SemanticVersion,
    Sha256Digest,
    TenantId,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
TENANT = TenantId("tenant-executor")
INCIDENT = IncidentId("incident-executor")
PROPOSAL_HASH = Sha256Digest("a" * 64)
POLICY_HASH = Sha256Digest("b" * 64)
CORRELATION = CorrelationId("correlation-executor")
CAUSATION = CausationId("causation-executor")


def target() -> ResolvedRollbackTarget:
    return ResolvedRollbackTarget(
        tenant_id=TENANT,
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=OpaqueIdentifier("simulator-orders"),
        expected_current_version=SemanticVersion("2.0.0"),
        stable_version=SemanticVersion("1.0.0"),
    )


def authority() -> AuthorizedRollbackExecution:
    return cast(
        AuthorizedRollbackExecution,
        SimpleNamespace(
            request=SimpleNamespace(idempotency_key=IdempotencyKey("rollback-executor")),
            actor_id=ActorId("operator-executor"),
            incident=SimpleNamespace(tenant_id=TENANT, id=INCIDENT),
            approval=SimpleNamespace(id=ApprovalId("approval-executor")),
            admitted=SimpleNamespace(proposal=SimpleNamespace(fingerprint=PROPOSAL_HASH)),
            policy_decision=SimpleNamespace(fingerprint=POLICY_HASH),
            target=target(),
        ),
    )


def before_snapshot() -> ActionSnapshot:
    return ActionSnapshot(
        artifact_id=ArtifactId("before-executor"),
        tenant_id=TENANT,
        incident_id=INCIDENT,
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=OpaqueIdentifier("simulator-orders"),
        deployed_version=SemanticVersion("2.0.0"),
        observed_at=NOW,
        content_hash=Sha256Digest("c" * 64),
    )


def after_snapshot() -> ActionSnapshot:
    return ActionSnapshot(
        artifact_id=ArtifactId("after-executor"),
        tenant_id=TENANT,
        incident_id=INCIDENT,
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=OpaqueIdentifier("simulator-orders"),
        deployed_version=SemanticVersion("1.0.0"),
        observed_at=NOW + timedelta(seconds=2),
        content_hash=Sha256Digest("d" * 64),
    )


class Preflight:
    def __init__(self, events: list[str], *, error: Exception | None = None) -> None:
        self.events = events
        self.error = error
        self.calls = 0

    async def authorize(self, *_: object, **__: object) -> AuthorizedRollbackExecution:
        self.events.append("preflight")
        self.calls += 1
        if self.error is not None:
            raise self.error
        return authority()


class Snapshots:
    def __init__(self, events: list[str], *, error: Exception | None = None) -> None:
        self.events = events
        self.error = error
        self.calls = 0

    async def persist_before_snapshot(
        self,
        _: AuthorizedRollbackExecution,
        *,
        observed_at: datetime,
    ) -> ActionSnapshot:
        self.events.append("before")
        self.calls += 1
        assert observed_at == NOW + timedelta(seconds=1)
        if self.error is not None:
            raise self.error
        return before_snapshot()


class Store:
    def __init__(
        self,
        events: list[str],
        *,
        claim_error: Exception | None = None,
        finish_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.claim_error = claim_error
        self.finish_error = finish_error
        self.stored: ActionExecution | None = None
        self.claim_audits: list[AuditEvent] = []
        self.finish_audits: list[AuditEvent] = []
        self.replay_audits: list[AuditEvent] = []

    async def claim(
        self,
        execution: ActionExecution,
        audit_event: AuditEvent,
        replay_audit_factory: Callable[[ActionExecution], AuditEvent],
    ) -> tuple[ActionExecution, bool]:
        self.events.append("claim")
        self.claim_audits.append(audit_event)
        if self.claim_error is not None:
            raise self.claim_error
        if self.stored is not None:
            assert execution.request_fingerprint == self.stored.request_fingerprint
            self.events.append("replay")
            self.replay_audits.append(replay_audit_factory(self.stored))
            return self.stored, True
        self.stored = execution
        return execution, False

    async def finish(
        self,
        expected: ActionExecution,
        completed: ActionExecution,
        audit_event: AuditEvent,
    ) -> ActionExecution:
        self.events.append("finish")
        self.finish_audits.append(audit_event)
        assert self.stored == expected
        if self.finish_error is not None:
            raise self.finish_error
        self.stored = completed
        return completed


class CrashAfterClaimCommitStore(Store):
    """Simulate process loss after the durable claim commit returned internally."""

    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.crashed = False

    async def claim(
        self,
        execution: ActionExecution,
        audit_event: AuditEvent,
        replay_audit_factory: Callable[[ActionExecution], AuditEvent],
    ) -> tuple[ActionExecution, bool]:
        result = await super().claim(execution, audit_event, replay_audit_factory)
        if not self.crashed:
            self.crashed = True
            raise asyncio.CancelledError()
        return result


class CrashAfterFinishCommitStore(Store):
    """Simulate process loss after the terminal result became durable."""

    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.crashed = False

    async def finish(
        self,
        expected: ActionExecution,
        completed: ActionExecution,
        audit_event: AuditEvent,
    ) -> ActionExecution:
        result = await super().finish(expected, completed, audit_event)
        if not self.crashed:
            self.crashed = True
            raise asyncio.CancelledError()
        return result


class Dispatcher:
    def __init__(
        self,
        events: list[str],
        *,
        status: ActionExecutionStatus = ActionExecutionStatus.SUCCEEDED,
        enable_error: Exception | None = None,
        dispatch_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.status = status
        self.enable_error = enable_error
        self.dispatch_error = dispatch_error
        self.calls = 0

    def ensure_enabled(self) -> None:
        self.events.append("enabled")
        if self.enable_error is not None:
            raise self.enable_error

    async def dispatch(
        self,
        _: AuthorizedRollbackExecution,
        execution: ActionExecution,
    ) -> ActionExecution:
        self.events.append("dispatch")
        self.calls += 1
        if self.dispatch_error is not None:
            raise self.dispatch_error
        if self.status is ActionExecutionStatus.STARTED:
            return execution
        if self.status is ActionExecutionStatus.SUCCEEDED:
            return execution.succeed(
                after_snapshot=after_snapshot(),
                at=NOW + timedelta(seconds=2),
            )
        return execution.fail(
            self.status,
            failure_code="ADAPTER_TEST_FAILURE",
            at=NOW + timedelta(seconds=2),
        )


class RecordingObserver:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.values: list[ControlPlaneObservation] = []

    def record(self, value: ControlPlaneObservation) -> None:
        if self.fail:
            raise RuntimeError("telemetry unavailable")
        self.values.append(value)


def executor(
    *,
    events: list[str] | None = None,
    preflight: Preflight | None = None,
    snapshots: Snapshots | None = None,
    store: Store | None = None,
    dispatcher: Dispatcher | None = None,
    execution_ids: list[object] | None = None,
    audit_ids: list[object] | None = None,
    observer: RecordingObserver | None = None,
) -> tuple[RollbackActionExecutor, Preflight, Snapshots, Store, Dispatcher, list[str]]:
    recorded = [] if events is None else events
    prepared_preflight = Preflight(recorded) if preflight is None else preflight
    prepared_snapshots = Snapshots(recorded) if snapshots is None else snapshots
    prepared_store = Store(recorded) if store is None else store
    prepared_dispatcher = Dispatcher(recorded) if dispatcher is None else dispatcher
    generated_executions = iter(
        execution_ids or [OpaqueIdentifier("execution-one"), OpaqueIdentifier("execution-two")]
    )
    generated_audits = iter(
        audit_ids
        or [
            AuditEventId("audit-one"),
            AuditEventId("audit-two"),
            AuditEventId("audit-three"),
            AuditEventId("audit-four"),
        ]
    )
    service = RollbackActionExecutor(
        prepared_preflight,
        prepared_snapshots,
        prepared_store,
        prepared_dispatcher,
        execution_id_factory=lambda: cast(OpaqueIdentifier, next(generated_executions)),
        audit_event_id_factory=lambda: cast(AuditEventId, next(generated_audits)),
        clock=lambda: NOW + timedelta(seconds=1),
        observer=RecordingObserver() if observer is None else observer,
    )
    return (
        service,
        prepared_preflight,
        prepared_snapshots,
        prepared_store,
        prepared_dispatcher,
        recorded,
    )


async def run(service: RollbackActionExecutor, **overrides: Any) -> ActionExecution:
    values: dict[str, Any] = {
        "request": cast(
            Any,
            SimpleNamespace(
                incident_id=INCIDENT,
                approval_id=ApprovalId("approval-executor"),
                idempotency_key=IdempotencyKey("rollback-executor"),
                schema_version="1.0.0",
            ),
        ),
        "proposal": cast(Any, object()),
        "policy_input": cast(Any, SimpleNamespace(tenant_id=TENANT)),
        "policy_decision": cast(Any, object()),
        "principal": None,
        "correlation_id": CORRELATION,
        "causation_id": CAUSATION,
    }
    values.update(overrides)
    return await service.execute(**values)


@pytest.mark.anyio
async def test_executor_orders_durable_claim_dispatch_and_terminal_commit() -> None:
    observer = RecordingObserver()
    service, _, _, store, dispatcher, events = executor(observer=observer)
    completed = await run(service)

    assert completed.status is ActionExecutionStatus.SUCCEEDED
    assert events == ["enabled", "preflight", "before", "claim", "dispatch", "finish"]
    assert dispatcher.calls == 1
    started_audit = store.claim_audits[0]
    finished_audit = store.finish_audits[0]
    assert started_audit.type == "action.execution_started"
    assert started_audit.request_hash == completed.request_fingerprint
    assert finished_audit.type == "action.execution_finished"
    assert finished_audit.request_hash != finished_audit.result_hash
    assert finished_audit.result_hash == completed.fingerprint
    assert started_audit.correlation_id == finished_audit.correlation_id == CORRELATION
    assert [value.outcome for value in observer.values] == [
        ControlPlaneOutcome.STARTED,
        ControlPlaneOutcome.SUCCEEDED,
    ]
    assert observer.values[-1].route == "VERIFYING"
    assert observer.values[-1].result_code == "SUCCEEDED"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status",
    [
        ActionExecutionStatus.FAILED,
        ActionExecutionStatus.TIMED_OUT,
        ActionExecutionStatus.UNCERTAIN,
    ],
)
async def test_executor_persists_every_non_success_dispatch_classification(
    status: ActionExecutionStatus,
) -> None:
    events: list[str] = []
    observer = RecordingObserver()
    service, _, _, store, _, _ = executor(
        events=events,
        dispatcher=Dispatcher(events, status=status),
        observer=observer,
    )
    completed = await run(service)
    assert completed.status is status
    assert store.stored == completed
    expected = {
        ActionExecutionStatus.FAILED: ControlPlaneOutcome.FAILED,
        ActionExecutionStatus.TIMED_OUT: ControlPlaneOutcome.TIMED_OUT,
        ActionExecutionStatus.UNCERTAIN: ControlPlaneOutcome.HANDED_OFF,
    }[status]
    assert observer.values[-1].outcome is expected


@pytest.mark.anyio
async def test_terminal_retry_records_replay_without_second_dispatch() -> None:
    observer = RecordingObserver()
    service, _, _, store, dispatcher, events = executor(observer=observer)
    completed = await run(service)
    replayed = await run(service)

    assert replayed == completed
    assert dispatcher.calls == 1
    assert events[-5:] == ["enabled", "preflight", "before", "claim", "replay"]
    replay_audit = store.replay_audits[0]
    assert replay_audit.type == "action.execution_replayed"
    assert replay_audit.target.id == completed.id
    assert replay_audit.request_hash == completed.request_fingerprint
    assert replay_audit.result_hash == completed.fingerprint
    assert observer.values[-1].outcome is ControlPlaneOutcome.REPLAYED
    assert observer.values[-1].result_code == "REPLAY_SUCCEEDED"


@pytest.mark.anyio
async def test_claim_commit_then_worker_exit_replays_without_dispatch() -> None:
    events: list[str] = []
    store = CrashAfterClaimCommitStore(events)
    service, _, _, _, dispatcher, _ = executor(events=events, store=store)

    with pytest.raises(asyncio.CancelledError):
        await run(service)
    assert store.stored is not None
    assert store.stored.status is ActionExecutionStatus.STARTED
    assert dispatcher.calls == 0

    replayed = await run(service)
    assert replayed == store.stored
    assert replayed.status is ActionExecutionStatus.STARTED
    assert dispatcher.calls == 0
    assert len(store.claim_audits) == 2
    assert len(store.replay_audits) == 1


@pytest.mark.anyio
async def test_cancellation_leaves_durable_started_claim_and_retry_only_observes_replay() -> None:
    events: list[str] = []
    dispatcher = Dispatcher(events, dispatch_error=asyncio.CancelledError())
    service, _, _, store, _, _ = executor(events=events, dispatcher=dispatcher)

    with pytest.raises(asyncio.CancelledError):
        await run(service)
    assert store.stored is not None
    assert store.stored.status is ActionExecutionStatus.STARTED

    replayed = await run(service)
    assert replayed.status is ActionExecutionStatus.STARTED
    assert dispatcher.calls == 1
    assert len(store.replay_audits) == 1


@pytest.mark.anyio
async def test_terminal_commit_then_worker_exit_replays_without_redispatch() -> None:
    events: list[str] = []
    store = CrashAfterFinishCommitStore(events)
    service, _, _, _, dispatcher, _ = executor(events=events, store=store)

    with pytest.raises(asyncio.CancelledError):
        await run(service)
    assert store.stored is not None
    assert store.stored.status is ActionExecutionStatus.SUCCEEDED
    assert dispatcher.calls == 1

    replayed = await run(service)
    assert replayed == store.stored
    assert replayed.status is ActionExecutionStatus.SUCCEEDED
    assert dispatcher.calls == 1
    assert len(store.finish_audits) == 1
    assert len(store.replay_audits) == 1


@pytest.mark.anyio
async def test_finish_failure_never_redispatches_after_durable_claim() -> None:
    events: list[str] = []
    store = Store(events, finish_error=RuntimeError("commit unavailable"))
    dispatcher = Dispatcher(events)
    service, _, _, _, _, _ = executor(
        events=events,
        store=store,
        dispatcher=dispatcher,
    )

    with pytest.raises(RuntimeError, match="commit unavailable"):
        await run(service)
    assert store.stored is not None
    assert store.stored.status is ActionExecutionStatus.STARTED
    store.finish_error = None

    replayed = await run(service)
    assert replayed.status is ActionExecutionStatus.STARTED
    assert dispatcher.calls == 1
    assert len(store.replay_audits) == 1


@pytest.mark.anyio
async def test_executor_refuses_before_claim_when_any_pre_effect_boundary_fails() -> None:
    for boundary in ("enabled", "preflight", "snapshot", "claim"):
        events: list[str] = []
        preflight = Preflight(
            events,
            error=InvalidDomainValueError("preflight refused") if boundary == "preflight" else None,
        )
        snapshots = Snapshots(
            events,
            error=RuntimeError("snapshot unavailable") if boundary == "snapshot" else None,
        )
        store = Store(
            events,
            claim_error=InvalidDomainValueError("claim conflict") if boundary == "claim" else None,
        )
        dispatcher = Dispatcher(
            events,
            enable_error=(
                InvalidDomainValueError("capability disabled") if boundary == "enabled" else None
            ),
        )
        service, _, _, _, _, _ = executor(
            events=events,
            preflight=preflight,
            snapshots=snapshots,
            store=store,
            dispatcher=dispatcher,
        )
        with pytest.raises((InvalidDomainValueError, RuntimeError)):
            await run(service)
        assert dispatcher.calls == 0
        assert store.stored is None


@pytest.mark.anyio
async def test_capability_and_unexpected_failures_are_observable_without_error_payloads() -> None:
    events: list[str] = []
    disabled_observer = RecordingObserver()
    disabled, _, _, _, _, _ = executor(
        events=events,
        dispatcher=Dispatcher(
            events,
            enable_error=InvalidDomainValueError("secret capability detail"),
        ),
        observer=disabled_observer,
    )
    with pytest.raises(InvalidDomainValueError):
        await run(disabled)
    assert disabled_observer.values[-1].outcome is ControlPlaneOutcome.REFUSED
    assert disabled_observer.values[-1].result_code == "CAPABILITY_DISABLED"

    failed_observer = RecordingObserver()
    failed, _, _, _, _, _ = executor(
        events=[],
        preflight=Preflight([], error=RuntimeError("secret provider detail")),
        observer=failed_observer,
    )
    with pytest.raises(RuntimeError):
        await run(failed)
    assert failed_observer.values[-1].outcome is ControlPlaneOutcome.FAILED
    assert failed_observer.values[-1].result_code == "EXECUTION_FAILED"
    assert all("secret" not in repr(value) for value in failed_observer.values)

    timeout_observer = RecordingObserver()
    timed_out, _, _, _, _, _ = executor(
        events=[],
        dispatcher=Dispatcher([], dispatch_error=TimeoutError("backend timeout")),
        observer=timeout_observer,
    )
    with pytest.raises(TimeoutError):
        await run(timed_out)
    assert timeout_observer.values[-1].outcome is ControlPlaneOutcome.TIMED_OUT
    assert timeout_observer.values[-1].result_code == "EXECUTION_TIMEOUT"


@pytest.mark.anyio
async def test_observer_failure_cannot_change_authoritative_execution() -> None:
    service, _, _, store, dispatcher, _ = executor(observer=RecordingObserver(fail=True))
    completed = await run(service)
    assert completed.status is ActionExecutionStatus.SUCCEEDED
    assert store.stored == completed
    assert dispatcher.calls == 1

    unscoped, _, _, _, _, _ = executor(observer=RecordingObserver(fail=True))
    unobserved = await run(unscoped, request=object(), policy_input=object())
    assert unobserved.status is ActionExecutionStatus.SUCCEEDED


@pytest.mark.anyio
async def test_executor_rejects_invalid_trace_or_generated_identities_and_nonterminal_result() -> (
    None
):
    service, preflight, _, _, _, _ = executor()
    with pytest.raises(InvalidDomainValueError, match="trace identities"):
        await run(service, correlation_id=cast(CorrelationId, "invalid"))
    assert preflight.calls == 0

    bad_execution, _, _, _, _, _ = executor(execution_ids=["invalid"])
    with pytest.raises(InvalidDomainValueError, match="execution identity"):
        await run(bad_execution)

    bad_audit, _, _, _, _, _ = executor(audit_ids=["invalid"])
    with pytest.raises(InvalidDomainValueError, match="audit identity"):
        await run(bad_audit)

    events: list[str] = []
    nonterminal, _, _, store, _, _ = executor(
        events=events,
        dispatcher=Dispatcher(events, status=ActionExecutionStatus.STARTED),
    )
    with pytest.raises(InvalidDomainValueError, match="non-terminal"):
        await run(nonterminal)
    assert store.finish_audits == []
