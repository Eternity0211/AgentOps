"""Tests for framework-free transactional outbox contracts."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from agentops_incident_commander.domain import (
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    NaiveDateTimeError,
    OpaqueIdentifier,
    OutboxClaim,
    OutboxEvent,
    OutboxEventId,
    OutboxPayload,
    Sha256Digest,
)

NOW = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


def outbox_event(**overrides: object) -> OutboxEvent:
    values: dict[str, object] = {
        "id": OutboxEventId("outbox-1"),
        "topic": "incident.transitioned",
        "schema_version": "incident/v1",
        "aggregate_type": "incident.record",
        "aggregate_id": IncidentId("incident-1"),
        "aggregate_version": 2,
        "correlation_id": CorrelationId("correlation-1"),
        "causation_id": CausationId("command-1"),
        "payload": OutboxPayload.from_mapping({"state": "TRIAGED", "version": 2}),
        "occurred_at": NOW,
        "available_at": NOW,
        "max_attempts": 3,
    }
    values.update(overrides)
    return OutboxEvent(**values)  # type: ignore[arg-type]


def test_payload_is_canonical_detached_and_hashed() -> None:
    source = {"z": [1, True, None], "a": "事件"}
    payload = OutboxPayload.from_mapping(source)
    source["a"] = "changed"

    assert payload.canonical_json == '{"a":"事件","z":[1,true,null]}'
    assert payload.as_mapping() == {"a": "事件", "z": [1, True, None]}
    assert payload.sha256 == Sha256Digest(
        "6a0ee64d5291e7f6b554b824c9eb45896fbcf6637dde3475bf8584bd86065c3f"
    )


@pytest.mark.parametrize("value", ["not-json", "[]", '{"b":1,"a":2}'])
def test_payload_rejects_invalid_non_object_or_noncanonical_json(value: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="outbox payload"):
        OutboxPayload(value)


@pytest.mark.parametrize("value", [{"value": math.nan}, {"value": object()}])
def test_payload_rejects_non_json_or_nonfinite_values(value: dict[str, object]) -> None:
    with pytest.raises(InvalidDomainValueError, match="finite JSON"):
        OutboxPayload.from_mapping(value)


def test_payload_rejects_oversized_utf8_content() -> None:
    with pytest.raises(InvalidDomainValueError, match="65536"):
        OutboxPayload.from_mapping({"value": "界" * 22_000})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("topic", "incident", "dotted lowercase"),
        ("aggregate_type", "Incident.record", "dotted lowercase"),
        ("schema_version", "incident/v0", "name/vN"),
        ("aggregate_version", 0, "positive integer"),
        ("aggregate_version", True, "positive integer"),
        ("max_attempts", -1, "positive integer"),
    ],
)
def test_event_rejects_invalid_contract_fields(field: str, value: object, message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        outbox_event(**{field: value})


def test_event_normalizes_times_and_rejects_invalid_order() -> None:
    event = outbox_event(available_at=NOW + timedelta(seconds=1))
    assert event.available_at == NOW + timedelta(seconds=1)

    with pytest.raises(InvalidDomainValueError, match="cannot predate"):
        outbox_event(available_at=NOW - timedelta(microseconds=1))
    with pytest.raises(NaiveDateTimeError, match="timezone-aware"):
        outbox_event(occurred_at=NOW.replace(tzinfo=None))


def test_claim_preserves_delivery_metadata() -> None:
    claim = OutboxClaim(4, outbox_event(), 2, OpaqueIdentifier("worker-1"), NOW)
    assert claim.sequence == 4
    assert claim.attempt == 2
    assert claim.lease_expires_at == NOW


@pytest.mark.parametrize(("field", "value"), [("sequence", 0), ("attempt", True)])
def test_claim_requires_positive_integer_metadata(field: str, value: object) -> None:
    values: dict[str, object] = {
        "sequence": 1,
        "event": outbox_event(),
        "attempt": 1,
        "worker_id": OpaqueIdentifier("worker-1"),
        "lease_expires_at": NOW,
    }
    values[field] = value
    with pytest.raises(InvalidDomainValueError, match="positive integer"):
        OutboxClaim(**values)  # type: ignore[arg-type]
