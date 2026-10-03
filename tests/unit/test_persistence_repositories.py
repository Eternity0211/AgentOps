"""Focused defensive-path tests for persistence repositories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentops_incident_commander.domain import (
    AggregateVersion,
    Alert,
    AlertDimension,
    AlertGroupId,
    AlertId,
    IncidentSeverity,
    InvalidDomainValueError,
    OpaqueIdentifier,
    OptimisticVersionError,
    OutboxEventId,
    TenantId,
)
from agentops_incident_commander.infrastructure.persistence import (
    AlertGroupRow,
    AlertRepository,
    OutboxEventRow,
    OutboxRepository,
    repositories,
)

NOW = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


def alert() -> Alert:
    return Alert(
        id=AlertId("alert-2"),
        tenant_id=TenantId("tenant-1"),
        environment="production",
        service="order-service",
        rule="errors",
        severity=IncidentSeverity.SEV1,
        observed_at=NOW,
        received_at=NOW,
        dimensions=(AlertDimension("region", "east"),),
    )


def existing_row(item: Alert) -> AlertGroupRow:
    return AlertGroupRow(
        id="group-1",
        fingerprint=item.fingerprint().value,
        fingerprint_schema_version=item.fingerprint().schema_version,
        tenant_id=item.tenant_id.value,
        environment=item.environment,
        service=item.service,
        rule=item.rule,
        severity=IncidentSeverity.SEV3.value,
        first_observed_at=NOW,
        last_observed_at=NOW,
        first_received_at=NOW,
        last_received_at=NOW,
        occurrence_count=1,
        version=1,
    )


@pytest.mark.anyio
async def test_alert_repository_rejects_impossible_optimistic_update_loss() -> None:
    """The row-count guard still fails closed if locking guarantees are violated."""
    item = alert()
    session = AsyncMock()
    session.get.return_value = None
    session.scalars.side_effect = [
        SimpleNamespace(all=lambda: [existing_row(item)]),
        SimpleNamespace(all=lambda: ["alert-1"]),
    ]
    session.execute.side_effect = [SimpleNamespace(), SimpleNamespace(rowcount=0)]
    repository = AlertRepository(
        session,
        window=timedelta(minutes=5),
        group_id_factory=lambda: AlertGroupId("unused"),
    )

    with pytest.raises(OptimisticVersionError, match="changed during"):
        await repository.ingest(item)


@pytest.mark.anyio
async def test_alert_repository_rejects_dangling_alert_group_reference() -> None:
    """A corrupt foreign-key reference cannot become a partial domain aggregate."""
    session = AsyncMock()
    session.get.return_value = None
    repository = AlertRepository(
        session,
        window=timedelta(minutes=5),
        group_id_factory=lambda: AlertGroupId("unused"),
    )

    with pytest.raises(InvalidDomainValueError, match="missing group"):
        await repository._load_group("missing")


def test_aggregate_version_type_remains_explicit_in_repository_test_fixture() -> None:
    """Keep the repository fixture's expected version contract visible."""
    assert AggregateVersion(1).next() == AggregateVersion(2)


def test_outbox_hydration_rejects_payload_hash_drift() -> None:
    """A stored payload cannot be dispatched when its integrity digest no longer matches."""
    row = OutboxEventRow(payload={"value": 1}, payload_hash="0" * 64)

    with pytest.raises(InvalidDomainValueError, match="hash does not match"):
        repositories._outbox_event_from_row(row)


@pytest.mark.anyio
@pytest.mark.parametrize("duration", [timedelta(0), timedelta(seconds=-1)])
async def test_outbox_claim_rejects_nonpositive_lease(duration: timedelta) -> None:
    repository = OutboxRepository(AsyncMock())

    with pytest.raises(InvalidDomainValueError, match="duration must be positive"):
        await repository.claim(
            OpaqueIdentifier("worker-1"), now=NOW, lease_duration=duration, limit=1
        )


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
async def test_outbox_claim_rejects_invalid_batch_limit(limit: object) -> None:
    repository = OutboxRepository(AsyncMock())

    with pytest.raises(InvalidDomainValueError, match="between 1 and 100"):
        await repository.claim(
            OpaqueIdentifier("worker-1"),
            now=NOW,
            lease_duration=timedelta(seconds=1),
            limit=limit,  # type: ignore[arg-type]
        )


@pytest.mark.anyio
async def test_outbox_failure_rejects_retry_before_failure() -> None:
    repository = OutboxRepository(AsyncMock())

    with pytest.raises(InvalidDomainValueError, match="cannot predate"):
        await repository.mark_failed(
            OutboxEventId("outbox-1"),
            OpaqueIdentifier("worker-1"),
            failed_at=NOW,
            retry_at=NOW - timedelta(seconds=1),
            error="failure",
        )


@pytest.mark.anyio
@pytest.mark.parametrize("error", ["", "x" * 513, "line\nbreak"])
async def test_outbox_failure_rejects_unsafe_error_text(error: str) -> None:
    repository = OutboxRepository(AsyncMock())

    with pytest.raises(InvalidDomainValueError, match="bounded printable"):
        await repository.mark_failed(
            OutboxEventId("outbox-1"),
            OpaqueIdentifier("worker-1"),
            failed_at=NOW,
            retry_at=NOW,
            error=error,
        )
