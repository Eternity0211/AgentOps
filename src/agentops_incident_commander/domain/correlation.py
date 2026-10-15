"""Versioned, content-free correlation links for the control-plane safety chain."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import InvalidDomainValueError
from .values import (
    CausationId,
    CorrelationEventId,
    CorrelationId,
    IncidentId,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    TraceId,
    as_utc,
)

CORRELATION_LINK_SCHEMA_VERSION = "1.0.0"
MAX_CORRELATION_LINKS = 10_000


class CorrelationComponent(StrEnum):
    """Closed set of control-plane stages required by the Phase 11 chain."""

    ALERT = "ALERT"
    INCIDENT = "INCIDENT"
    GRAPH = "GRAPH"
    TOOL = "TOOL"
    MODEL = "MODEL"
    APPROVAL = "APPROVAL"
    EXECUTION = "EXECUTION"
    VERIFICATION = "VERIFICATION"


@dataclass(frozen=True, slots=True)
class CorrelationLink:
    """One immutable event-to-resource link without request or telemetry payloads."""

    event_id: CorrelationEventId
    tenant_id: TenantId
    incident_id: IncidentId
    component: CorrelationComponent
    resource_id: OpaqueIdentifier
    trace_id: TraceId
    correlation_id: CorrelationId
    causation_id: CausationId | None
    occurred_at: datetime
    schema_version: str = CORRELATION_LINK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CORRELATION_LINK_SCHEMA_VERSION:
            raise InvalidDomainValueError("unsupported correlation-link schema version")
        if not isinstance(self.event_id, CorrelationEventId):
            raise InvalidDomainValueError("correlation link requires a typed event ID")
        if not isinstance(self.tenant_id, TenantId):
            raise InvalidDomainValueError("correlation link requires a typed tenant ID")
        if not isinstance(self.incident_id, IncidentId):
            raise InvalidDomainValueError("correlation link requires a typed incident ID")
        if not isinstance(self.component, CorrelationComponent):
            raise InvalidDomainValueError("correlation link requires a typed component")
        if not isinstance(self.resource_id, OpaqueIdentifier):
            raise InvalidDomainValueError("correlation link requires a typed resource ID")
        if not isinstance(self.trace_id, TraceId):
            raise InvalidDomainValueError("correlation link requires a typed trace ID")
        if not isinstance(self.correlation_id, CorrelationId):
            raise InvalidDomainValueError("correlation link requires a typed correlation ID")
        if self.causation_id is not None and not isinstance(self.causation_id, CausationId):
            raise InvalidDomainValueError("correlation link causation ID must be typed")
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))


def correlation_link_fingerprint(link: CorrelationLink) -> Sha256Digest:
    """Return the canonical content fingerprint used for replay and corruption checks."""

    document = {
        "causation_id": None if link.causation_id is None else link.causation_id.value,
        "component": link.component.value,
        "correlation_id": link.correlation_id.value,
        "event_id": link.event_id.value,
        "incident_id": link.incident_id.value,
        "occurred_at": link.occurred_at.isoformat(),
        "resource_id": link.resource_id.value,
        "schema_version": link.schema_version,
        "tenant_id": link.tenant_id.value,
        "trace_id": link.trace_id.value,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return Sha256Digest(hashlib.sha256(encoded).hexdigest())


@dataclass(frozen=True, slots=True)
class CorrelationTimeline:
    """Chronological, same-Incident correlation links with resolvable causation."""

    links: tuple[CorrelationLink, ...]

    def __post_init__(self) -> None:
        if not self.links or len(self.links) > MAX_CORRELATION_LINKS:
            raise InvalidDomainValueError(
                f"correlation timeline must contain 1-{MAX_CORRELATION_LINKS} links"
            )
        first = self.links[0]
        expected_scope = (first.tenant_id, first.incident_id, first.correlation_id)
        prior_events: dict[str, CorrelationLink] = {}
        previous_order: tuple[datetime, str] | None = None
        resources: set[tuple[CorrelationComponent, str]] = set()
        for link in self.links:
            if (link.tenant_id, link.incident_id, link.correlation_id) != expected_scope:
                raise InvalidDomainValueError(
                    "correlation timeline cannot mix tenant, Incident, or correlation scope"
                )
            order = (link.occurred_at, link.event_id.value)
            if previous_order is not None and order <= previous_order:
                raise InvalidDomainValueError(
                    "correlation timeline must be strictly ordered by time and event ID"
                )
            previous_order = order
            if link.event_id.value in prior_events:
                raise InvalidDomainValueError("correlation event IDs must be unique")
            resource_key = (link.component, link.resource_id.value)
            if resource_key in resources:
                raise InvalidDomainValueError(
                    "a component resource can appear only once in a correlation timeline"
                )
            resources.add(resource_key)
            if link.causation_id is None:
                if link.component is not CorrelationComponent.ALERT or prior_events:
                    raise InvalidDomainValueError(
                        "a correlation timeline requires exactly one leading Alert root"
                    )
            elif link.causation_id.value not in prior_events:
                raise InvalidDomainValueError(
                    "correlation causation must resolve to an earlier event in the same timeline"
                )
            prior_events[link.event_id.value] = link

    @property
    def tenant_id(self) -> TenantId:
        return self.links[0].tenant_id

    @property
    def incident_id(self) -> IncidentId:
        return self.links[0].incident_id

    @property
    def correlation_id(self) -> CorrelationId:
        return self.links[0].correlation_id

    def missing_components(self) -> frozenset[CorrelationComponent]:
        present = {link.component for link in self.links}
        return frozenset(CorrelationComponent) - present

    def require_complete(self) -> None:
        missing = self.missing_components()
        if missing:
            names = ", ".join(sorted(component.value for component in missing))
            raise InvalidDomainValueError(f"correlation timeline is missing components: {names}")
