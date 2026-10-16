"""Pure append-only audit event contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from .errors import InvalidDomainValueError
from .values import (
    ActorId,
    AuditEventId,
    CausationId,
    CorrelationId,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    as_utc,
)

_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*){1,7}$")
_VERSION_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}/v[1-9][0-9]*$")
AUDIT_INTEGRITY_SCHEMA_VERSION: Final = "audit-integrity/v1"
AUDIT_EXPORT_SCHEMA_VERSION: Final = "audit-export/v1"
MAX_AUDIT_EXPORT_EVENTS: Final = 100


@dataclass(frozen=True, slots=True)
class AuditTarget:
    """Typed target reference without embedding mutable target content."""

    type: str
    id: OpaqueIdentifier

    def __post_init__(self) -> None:
        if _TYPE_PATTERN.fullmatch(self.type) is None:
            raise InvalidDomainValueError("audit target type must be a dotted lowercase name")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Immutable audit event staged for database sequence assignment."""

    id: AuditEventId
    tenant_id: TenantId
    type: str
    event_version: int
    payload_schema_version: str
    actor_id: ActorId
    correlation_id: CorrelationId
    causation_id: CausationId
    target: AuditTarget
    occurred_at: datetime
    request_hash: Sha256Digest | None = None
    result_hash: Sha256Digest | None = None

    def __post_init__(self) -> None:
        if _TYPE_PATTERN.fullmatch(self.type) is None:
            raise InvalidDomainValueError("audit event type must be a dotted lowercase name")
        if (
            not isinstance(self.event_version, int)
            or isinstance(self.event_version, bool)
            or self.event_version < 1
        ):
            raise InvalidDomainValueError("audit event version must be a positive integer")
        if _VERSION_PATTERN.fullmatch(self.payload_schema_version) is None:
            raise InvalidDomainValueError("payload schema version must use name/vN format")
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))


@dataclass(frozen=True, slots=True)
class StoredAuditEvent:
    """Audit event with verified database-assigned global and tenant sequences."""

    sequence: int
    tenant_sequence: int
    event: AuditEvent
    event_fingerprint: Sha256Digest

    def __post_init__(self) -> None:
        for value, field in (
            (self.sequence, "global"),
            (self.tenant_sequence, "tenant"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise InvalidDomainValueError(f"audit {field} sequence must be a positive integer")
        if not isinstance(self.event, AuditEvent) or not isinstance(
            self.event_fingerprint, Sha256Digest
        ):
            raise InvalidDomainValueError("stored audit event types are invalid")
        if self.event_fingerprint != audit_event_fingerprint(self.event):
            raise InvalidDomainValueError("stored audit event fingerprint is invalid")


def _audit_event_document(event: AuditEvent) -> dict[str, object]:
    return {
        "actor_id": event.actor_id.value,
        "causation_id": event.causation_id.value,
        "correlation_id": event.correlation_id.value,
        "event_id": event.id.value,
        "event_type": event.type,
        "event_version": event.event_version,
        "occurred_at": event.occurred_at.isoformat(),
        "payload_schema_version": event.payload_schema_version,
        "request_hash": None if event.request_hash is None else event.request_hash.value,
        "result_hash": None if event.result_hash is None else event.result_hash.value,
        "schema_version": AUDIT_INTEGRITY_SCHEMA_VERSION,
        "target_id": event.target.id.value,
        "target_type": event.target.type,
        "tenant_id": event.tenant_id.value,
    }


def audit_event_fingerprint(event: AuditEvent) -> Sha256Digest:
    """Hash every immutable event field using one versioned canonical representation."""
    if not isinstance(event, AuditEvent):
        raise InvalidDomainValueError("audit fingerprint requires a typed event")
    canonical = json.dumps(
        _audit_event_document(event),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return Sha256Digest(hashlib.sha256(canonical).hexdigest())


@dataclass(frozen=True, slots=True)
class AuditExportManifest:
    """Content-free integrity manifest for one authorized tenant export page."""

    tenant_id: TenantId
    after_sequence: int
    first_sequence: int | None
    last_sequence: int | None
    item_count: int
    page_fingerprint: Sha256Digest
    next_after_sequence: int | None
    schema_version: str = AUDIT_EXPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, TenantId):
            raise InvalidDomainValueError("audit export manifest tenant is invalid")
        for number, field in (
            (self.after_sequence, "cursor"),
            (self.item_count, "item count"),
        ):
            if not isinstance(number, int) or isinstance(number, bool) or number < 0:
                raise InvalidDomainValueError(
                    f"audit export manifest {field} must be a non-negative integer"
                )
        if self.item_count > MAX_AUDIT_EXPORT_EVENTS:
            raise InvalidDomainValueError("audit export manifest item count is unbounded")
        for sequence, field in (
            (self.first_sequence, "first sequence"),
            (self.last_sequence, "last sequence"),
            (self.next_after_sequence, "next cursor"),
        ):
            if sequence is not None and (
                not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1
            ):
                raise InvalidDomainValueError(
                    f"audit export manifest {field} must be a positive integer"
                )
        if not isinstance(self.page_fingerprint, Sha256Digest):
            raise InvalidDomainValueError("audit export manifest fingerprint is invalid")
        if self.schema_version != AUDIT_EXPORT_SCHEMA_VERSION:
            raise InvalidDomainValueError("audit export manifest schema version is invalid")
        empty = self.item_count == 0
        if empty != (self.first_sequence is None and self.last_sequence is None):
            raise InvalidDomainValueError("audit export manifest range is inconsistent")
        if not empty:
            assert self.first_sequence is not None
            assert self.last_sequence is not None
            if self.first_sequence != self.after_sequence + 1:
                raise InvalidDomainValueError("audit export manifest first sequence is invalid")
            if self.last_sequence - self.first_sequence + 1 != self.item_count:
                raise InvalidDomainValueError("audit export manifest range is not contiguous")
        if self.next_after_sequence is not None and self.next_after_sequence != self.last_sequence:
            raise InvalidDomainValueError("audit export manifest next cursor is invalid")


@dataclass(frozen=True, slots=True)
class AuditExportPage:
    """A bounded, tenant-contiguous audit page plus its reproducible manifest."""

    events: tuple[StoredAuditEvent, ...]
    manifest: AuditExportManifest

    def __post_init__(self) -> None:
        if not isinstance(self.events, tuple) or not isinstance(self.manifest, AuditExportManifest):
            raise InvalidDomainValueError("audit export page types are invalid")
        if len(self.events) != self.manifest.item_count:
            raise InvalidDomainValueError("audit export page count does not match its manifest")
        _validate_audit_export_events(
            self.events,
            tenant_id=self.manifest.tenant_id,
            after_sequence=self.manifest.after_sequence,
        )
        expected = _audit_export_page_fingerprint(
            self.events,
            tenant_id=self.manifest.tenant_id,
            after_sequence=self.manifest.after_sequence,
            has_more=self.manifest.next_after_sequence is not None,
        )
        if expected != self.manifest.page_fingerprint:
            raise InvalidDomainValueError(
                "audit export page fingerprint does not match its manifest"
            )


def _validate_audit_export_events(
    events: tuple[StoredAuditEvent, ...],
    *,
    tenant_id: TenantId,
    after_sequence: int,
) -> tuple[int | None, int | None]:
    expected = after_sequence + 1
    seen_global: set[int] = set()
    seen_ids: set[str] = set()
    for stored in events:
        if not isinstance(stored, StoredAuditEvent):
            raise InvalidDomainValueError("audit export contains an invalid stored event")
        if stored.event.tenant_id != tenant_id:
            raise InvalidDomainValueError("audit export contains a cross-tenant event")
        if stored.tenant_sequence != expected:
            raise InvalidDomainValueError("audit export tenant sequence is not contiguous")
        if stored.sequence in seen_global or stored.event.id.value in seen_ids:
            raise InvalidDomainValueError("audit export contains duplicate event identity")
        expected += 1
        seen_global.add(stored.sequence)
        seen_ids.add(stored.event.id.value)
    return (
        events[0].tenant_sequence if events else None,
        events[-1].tenant_sequence if events else None,
    )


def _audit_export_page_fingerprint(
    events: tuple[StoredAuditEvent, ...],
    *,
    tenant_id: TenantId,
    after_sequence: int,
    has_more: bool,
) -> Sha256Digest:
    document = {
        "after_sequence": after_sequence,
        "events": [
            {
                "event_fingerprint": stored.event_fingerprint.value,
                "event_id": stored.event.id.value,
                "global_sequence": stored.sequence,
                "tenant_sequence": stored.tenant_sequence,
            }
            for stored in events
        ],
        "has_more": has_more,
        "schema_version": AUDIT_EXPORT_SCHEMA_VERSION,
        "tenant_id": tenant_id.value,
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return Sha256Digest(hashlib.sha256(canonical).hexdigest())


def build_audit_export_page(
    events: tuple[StoredAuditEvent, ...],
    *,
    tenant_id: TenantId,
    after_sequence: int,
    has_more: bool,
) -> AuditExportPage:
    """Validate tenant sequence continuity and bind a deterministic page manifest."""
    if not isinstance(tenant_id, TenantId):
        raise InvalidDomainValueError("audit export tenant is invalid")
    if (
        not isinstance(after_sequence, int)
        or isinstance(after_sequence, bool)
        or after_sequence < 0
    ):
        raise InvalidDomainValueError("audit export cursor must be a non-negative integer")
    if not isinstance(events, tuple) or len(events) > MAX_AUDIT_EXPORT_EVENTS:
        raise InvalidDomainValueError("audit export page must be a bounded tuple")
    if not isinstance(has_more, bool) or (has_more and not events):
        raise InvalidDomainValueError("audit export continuation state is invalid")

    first, last = _validate_audit_export_events(
        events,
        tenant_id=tenant_id,
        after_sequence=after_sequence,
    )
    manifest = AuditExportManifest(
        tenant_id=tenant_id,
        after_sequence=after_sequence,
        first_sequence=first,
        last_sequence=last,
        item_count=len(events),
        page_fingerprint=_audit_export_page_fingerprint(
            events,
            tenant_id=tenant_id,
            after_sequence=after_sequence,
            has_more=has_more,
        ),
        next_after_sequence=last if has_more else None,
    )
    return AuditExportPage(events, manifest)
