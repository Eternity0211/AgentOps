"""Tests for the versioned incident/control-plane correlation contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from agentops_incident_commander.domain import (
    CORRELATION_LINK_SCHEMA_VERSION,
    MAX_CORRELATION_LINKS,
    CausationId,
    CorrelationComponent,
    CorrelationEventId,
    CorrelationId,
    CorrelationLink,
    CorrelationTimeline,
    IncidentId,
    InvalidDomainValueError,
    NaiveDateTimeError,
    OpaqueIdentifier,
    TenantId,
    TraceId,
    correlation_link_fingerprint,
)

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
TENANT = TenantId("tenant-1")
INCIDENT = IncidentId("incident-1")
CORRELATION = CorrelationId("correlation-1")
TRACE = TraceId("0123456789abcdef0123456789abcdef")


def link(
    component: CorrelationComponent,
    index: int,
    *,
    cause: int | None = None,
) -> CorrelationLink:
    return CorrelationLink(
        event_id=CorrelationEventId(f"event-{index}"),
        tenant_id=TENANT,
        incident_id=INCIDENT,
        component=component,
        resource_id=OpaqueIdentifier(f"resource-{index}"),
        trace_id=TRACE,
        correlation_id=CORRELATION,
        causation_id=None if cause is None else CausationId(f"event-{cause}"),
        occurred_at=NOW + timedelta(seconds=index),
    )


def complete_links() -> tuple[CorrelationLink, ...]:
    return tuple(
        link(component, index, cause=None if index == 1 else index - 1)
        for index, component in enumerate(CorrelationComponent, start=1)
    )


def test_complete_timeline_covers_every_required_component() -> None:
    """One chain reconstructs all eight required platform stages."""
    timeline = CorrelationTimeline(complete_links())

    assert timeline.tenant_id == TENANT
    assert timeline.incident_id == INCIDENT
    assert timeline.correlation_id == CORRELATION
    assert timeline.missing_components() == frozenset()
    timeline.require_complete()


def test_fingerprint_is_canonical_and_sensitive_to_every_link_field() -> None:
    """Replay fingerprints are stable and detect content substitution."""
    original = link(CorrelationComponent.ALERT, 1)

    assert correlation_link_fingerprint(original) == correlation_link_fingerprint(original)
    assert correlation_link_fingerprint(original) != correlation_link_fingerprint(
        replace(original, trace_id=TraceId("1123456789abcdef0123456789abcdef"))
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event_id", object(), "event ID"),
        ("tenant_id", object(), "tenant ID"),
        ("incident_id", object(), "incident ID"),
        ("component", "ALERT", "component"),
        ("resource_id", object(), "resource ID"),
        ("trace_id", object(), "trace ID"),
        ("correlation_id", object(), "correlation ID"),
        ("causation_id", object(), "causation ID"),
    ],
)
def test_link_rejects_untyped_identity_fields(field: str, value: object, message: str) -> None:
    """Callers cannot swap raw or cross-domain identities into the ledger."""
    values = {field: value}
    with pytest.raises(InvalidDomainValueError, match=message):
        replace(link(CorrelationComponent.ALERT, 1), **values)  # type: ignore[arg-type]


def test_link_rejects_unknown_schema_and_naive_time() -> None:
    with pytest.raises(InvalidDomainValueError, match="schema version"):
        replace(link(CorrelationComponent.ALERT, 1), schema_version="2.0.0")
    with pytest.raises(NaiveDateTimeError, match="timezone-aware"):
        replace(link(CorrelationComponent.ALERT, 1), occurred_at=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("scope", ["tenant_id", "incident_id", "correlation_id"])
def test_timeline_rejects_mixed_scope(scope: str) -> None:
    links = list(complete_links())
    replacement: object
    if scope == "tenant_id":
        replacement = TenantId("tenant-2")
    elif scope == "incident_id":
        replacement = IncidentId("incident-2")
    else:
        replacement = CorrelationId("correlation-2")
    links[1] = replace(links[1], **{scope: replacement})  # type: ignore[arg-type]

    with pytest.raises(InvalidDomainValueError, match="cannot mix"):
        CorrelationTimeline(tuple(links))


def test_timeline_rejects_invalid_order_duplicate_event_and_resource() -> None:
    links = complete_links()
    with pytest.raises(InvalidDomainValueError, match="strictly ordered"):
        CorrelationTimeline(
            (
                replace(links[0], occurred_at=NOW + timedelta(seconds=2)),
                replace(links[1], occurred_at=NOW + timedelta(seconds=1)),
            )
        )
    with pytest.raises(InvalidDomainValueError, match="event IDs must be unique"):
        CorrelationTimeline((links[0], replace(links[1], event_id=links[0].event_id)))
    with pytest.raises(InvalidDomainValueError, match="component resource"):
        CorrelationTimeline(
            (
                links[0],
                replace(
                    links[1],
                    component=links[0].component,
                    resource_id=links[0].resource_id,
                ),
            )
        )


def test_timeline_rejects_non_alert_root_and_unresolved_or_forward_cause() -> None:
    with pytest.raises(InvalidDomainValueError, match="leading Alert root"):
        CorrelationTimeline((link(CorrelationComponent.INCIDENT, 1),))
    with pytest.raises(InvalidDomainValueError, match="leading Alert root"):
        CorrelationTimeline(
            (link(CorrelationComponent.ALERT, 1), link(CorrelationComponent.ALERT, 2))
        )
    with pytest.raises(InvalidDomainValueError, match="resolve to an earlier event"):
        CorrelationTimeline((link(CorrelationComponent.ALERT, 1, cause=9),))
    with pytest.raises(InvalidDomainValueError, match="resolve to an earlier event"):
        CorrelationTimeline(
            (
                link(CorrelationComponent.ALERT, 1),
                link(CorrelationComponent.INCIDENT, 2, cause=3),
                link(CorrelationComponent.GRAPH, 3, cause=1),
            )
        )


def test_timeline_reports_missing_components_and_rejects_invalid_size() -> None:
    timeline = CorrelationTimeline((link(CorrelationComponent.ALERT, 1),))
    assert timeline.missing_components() == frozenset(CorrelationComponent) - {
        CorrelationComponent.ALERT
    }
    with pytest.raises(InvalidDomainValueError, match="missing components"):
        timeline.require_complete()
    with pytest.raises(InvalidDomainValueError, match=f"1-{MAX_CORRELATION_LINKS}"):
        CorrelationTimeline(())
    with pytest.raises(InvalidDomainValueError, match=f"1-{MAX_CORRELATION_LINKS}"):
        CorrelationTimeline(cast(tuple[CorrelationLink, ...], (timeline.links[0],) * 10_001))


def test_schema_version_is_explicit_and_stable() -> None:
    assert CORRELATION_LINK_SCHEMA_VERSION == "1.0.0"
