"""Tests for immutable audit-domain contracts and export integrity."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from agentops_incident_commander.domain import (
    AUDIT_EXPORT_SCHEMA_VERSION,
    ActorId,
    AuditEvent,
    AuditEventId,
    AuditExportManifest,
    AuditExportPage,
    AuditTarget,
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    NaiveDateTimeError,
    Sha256Digest,
    StoredAuditEvent,
    TenantId,
    audit_event_fingerprint,
    build_audit_export_page,
)


def audit_event(**overrides: object) -> AuditEvent:
    values: dict[str, object] = {
        "id": AuditEventId("audit-1"),
        "tenant_id": TenantId("tenant-1"),
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


def stored(
    sequence: int = 7,
    tenant_sequence: int = 1,
    **event_overrides: object,
) -> StoredAuditEvent:
    event = audit_event(**event_overrides)
    return StoredAuditEvent(
        sequence,
        tenant_sequence,
        event,
        audit_event_fingerprint(event),
    )


def manifest(**overrides: object) -> AuditExportManifest:
    values: dict[str, object] = {
        "tenant_id": TenantId("tenant-1"),
        "after_sequence": 0,
        "first_sequence": 1,
        "last_sequence": 1,
        "item_count": 1,
        "page_fingerprint": Sha256Digest("c" * 64),
        "next_after_sequence": None,
        "schema_version": AUDIT_EXPORT_SCHEMA_VERSION,
    }
    values.update(overrides)
    return AuditExportManifest(**values)  # type: ignore[arg-type]


def test_audit_event_preserves_typed_provenance_and_normalizes_time() -> None:
    event = audit_event()
    fingerprint = audit_event_fingerprint(event)

    assert event.occurred_at == datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    assert event.target.id == IncidentId("incident-1")
    assert str(event.request_hash) == "a" * 64
    assert stored().event_fingerprint == fingerprint
    assert audit_event_fingerprint(replace(event)) == fingerprint
    assert audit_event_fingerprint(replace(event, actor_id=ActorId("operator-2"))) != fingerprint


def test_audit_fingerprint_rejects_untyped_input() -> None:
    with pytest.raises(InvalidDomainValueError, match="typed event"):
        audit_event_fingerprint(object())  # type: ignore[arg-type]


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


@pytest.mark.parametrize("field", ["sequence", "tenant_sequence"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_stored_audit_sequences_must_be_positive(field: str, value: object) -> None:
    event = audit_event()
    values = {
        "sequence": 1,
        "tenant_sequence": 1,
        "event": event,
        "event_fingerprint": audit_event_fingerprint(event),
    }
    values[field] = value
    with pytest.raises(InvalidDomainValueError, match="positive integer"):
        StoredAuditEvent(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"event": object()}, "types"),
        ({"event_fingerprint": object()}, "types"),
        ({"event_fingerprint": Sha256Digest("d" * 64)}, "fingerprint"),
    ],
)
def test_stored_audit_event_rejects_invalid_types_or_fingerprint(
    overrides: dict[str, object], message: str
) -> None:
    event = audit_event()
    values: dict[str, object] = {
        "sequence": 1,
        "tenant_sequence": 1,
        "event": event,
        "event_fingerprint": audit_event_fingerprint(event),
    }
    values.update(overrides)
    with pytest.raises(InvalidDomainValueError, match=message):
        StoredAuditEvent(**values)  # type: ignore[arg-type]


def test_export_page_is_tenant_contiguous_deterministic_and_bounded() -> None:
    events = (
        stored(7, 1),
        stored(9, 2, id=AuditEventId("audit-2")),
    )
    first = build_audit_export_page(
        events,
        tenant_id=TenantId("tenant-1"),
        after_sequence=0,
        has_more=True,
    )
    replay = build_audit_export_page(
        events,
        tenant_id=TenantId("tenant-1"),
        after_sequence=0,
        has_more=True,
    )

    assert first == replay
    assert first.manifest.first_sequence == 1
    assert first.manifest.last_sequence == 2
    assert first.manifest.item_count == 2
    assert first.manifest.next_after_sequence == 2
    assert first.manifest.schema_version == AUDIT_EXPORT_SCHEMA_VERSION

    empty = build_audit_export_page(
        (),
        tenant_id=TenantId("tenant-1"),
        after_sequence=2,
        has_more=False,
    )
    assert empty.manifest.first_sequence is None
    assert empty.manifest.last_sequence is None
    assert empty.manifest.next_after_sequence is None


@pytest.mark.parametrize(
    ("events", "tenant_id", "after_sequence", "has_more", "message"),
    [
        ((), "tenant-1", 0, False, "tenant"),
        ((), TenantId("tenant-1"), -1, False, "cursor"),
        ([], TenantId("tenant-1"), 0, False, "bounded tuple"),
        (
            tuple(
                stored(index + 1, index + 1, id=AuditEventId(f"audit-{index + 1}"))
                for index in range(101)
            ),
            TenantId("tenant-1"),
            0,
            False,
            "bounded tuple",
        ),
        ((), TenantId("tenant-1"), 0, "yes", "continuation"),
        ((), TenantId("tenant-1"), 0, True, "continuation"),
        ((object(),), TenantId("tenant-1"), 0, False, "invalid stored"),
        (
            (stored(1, 1, tenant_id=TenantId("tenant-2")),),
            TenantId("tenant-1"),
            0,
            False,
            "cross-tenant",
        ),
        ((stored(1, 2),), TenantId("tenant-1"), 0, False, "not contiguous"),
        (
            (stored(1, 1), stored(1, 2, id=AuditEventId("audit-2"))),
            TenantId("tenant-1"),
            0,
            False,
            "duplicate",
        ),
        (
            (stored(1, 1), stored(2, 2)),
            TenantId("tenant-1"),
            0,
            False,
            "duplicate",
        ),
    ],
)
def test_export_page_rejects_invalid_scope_sequence_and_identity(
    events: Any,
    tenant_id: Any,
    after_sequence: Any,
    has_more: Any,
    message: str,
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        build_audit_export_page(
            events,
            tenant_id=tenant_id,
            after_sequence=after_sequence,
            has_more=has_more,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant_id": "tenant-1"}, "tenant"),
        ({"after_sequence": -1}, "cursor"),
        ({"after_sequence": True}, "cursor"),
        ({"item_count": -1}, "item count"),
        ({"item_count": True}, "item count"),
        ({"item_count": 101}, "unbounded"),
        ({"first_sequence": 0}, "first sequence"),
        ({"last_sequence": True}, "last sequence"),
        ({"next_after_sequence": -1}, "next cursor"),
        ({"page_fingerprint": "c" * 64}, "fingerprint"),
        ({"schema_version": "audit-export/v2"}, "schema version"),
        ({"item_count": 0}, "range is inconsistent"),
        ({"first_sequence": None, "last_sequence": None}, "range is inconsistent"),
        ({"after_sequence": 2}, "first sequence"),
        ({"last_sequence": 2}, "range is not contiguous"),
        ({"next_after_sequence": 2}, "next cursor"),
    ],
)
def test_export_manifest_rejects_inconsistent_fields(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        manifest(**overrides)


def test_export_page_contract_rejects_invalid_types_and_count() -> None:
    valid_manifest = manifest()
    with pytest.raises(InvalidDomainValueError, match="types"):
        AuditExportPage([], valid_manifest)  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="types"):
        AuditExportPage((), object())  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="count"):
        AuditExportPage((), valid_manifest)

    built = build_audit_export_page(
        (stored(),),
        tenant_id=TenantId("tenant-1"),
        after_sequence=0,
        has_more=False,
    )
    with pytest.raises(InvalidDomainValueError, match="fingerprint"):
        AuditExportPage(
            built.events,
            replace(built.manifest, page_fingerprint=Sha256Digest("d" * 64)),
        )
