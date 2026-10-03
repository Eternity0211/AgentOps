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
    OptimisticVersionError,
    TenantId,
)
from agentops_incident_commander.infrastructure.persistence import AlertGroupRow, AlertRepository

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
