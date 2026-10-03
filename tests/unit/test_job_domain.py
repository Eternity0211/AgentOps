"""Tests for durable worker job contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agentops_incident_commander.domain import (
    CausationId,
    CorrelationId,
    InvalidDomainValueError,
    Job,
    JobFailureRoute,
    JobId,
    JobLease,
    NaiveDateTimeError,
    OpaqueIdentifier,
)

NOW = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


def job(**overrides: object) -> Job:
    values: dict[str, object] = {
        "id": JobId("job-1"),
        "type": "workflow.investigate",
        "schema_version": "workflow/v1",
        "payload_ref": OpaqueIdentifier("payload-1"),
        "correlation_id": CorrelationId("correlation-1"),
        "causation_id": CausationId("command-1"),
        "priority": 50,
        "created_at": NOW,
        "available_at": NOW,
        "max_attempts": 3,
        "failure_route": JobFailureRoute.NEEDS_HUMAN,
    }
    values.update(overrides)
    return Job(**values)  # type: ignore[arg-type]


def test_job_preserves_typed_queue_contract() -> None:
    value = job()
    assert value.priority == 50
    assert value.failure_route is JobFailureRoute.NEEDS_HUMAN


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("type", "workflow", "dotted lowercase"),
        ("schema_version", "workflow/v0", "name/vN"),
        ("priority", True, "must be an integer"),
        ("priority", -1, "between 0 and 100"),
        ("priority", 101, "between 0 and 100"),
        ("max_attempts", 0, "positive integer"),
        ("max_attempts", True, "positive integer"),
    ],
)
def test_job_rejects_invalid_fields(field: str, value: object, message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        job(**{field: value})


def test_job_rejects_invalid_times() -> None:
    with pytest.raises(InvalidDomainValueError, match="cannot predate"):
        job(available_at=NOW - timedelta(seconds=1))
    with pytest.raises(NaiveDateTimeError, match="timezone-aware"):
        job(created_at=NOW.replace(tzinfo=None))


def test_job_lease_requires_ordered_active_times() -> None:
    lease = JobLease(
        job(),
        1,
        OpaqueIdentifier("worker-1"),
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=2),
    )
    assert lease.attempt == 1

    with pytest.raises(InvalidDomainValueError, match="positive integer"):
        JobLease(job(), True, OpaqueIdentifier("worker-1"), NOW, NOW, NOW + timedelta(seconds=1))
    with pytest.raises(InvalidDomainValueError, match="ordered and active"):
        JobLease(job(), 1, OpaqueIdentifier("worker-1"), NOW, NOW, NOW)
