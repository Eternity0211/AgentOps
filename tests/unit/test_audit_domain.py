"""Tests for immutable audit-domain contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from agentops_incident_commander.domain import (
    ActorId,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    NaiveDateTimeError,
    Sha256Digest,
    StoredAuditEvent,
)


def audit_event(**overrides: object) -> AuditEvent:
    values: dict[str, object] = {
        "id": AuditEventId("audit-1"),
        "type": "incident.opened",
        "event_version": 1,
        "payload_schema_version": "incident/v1",
        "actor_id": ActorId("operator-1"),
        "correlation_id": CorrelationId("correlation-1"),
        "causation_id": CausationId("command-1"),
        "target": AuditTarget("incident.record", IncidentId("incident-1")),
        "occurred_at": datetime(2026, 10, 3, 16, 0, tzinfo=timezone(timedelta(hours=8))),
        "request_hash": Sha256Digest("a" * 64),
        "result_hash": Sha256Digest("b" * 64),
    }
    values.update(overrides)
    return AuditEvent(**values)  # type: ignore[arg-type]


def test_audit_event_preserves_typed_provenance_and_normalizes_time() -> None:
    event = audit_event()

    assert event.occurred_at == datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    assert event.target.id == IncidentId("incident-1")
    assert str(event.request_hash) == "a" * 64
    assert StoredAuditEvent(7, event).sequence == 7


@pytest.mark.parametrize("value", ["", "incident", "Incident.opened", "incident.open-ed"])
def test_audit_event_rejects_invalid_event_type(value: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="dotted lowercase"):
        audit_event(type=value)


@pytest.mark.parametrize("value", ["incident", "Incident.record", "incident.record-value"])
def test_audit_target_rejects_invalid_type(value: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="dotted lowercase"):
        AuditTarget(value, IncidentId("incident-1"))


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_audit_event_version_must_be_a_positive_integer(value: object) -> None:
    with pytest.raises(InvalidDomainValueError, match="positive integer"):
        audit_event(event_version=value)


@pytest.mark.parametrize("value", ["", "incident", "incident/v0", "Incident/v1", "x/v01"])
def test_audit_event_rejects_invalid_payload_schema_version(value: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="name/vN"):
        audit_event(payload_schema_version=value)


@pytest.mark.parametrize("value", ["a" * 63, "A" * 64, "g" * 64])
def test_sha256_digest_rejects_noncanonical_value(value: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="64 lowercase hex"):
        Sha256Digest(value)


def test_audit_event_rejects_naive_time() -> None:
    with pytest.raises(NaiveDateTimeError, match="timezone-aware"):
        audit_event(occurred_at=datetime(2026, 10, 3, 8, 0))


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_stored_audit_sequence_must_be_a_positive_integer(value: object) -> None:
    with pytest.raises(InvalidDomainValueError, match="positive integer"):
        StoredAuditEvent(value, audit_event())  # type: ignore[arg-type]
