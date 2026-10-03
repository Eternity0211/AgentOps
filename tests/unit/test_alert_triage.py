"""Tests for deterministic Alert fingerprinting, deduplication, merge, and triage."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from itertools import count

import pytest

from agentops_incident_commander.domain import (
    FINGERPRINT_SCHEMA_VERSION,
    AggregateVersion,
    Alert,
    AlertDeduplicator,
    AlertDimension,
    AlertFingerprint,
    AlertGroup,
    AlertGroupId,
    AlertId,
    AlertTriageAction,
    IncidentSeverity,
    InvalidDomainValueError,
    OptimisticVersionError,
    TenantId,
)

BASE_TIME = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)


def make_alert(
    alert_id: str = "alert-1",
    *,
    minute: int = 0,
    received_minute: int | None = None,
    tenant: str = "tenant-1",
    environment: str = "production",
    service: str = "order-service",
    rule: str = "http-error-rate",
    severity: IncidentSeverity = IncidentSeverity.SEV3,
    dimensions: tuple[AlertDimension, ...] = (
        AlertDimension("region", "cn-east-1"),
        AlertDimension("route", "/orders"),
    ),
) -> Alert:
    """Create a normalized Alert with independently selectable identity fields."""
    received = minute if received_minute is None else received_minute
    return Alert(
        id=AlertId(alert_id),
        tenant_id=TenantId(tenant),
        environment=environment,
        service=service,
        rule=rule,
        severity=severity,
        observed_at=BASE_TIME + timedelta(minutes=minute),
        received_at=BASE_TIME + timedelta(minutes=received),
        dimensions=dimensions,
    )


def id_factory() -> Callable[[], AlertGroupId]:
    """Return a deterministic callable producing unique group IDs."""
    sequence = count(1)
    return lambda: AlertGroupId(f"group-{next(sequence)}")


def deduplicator(window_minutes: int = 5) -> AlertDeduplicator:
    """Build a coordinator with deterministic IDs."""
    factory = id_factory()
    return AlertDeduplicator(
        window=timedelta(minutes=window_minutes),
        group_id_factory=factory,
    )


def test_fingerprint_is_stable_order_independent_and_versioned() -> None:
    """Canonical field and dimension ordering produces one reproducible digest."""
    forward = make_alert()
    reverse = make_alert(
        "alert-2",
        minute=1,
        severity=IncidentSeverity.SEV1,
        dimensions=tuple(reversed(forward.dimensions)),
    )

    assert forward.fingerprint() == reverse.fingerprint()
    assert forward.fingerprint().schema_version == FINGERPRINT_SCHEMA_VERSION
    assert forward.fingerprint().value == (
        "6a98431b728b46f82f0ea882ba47a75ab211a1eed6dbb3b010bc6dfb2c5f4a17"
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"tenant": "tenant-2"},
        {"environment": "staging"},
        {"service": "payment-service"},
        {"rule": "latency-p95"},
        {"dimensions": (AlertDimension("region", "cn-west-1"),)},
    ],
)
def test_every_grouping_scope_change_produces_a_different_fingerprint(
    changed: dict[str, object],
) -> None:
    """Tenant, environment, service, rule, and explicit dimensions never cross-merge."""
    baseline = make_alert().fingerprint()

    assert make_alert("alert-2", **changed).fingerprint() != baseline  # type: ignore[arg-type]


def test_unicode_dimension_values_are_normalized_before_hashing() -> None:
    """Equivalent Unicode representations do not fragment groups."""
    composed = make_alert(
        dimensions=(AlertDimension("zone", "caf\N{LATIN SMALL LETTER E WITH ACUTE}"),)
    )
    decomposed = make_alert(
        "alert-2", dimensions=(AlertDimension("zone", "cafe\N{COMBINING ACUTE ACCENT}"),)
    )

    assert composed.dimensions == decomposed.dimensions
    assert composed.fingerprint() == decomposed.fingerprint()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment", ""),
        ("service", "contains space"),
        ("rule", "bad?rule"),
        ("service", "a" * 129),
    ],
)
def test_alert_rejects_invalid_grouping_names(field: str, value: str) -> None:
    """Grouping identity stays bounded and canonical."""
    arguments = {field: value}
    with pytest.raises(InvalidDomainValueError):
        make_alert(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "x\nvalue", "x\x7fvalue", "a" * 257])
def test_dimension_rejects_empty_control_or_unbounded_values(value: str) -> None:
    """Untrusted label values cannot inject controls or grow without bound."""
    with pytest.raises(InvalidDomainValueError, match="dimension value"):
        AlertDimension("region", value)


def test_dimension_rejects_invalid_name_and_alert_rejects_duplicate_names() -> None:
    """Canonical maps cannot contain invalid or ambiguous duplicate keys."""
    with pytest.raises(InvalidDomainValueError, match="dimension name"):
        AlertDimension("bad name", "value")

    with pytest.raises(InvalidDomainValueError, match="must be unique"):
        make_alert(
            dimensions=(
                AlertDimension("region", "east"),
                AlertDimension("region", "west"),
            )
        )


def test_alert_normalizes_aware_time_and_rejects_receipt_before_observation() -> None:
    """Alert chronology is UTC-aware and cannot run backwards."""
    local_zone = timezone(timedelta(hours=8))
    alert = Alert(
        id=AlertId("alert-1"),
        tenant_id=TenantId("tenant-1"),
        environment="production",
        service="order-service",
        rule="errors",
        severity=IncidentSeverity.SEV2,
        observed_at=datetime(2026, 10, 2, 16, 0, tzinfo=local_zone),
        received_at=datetime(2026, 10, 2, 16, 1, tzinfo=local_zone),
    )
    assert alert.observed_at == BASE_TIME
    assert alert.received_at == BASE_TIME + timedelta(minutes=1)

    with pytest.raises(InvalidDomainValueError, match="cannot predate"):
        make_alert(minute=1, received_minute=0)


@pytest.mark.parametrize(
    ("value", "schema"),
    [("not-a-digest", FINGERPRINT_SCHEMA_VERSION), ("0" * 64, "alert-fingerprint/v2")],
)
def test_fingerprint_value_and_schema_are_validated(value: str, schema: str) -> None:
    """Stored hashes cannot masquerade as another algorithm or schema."""
    with pytest.raises(InvalidDomainValueError, match=r"fingerprint|schema"):
        AlertFingerprint(value, schema)


def test_group_open_and_merge_tracks_range_count_version_and_escalation() -> None:
    """A unique matching Alert expands the group and can only raise severity."""
    group = AlertGroup.open(AlertGroupId("group-1"), make_alert(minute=2))
    earlier_critical = make_alert(
        "alert-2", minute=1, received_minute=3, severity=IncidentSeverity.SEV1
    )

    merged, action = group.merge(earlier_critical, expected_version=AggregateVersion(1))

    assert action is AlertTriageAction.MERGE_GROUP
    assert merged.severity is IncidentSeverity.SEV1
    assert merged.first_observed_at == BASE_TIME + timedelta(minutes=1)
    assert merged.last_observed_at == BASE_TIME + timedelta(minutes=2)
    assert merged.first_received_at == BASE_TIME + timedelta(minutes=2)
    assert merged.last_received_at == BASE_TIME + timedelta(minutes=3)
    assert merged.alert_ids == (AlertId("alert-1"), AlertId("alert-2"))
    assert merged.occurrence_count == 2
    assert merged.version == AggregateVersion(2)

    later_low = make_alert("alert-3", minute=4, received_minute=4, severity=IncidentSeverity.SEV4)
    merged_again, _ = merged.merge(later_low, expected_version=AggregateVersion(2))
    assert merged_again.severity is IncidentSeverity.SEV1
    assert merged_again.last_observed_at == BASE_TIME + timedelta(minutes=4)


def test_exact_alert_replay_is_idempotent_without_version_increment() -> None:
    """Delivery retries do not inflate occurrence counts or aggregate versions."""
    alert = make_alert()
    group = AlertGroup.open(AlertGroupId("group-1"), alert)

    replayed, action = group.merge(alert, expected_version=AggregateVersion(1))

    assert replayed is group
    assert action is AlertTriageAction.DUPLICATE
    assert replayed.occurrence_count == 1
    assert replayed.version == AggregateVersion(1)


def test_group_merge_rejects_stale_version_and_different_fingerprint() -> None:
    """Concurrent or cross-scope writes fail closed."""
    group = AlertGroup.open(AlertGroupId("group-1"), make_alert())
    with pytest.raises(OptimisticVersionError, match="expected version 2"):
        group.merge(make_alert("alert-2"), expected_version=AggregateVersion(2))
    with pytest.raises(InvalidDomainValueError, match="different fingerprint"):
        group.merge(
            make_alert("alert-2", tenant="tenant-2"),
            expected_version=AggregateVersion(1),
        )


def test_group_window_is_inclusive_and_requires_equal_fingerprint() -> None:
    """The exact time boundary merges, while one microsecond beyond opens a new group."""
    group = AlertGroup.open(AlertGroupId("group-1"), make_alert())
    window = timedelta(minutes=5)

    assert group.is_within(make_alert("alert-2", minute=5), window)
    beyond = replace_alert_time(make_alert("alert-3", minute=5), timedelta(microseconds=1))
    assert not group.is_within(beyond, window)
    assert not group.is_within(make_alert("alert-4", tenant="tenant-2"), window)


def replace_alert_time(alert: Alert, delta: timedelta) -> Alert:
    """Return an Alert shifted equally in observation and receipt time."""
    return Alert(
        id=alert.id,
        tenant_id=alert.tenant_id,
        environment=alert.environment,
        service=alert.service,
        rule=alert.rule,
        severity=alert.severity,
        observed_at=alert.observed_at + delta,
        received_at=alert.received_at + delta,
        dimensions=alert.dimensions,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"first_observed_at": BASE_TIME + timedelta(minutes=1)},
        {"first_received_at": BASE_TIME + timedelta(minutes=1)},
        {"alert_ids": ()},
        {"alert_ids": (AlertId("alert-1"), AlertId("alert-1")), "occurrence_count": 2},
        {"occurrence_count": 2},
    ],
)
def test_group_hydration_rejects_invalid_ranges_and_counts(
    overrides: dict[str, object],
) -> None:
    """Persistence adapters cannot hydrate a corrupt grouping aggregate."""
    alert = make_alert()
    arguments: dict[str, object] = {
        "id": AlertGroupId("group-1"),
        "fingerprint": alert.fingerprint(),
        "tenant_id": alert.tenant_id,
        "environment": alert.environment,
        "service": alert.service,
        "rule": alert.rule,
        "severity": alert.severity,
        "first_observed_at": BASE_TIME,
        "last_observed_at": BASE_TIME,
        "first_received_at": BASE_TIME,
        "last_received_at": BASE_TIME,
        "alert_ids": (alert.id,),
        "occurrence_count": 1,
        "version": AggregateVersion(1),
    }
    arguments.update(overrides)
    with pytest.raises(InvalidDomainValueError):
        AlertGroup(**arguments)  # type: ignore[arg-type]


def test_deduplicator_opens_merges_replays_and_splits_after_window() -> None:
    """The reference coordinator exposes every deterministic triage result."""
    engine = deduplicator()
    opened = engine.ingest(make_alert())
    merged = engine.ingest(make_alert("alert-2", minute=5))
    replayed = engine.ingest(make_alert("alert-2", minute=5))
    split = engine.ingest(make_alert("alert-3", minute=11))

    assert opened.action is AlertTriageAction.OPEN_GROUP
    assert merged.action is AlertTriageAction.MERGE_GROUP
    assert replayed.action is AlertTriageAction.DUPLICATE
    assert split.action is AlertTriageAction.OPEN_GROUP
    assert opened.fingerprint == merged.fingerprint == split.fingerprint
    assert [group.id for group in engine.groups()] == [
        AlertGroupId("group-1"),
        AlertGroupId("group-2"),
    ]
    assert [group.occurrence_count for group in engine.groups()] == [2, 1]


def test_deduplicator_keeps_tenant_and_service_scopes_separate() -> None:
    """Equal rules and times cannot merge across authorization or service scope."""
    engine = deduplicator()
    decisions = [
        engine.ingest(make_alert()),
        engine.ingest(make_alert("alert-2", tenant="tenant-2")),
        engine.ingest(make_alert("alert-3", service="payment-service")),
    ]

    assert all(decision.action is AlertTriageAction.OPEN_GROUP for decision in decisions)
    assert len(engine.groups()) == 3


def test_deduplicator_selects_nearest_group_deterministically_when_windows_overlap() -> None:
    """Out-of-order arrivals use stable distance/time/ID tie breakers."""
    engine = deduplicator()
    first = engine.ingest(make_alert(minute=0)).group
    second = engine.ingest(make_alert("alert-2", minute=11)).group
    engine.ingest(make_alert("alert-3", minute=5))

    decision = engine.ingest(make_alert("alert-4", minute=6))

    assert decision.group.id == first.id
    assert decision.group.occurrence_count == 3
    assert next(group for group in engine.groups() if group.id == second.id).occurrence_count == 1


def test_deduplicator_rejects_non_positive_window() -> None:
    """A zero or negative deduplication window is never silently accepted."""
    factory = id_factory()
    with pytest.raises(InvalidDomainValueError, match="must be positive"):
        AlertDeduplicator(
            window=timedelta(0),
            group_id_factory=factory,
        )


def test_concurrent_unique_alerts_create_one_group_without_lost_updates() -> None:
    """A race of unique deliveries retains every occurrence in one aggregate."""
    engine = deduplicator()
    alerts = [make_alert(f"alert-{index}") for index in range(1, 65)]

    with ThreadPoolExecutor(max_workers=16) as executor:
        decisions = list(executor.map(engine.ingest, alerts))

    groups = engine.groups()
    assert len(groups) == 1
    assert groups[0].occurrence_count == 64
    assert len(set(groups[0].alert_ids)) == 64
    assert groups[0].version == AggregateVersion(64)
    assert sum(decision.action is AlertTriageAction.OPEN_GROUP for decision in decisions) == 1
    assert sum(decision.action is AlertTriageAction.MERGE_GROUP for decision in decisions) == 63


def test_concurrent_replays_remain_one_occurrence() -> None:
    """A delivery retry storm is idempotent under the coordinator lock."""
    engine = deduplicator()
    alert = make_alert()

    with ThreadPoolExecutor(max_workers=16) as executor:
        decisions = list(executor.map(engine.ingest, [alert] * 64))

    assert engine.groups()[0].occurrence_count == 1
    assert engine.groups()[0].version == AggregateVersion(1)
    assert sum(decision.action is AlertTriageAction.OPEN_GROUP for decision in decisions) == 1
    assert sum(decision.action is AlertTriageAction.DUPLICATE for decision in decisions) == 63
