"""Immutable recovery ActionExecution lifecycle and snapshot tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from agentops_incident_commander.domain import (
    ACTION_EXECUTION_SCHEMA_VERSION,
    ACTION_SNAPSHOT_SCHEMA_VERSION,
    ActionExecution,
    ActionExecutionStatus,
    ActionSnapshot,
    ActorId,
    AggregateVersion,
    ApprovalId,
    ArtifactId,
    IdempotencyKey,
    IncidentId,
    InvalidDomainValueError,
    NaiveDateTimeError,
    OpaqueIdentifier,
    PolicyEnvironment,
    ResolvedRollbackTarget,
    SemanticVersion,
    Sha256Digest,
    TenantId,
)

NOW = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)


def target(**overrides: Any) -> ResolvedRollbackTarget:
    values: dict[str, Any] = {
        "tenant_id": TenantId("tenant-1"),
        "service": "orders",
        "environment": PolicyEnvironment.PRODUCTION,
        "target_reference": OpaqueIdentifier("simulator-orders"),
        "expected_current_version": SemanticVersion("2.0.0"),
        "stable_version": SemanticVersion("1.0.0"),
    }
    values.update(overrides)
    return ResolvedRollbackTarget(**values)


def snapshot(
    *,
    version: str = "2.0.0",
    observed_at: datetime = NOW,
    **overrides: Any,
) -> ActionSnapshot:
    values: dict[str, Any] = {
        "artifact_id": ArtifactId(f"snapshot-{version}"),
        "tenant_id": TenantId("tenant-1"),
        "incident_id": IncidentId("incident-1"),
        "service": "orders",
        "environment": PolicyEnvironment.PRODUCTION,
        "target_reference": OpaqueIdentifier("simulator-orders"),
        "deployed_version": SemanticVersion(version),
        "observed_at": observed_at,
        "content_hash": Sha256Digest("a" * 64 if version == "2.0.0" else "b" * 64),
    }
    values.update(overrides)
    return ActionSnapshot(**values)


def execution(**overrides: Any) -> ActionExecution:
    values: dict[str, Any] = {
        "id": OpaqueIdentifier("execution-1"),
        "tenant_id": TenantId("tenant-1"),
        "incident_id": IncidentId("incident-1"),
        "approval_id": ApprovalId("approval-1"),
        "idempotency_key": IdempotencyKey("rollback-1"),
        "actor_id": ActorId("operator-1"),
        "proposal_fingerprint": Sha256Digest("c" * 64),
        "policy_decision_fingerprint": Sha256Digest("d" * 64),
        "target": target(),
        "before_snapshot": snapshot(),
        "status": ActionExecutionStatus.STARTED,
        "version": AggregateVersion(1),
        "started_at": NOW,
    }
    values.update(overrides)
    return ActionExecution(**values)


def test_started_action_is_immutable_versioned_and_fingerprinted() -> None:
    value = execution(started_at=NOW.astimezone(timezone(timedelta(hours=8))))
    assert value.schema_version == ACTION_EXECUTION_SCHEMA_VERSION
    assert value.before_snapshot.schema_version == ACTION_SNAPSHOT_SCHEMA_VERSION
    assert value.started_at == NOW
    assert len(value.fingerprint.value) == 64
    assert value.fingerprint == execution().fingerprint
    with pytest.raises(FrozenInstanceError):
        value.status = ActionExecutionStatus.SUCCEEDED  # type: ignore[misc]


def test_success_binds_after_snapshot_to_stable_version() -> None:
    started = execution()
    after = snapshot(version="1.0.0", observed_at=NOW + timedelta(seconds=5))
    completed = started.succeed(after_snapshot=after, at=NOW + timedelta(seconds=6))
    assert completed.status is ActionExecutionStatus.SUCCEEDED
    assert completed.version == AggregateVersion(2)
    assert completed.after_snapshot == after
    assert completed.failure_code is None
    assert completed.fingerprint != started.fingerprint
    with pytest.raises(InvalidDomainValueError, match="only a started action"):
        completed.succeed(after_snapshot=after, at=NOW + timedelta(seconds=7))


@pytest.mark.parametrize(
    "status",
    [
        ActionExecutionStatus.FAILED,
        ActionExecutionStatus.TIMED_OUT,
        ActionExecutionStatus.UNCERTAIN,
    ],
)
def test_failure_lifecycle_records_stable_code_and_optional_snapshot(
    status: ActionExecutionStatus,
) -> None:
    after = snapshot(observed_at=NOW + timedelta(seconds=2))
    completed = execution().fail(
        status,
        failure_code="PROVIDER_UNCONFIRMED",
        at=NOW + timedelta(seconds=3),
        after_snapshot=after,
    )
    assert completed.status is status
    assert completed.failure_code == "PROVIDER_UNCONFIRMED"
    assert completed.after_snapshot == after


def test_failure_api_rejects_non_failure_status() -> None:
    for status in (ActionExecutionStatus.STARTED, ActionExecutionStatus.SUCCEEDED):
        with pytest.raises(InvalidDomainValueError, match="failure status is invalid"):
            execution().fail(status, failure_code="INVALID", at=NOW + timedelta(seconds=1))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"artifact_id": OpaqueIdentifier("snapshot")}, "types"),
        ({"tenant_id": OpaqueIdentifier("tenant-1")}, "types"),
        ({"incident_id": OpaqueIdentifier("incident-1")}, "types"),
        ({"environment": "PRODUCTION"}, "types"),
        ({"target_reference": "target"}, "types"),
        ({"deployed_version": "2.0.0"}, "types"),
        ({"content_hash": "a" * 64}, "types"),
        ({"service": "orders; shutdown"}, "service"),
        ({"schema_version": "2.0.0"}, "schema version"),
    ],
)
def test_snapshot_rejects_invalid_fields(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        snapshot(**overrides)


def test_snapshot_rejects_naive_time_and_normalizes_utc() -> None:
    with pytest.raises(NaiveDateTimeError):
        snapshot(observed_at=NOW.replace(tzinfo=None))
    value = snapshot(observed_at=NOW.astimezone(timezone(timedelta(hours=-4))))
    assert value.observed_at == NOW


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "tenant_id",
        "incident_id",
        "approval_id",
        "idempotency_key",
        "actor_id",
        "proposal_fingerprint",
        "policy_decision_fingerprint",
        "target",
        "before_snapshot",
        "status",
        "version",
    ],
)
def test_execution_rejects_untyped_fields(field: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="types are invalid"):
        execution(**{field: "invalid"})


def test_execution_rejects_schema_and_naive_times() -> None:
    with pytest.raises(InvalidDomainValueError, match="schema version"):
        execution(schema_version="2.0.0")
    with pytest.raises(NaiveDateTimeError):
        execution(started_at=NOW.replace(tzinfo=None))
    with pytest.raises(NaiveDateTimeError):
        execution(
            status=ActionExecutionStatus.FAILED,
            completed_at=NOW.replace(tzinfo=None),
            failure_code="FAILED",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": TenantId("tenant-other")},
        {"before_snapshot": snapshot(tenant_id=TenantId("tenant-other"))},
        {"before_snapshot": snapshot(incident_id=IncidentId("incident-other"))},
        {"before_snapshot": snapshot(service="payments")},
        {"before_snapshot": snapshot(environment=PolicyEnvironment.STAGING)},
        {"before_snapshot": snapshot(target_reference=OpaqueIdentifier("other-target"))},
        {"before_snapshot": snapshot(version="1.0.0")},
        {"before_snapshot": snapshot(observed_at=NOW + timedelta(seconds=1))},
    ],
)
def test_execution_rejects_unbound_before_snapshot(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvalidDomainValueError, match="before snapshot"):
        execution(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": ActionExecutionStatus.FAILED},
        {"completed_at": NOW + timedelta(seconds=1)},
    ],
)
def test_execution_rejects_inconsistent_completion(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvalidDomainValueError, match="completion state"):
        execution(**overrides)


def test_execution_rejects_completion_before_start() -> None:
    with pytest.raises(InvalidDomainValueError, match="before it starts"):
        execution(
            status=ActionExecutionStatus.FAILED,
            completed_at=NOW - timedelta(seconds=1),
            failure_code="FAILED",
        )


def test_success_requires_exact_stable_after_snapshot_and_no_failure() -> None:
    base = {
        "status": ActionExecutionStatus.SUCCEEDED,
        "completed_at": NOW + timedelta(seconds=2),
    }
    with pytest.raises(InvalidDomainValueError, match="requires only"):
        execution(**base)
    with pytest.raises(InvalidDomainValueError, match="requires only"):
        execution(
            **base,
            after_snapshot=snapshot(version="1.0.0", observed_at=NOW + timedelta(seconds=1)),
            failure_code="SHOULD_NOT_EXIST",
        )
    with pytest.raises(InvalidDomainValueError, match="stable version"):
        execution(
            **base,
            after_snapshot=snapshot(observed_at=NOW + timedelta(seconds=1)),
        )


@pytest.mark.parametrize("failure_code", [None, "", "lowercase", "BAD CODE", "X" * 129])
def test_non_success_terminal_state_requires_stable_failure_code(
    failure_code: str | None,
) -> None:
    with pytest.raises(InvalidDomainValueError, match="stable failure code"):
        execution(
            status=ActionExecutionStatus.FAILED,
            completed_at=NOW + timedelta(seconds=1),
            failure_code=failure_code,
        )


def test_started_action_cannot_contain_terminal_result() -> None:
    with pytest.raises(InvalidDomainValueError, match="started action"):
        execution(after_snapshot=snapshot())
    with pytest.raises(InvalidDomainValueError, match="started action"):
        execution(failure_code="FAILED")


@pytest.mark.parametrize(
    "after",
    [
        snapshot(version="1.0.0", tenant_id=TenantId("tenant-other")),
        snapshot(version="1.0.0", incident_id=IncidentId("incident-other")),
        snapshot(version="1.0.0", service="payments"),
        snapshot(version="1.0.0", environment=PolicyEnvironment.STAGING),
        snapshot(version="1.0.0", target_reference=OpaqueIdentifier("other-target")),
        snapshot(version="1.0.0", observed_at=NOW - timedelta(seconds=1)),
        snapshot(version="1.0.0", observed_at=NOW + timedelta(seconds=3)),
    ],
)
def test_execution_rejects_unbound_after_snapshot(after: ActionSnapshot) -> None:
    with pytest.raises(InvalidDomainValueError, match="after snapshot"):
        execution(
            status=ActionExecutionStatus.SUCCEEDED,
            completed_at=NOW + timedelta(seconds=2),
            after_snapshot=after,
        )


def test_fingerprint_binds_actor_approval_policy_and_snapshots() -> None:
    base = execution()
    variants = (
        replace(base, actor_id=ActorId("operator-2")),
        replace(base, approval_id=ApprovalId("approval-2")),
        replace(base, policy_decision_fingerprint=Sha256Digest("e" * 64)),
        replace(base, before_snapshot=snapshot(content_hash=Sha256Digest("f" * 64))),
    )
    assert all(item.fingerprint != base.fingerprint for item in variants)
