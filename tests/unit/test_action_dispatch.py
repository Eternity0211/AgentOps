"""Single-attempt rollback dispatch, kill-switch, and uncertainty tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    AuthorizedRollbackExecution,
    BoundedRollbackDispatcher,
    ConfirmedRollbackFailure,
    EvidenceBoundRemediationProposal,
    RecoveryMutationCapability,
    RollbackAdapterResult,
)
from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    ActionSnapshot,
    ActorId,
    AggregateVersion,
    Approval,
    ApprovalId,
    ArtifactId,
    IdempotencyKey,
    Incident,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    OpaqueIdentifier,
    PolicyDecision,
    PolicyEnvironment,
    PolicyEvaluationInput,
    ResolvedRollbackTarget,
    RollbackServiceRequest,
    SemanticVersion,
    Sha256Digest,
    TenantId,
)

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
TENANT = TenantId("tenant-dispatch")
INCIDENT = IncidentId("incident-dispatch")
PROPOSAL_HASH = Sha256Digest("a" * 64)
POLICY_HASH = Sha256Digest("b" * 64)


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
    current_incident = Incident(
        id=INCIDENT,
        tenant_id=TENANT,
        severity=IncidentSeverity.SEV1,
        opened_at=NOW - timedelta(hours=1),
        updated_at=NOW,
        state=IncidentState.READY_TO_EXECUTE,
        version=AggregateVersion(5),
    )
    return AuthorizedRollbackExecution(
        request=RollbackServiceRequest(
            INCIDENT,
            ApprovalId("approval-dispatch"),
            IdempotencyKey("rollback-dispatch-1"),
        ),
        actor_id=ActorId("operator-dispatch"),
        incident=current_incident,
        approval=cast(Approval, SimpleNamespace(id=ApprovalId("approval-dispatch"))),
        admitted=cast(
            EvidenceBoundRemediationProposal,
            SimpleNamespace(proposal=SimpleNamespace(fingerprint=PROPOSAL_HASH)),
        ),
        policy_input=cast(PolicyEvaluationInput, SimpleNamespace()),
        policy_decision=cast(PolicyDecision, SimpleNamespace(fingerprint=POLICY_HASH)),
        target=target(),
        authorized_at=NOW,
    )


def snapshot(*, version: str, observed_at: datetime) -> ActionSnapshot:
    return ActionSnapshot(
        artifact_id=ArtifactId(f"snapshot-{version}"),
        tenant_id=TENANT,
        incident_id=INCIDENT,
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=OpaqueIdentifier("simulator-orders"),
        deployed_version=SemanticVersion(version),
        observed_at=observed_at,
        content_hash=Sha256Digest("c" * 64),
    )


def execution() -> ActionExecution:
    value = authority()
    return ActionExecution(
        id=OpaqueIdentifier("execution-dispatch"),
        tenant_id=TENANT,
        incident_id=INCIDENT,
        approval_id=value.request.approval_id,
        idempotency_key=value.request.idempotency_key,
        actor_id=value.actor_id,
        proposal_fingerprint=PROPOSAL_HASH,
        policy_decision_fingerprint=POLICY_HASH,
        target=value.target,
        before_snapshot=snapshot(version="2.0.0", observed_at=NOW),
        status=ActionExecutionStatus.STARTED,
        version=AggregateVersion(1),
        started_at=NOW,
    )


class Adapter:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls = 0

    async def rollback(self, _: AuthorizedRollbackExecution) -> RollbackAdapterResult:
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if self.outcome == "timeout":
            await asyncio.sleep(60)
        return cast(RollbackAdapterResult, self.outcome)


class Snapshots:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def persist_after_snapshot(
        self,
        _: AuthorizedRollbackExecution,
        __: RollbackAdapterResult,
        *,
        observed_at: datetime,
    ) -> ActionSnapshot:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return snapshot(version="1.0.0", observed_at=observed_at)


def result(**overrides: Any) -> RollbackAdapterResult:
    values: dict[str, Any] = {
        "service": "orders",
        "deployed_version": SemanticVersion("1.0.0"),
        "operation_reference": OpaqueIdentifier("operation-1"),
    }
    values.update(overrides)
    return RollbackAdapterResult(**values)


def dispatcher(
    adapter: Adapter,
    snapshots: Snapshots | None = None,
    *,
    enabled: bool = True,
    timeout: float = 1,
) -> BoundedRollbackDispatcher:
    return BoundedRollbackDispatcher(
        adapter,
        Snapshots() if snapshots is None else snapshots,
        RecoveryMutationCapability(enabled),
        timeout_seconds=timeout,
        clock=lambda: NOW + timedelta(seconds=1),
    )


def test_dispatch_configuration_is_strict_and_disabled_by_default() -> None:
    assert not RecoveryMutationCapability().enabled
    with pytest.raises(InvalidDomainValueError, match="flag is invalid"):
        RecoveryMutationCapability(cast(bool, "true"))
    for value in (0, -1, 301, True, "30"):
        with pytest.raises(InvalidDomainValueError, match="timeout is invalid"):
            dispatcher(Adapter(result()), timeout=cast(float, value))
    with pytest.raises(InvalidDomainValueError, match="result is invalid"):
        RollbackAdapterResult("", SemanticVersion("1.0.0"), OpaqueIdentifier("operation"))


@pytest.mark.anyio
async def test_disabled_dispatch_never_calls_adapter() -> None:
    adapter = Adapter(result())
    with pytest.raises(InvalidDomainValueError, match="capability is disabled"):
        await dispatcher(adapter, enabled=False).dispatch(authority(), execution())
    assert adapter.calls == 0


@pytest.mark.anyio
async def test_dispatch_rejects_untyped_stale_or_time_regressed_input() -> None:
    adapter = Adapter(result())
    service = dispatcher(adapter)
    with pytest.raises(InvalidDomainValueError, match="inputs are invalid"):
        await service.dispatch(
            cast(AuthorizedRollbackExecution, "invalid"),
            execution(),
        )
    with pytest.raises(InvalidDomainValueError, match="does not match"):
        await service.dispatch(
            authority(),
            replace(execution(), actor_id=ActorId("other-operator")),
        )
    regressed = BoundedRollbackDispatcher(
        adapter,
        Snapshots(),
        RecoveryMutationCapability(True),
        timeout_seconds=1,
        clock=lambda: NOW - timedelta(seconds=1),
    )
    with pytest.raises(InvalidDomainValueError, match="cannot predate"):
        await regressed.dispatch(authority(), execution())
    assert adapter.calls == 0


@pytest.mark.anyio
async def test_success_dispatches_once_and_records_stable_after_snapshot() -> None:
    adapter = Adapter(result())
    snapshots = Snapshots()
    completed = await dispatcher(adapter, snapshots).dispatch(authority(), execution())
    assert completed.status is ActionExecutionStatus.SUCCEEDED
    assert completed.after_snapshot == snapshot(
        version="1.0.0", observed_at=NOW + timedelta(seconds=1)
    )
    assert adapter.calls == snapshots.calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("outcome", "expected_status", "failure_code"),
    [
        ("timeout", ActionExecutionStatus.TIMED_OUT, "ADAPTER_TIMEOUT"),
        (
            ConfirmedRollbackFailure("rejected"),
            ActionExecutionStatus.FAILED,
            "ADAPTER_REJECTED",
        ),
        (
            RuntimeError("connection lost"),
            ActionExecutionStatus.UNCERTAIN,
            "ADAPTER_RESULT_UNKNOWN",
        ),
        (
            result(service="inventory"),
            ActionExecutionStatus.UNCERTAIN,
            "ADAPTER_RESULT_MISMATCH",
        ),
        (
            result(deployed_version=SemanticVersion("2.0.0")),
            ActionExecutionStatus.UNCERTAIN,
            "ADAPTER_RESULT_MISMATCH",
        ),
        (SimpleNamespace(), ActionExecutionStatus.UNCERTAIN, "ADAPTER_RESULT_MISMATCH"),
    ],
)
async def test_dispatch_classifies_failure_without_retry(
    outcome: object,
    expected_status: ActionExecutionStatus,
    failure_code: str,
) -> None:
    adapter = Adapter(outcome)
    completed = await dispatcher(adapter, timeout=0.001).dispatch(authority(), execution())
    assert completed.status is expected_status
    assert completed.failure_code == failure_code
    assert adapter.calls == 1


@pytest.mark.anyio
async def test_snapshot_failure_is_uncertain_and_cancellation_propagates() -> None:
    adapter = Adapter(result())
    completed = await dispatcher(
        adapter,
        Snapshots(error=RuntimeError("artifact unavailable")),
    ).dispatch(authority(), execution())
    assert completed.status is ActionExecutionStatus.UNCERTAIN
    assert completed.failure_code == "AFTER_SNAPSHOT_UNAVAILABLE"

    cancelled = Adapter(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await dispatcher(cancelled).dispatch(authority(), execution())
    assert cancelled.calls == 1
