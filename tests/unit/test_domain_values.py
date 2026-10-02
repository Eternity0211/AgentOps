"""Tests for framework-free domain value objects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    AlertId,
    CausationId,
    CorrelationId,
    EventReason,
    IncidentId,
    InvalidDomainValueError,
    InvalidIdentifierError,
    NaiveDateTimeError,
    OpaqueIdentifier,
    as_utc,
    utc_now,
)


@pytest.mark.parametrize(
    "identifier_type",
    [OpaqueIdentifier, IncidentId, AlertId, ActorId, CorrelationId, CausationId],
)
def test_opaque_identifier_types_preserve_valid_values(
    identifier_type: type[OpaqueIdentifier],
) -> None:
    """Every public ID type retains a conservative opaque value."""
    identifier = identifier_type("01J_TEST.id:-42")

    assert identifier.value == "01J_TEST.id:-42"
    assert str(identifier) == "01J_TEST.id:-42"


@pytest.mark.parametrize(
    "value",
    ["", "-starts-with-punctuation", "contains space", "line\nbreak", "a" * 129],
)
def test_opaque_identifiers_reject_unsafe_values(value: str) -> None:
    """IDs cannot inject controls or create unbounded storage/log values."""
    with pytest.raises(InvalidIdentifierError, match="identifier must"):
        IncidentId(value)


def test_distinct_identifier_types_are_not_equal() -> None:
    """Runtime identity types prevent accidental cross-aggregate comparison."""
    incident_id: object = IncidentId("same")
    assert incident_id != AlertId("same")


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_aggregate_version_requires_a_positive_non_boolean_integer(value: object) -> None:
    """Optimistic versions cannot use invalid numeric representations."""
    with pytest.raises(InvalidDomainValueError, match="positive integer"):
        AggregateVersion(value)  # type: ignore[arg-type]


def test_aggregate_version_starts_at_one_and_increments_immutably() -> None:
    """Aggregate versions have one clear monotonic sequence."""
    initial = AggregateVersion.initial()

    assert initial == AggregateVersion(1)
    assert initial.next() == AggregateVersion(2)
    assert initial == AggregateVersion(1)


def test_event_reason_is_trimmed_and_printable() -> None:
    """Audit reasons are canonicalized without losing their text."""
    reason = EventReason("  evidence gate passed  ")

    assert reason.value == "evidence gate passed"
    assert str(reason) == "evidence gate passed"


@pytest.mark.parametrize(
    "value", ["", "   ", "line\nbreak", "has\rreturn", "null\x00byte", "a" * 513]
)
def test_event_reason_rejects_empty_unbounded_or_control_text(value: str) -> None:
    """Reasons remain bounded single-line audit data."""
    with pytest.raises(InvalidDomainValueError, match="event reason"):
        EventReason(value)


def test_as_utc_rejects_naive_time() -> None:
    """Naive timestamps cannot enter a domain record."""
    with pytest.raises(NaiveDateTimeError, match="timezone-aware"):
        as_utc(datetime(2026, 10, 2, 8, 0))


def test_as_utc_normalizes_aware_offset() -> None:
    """Timezone-aware inputs are converted to the internal UTC representation."""
    local = datetime(2026, 10, 2, 16, 0, tzinfo=timezone(timedelta(hours=8)))

    assert as_utc(local) == datetime(2026, 10, 2, 8, 0, tzinfo=UTC)


def test_utc_now_is_aware_utc() -> None:
    """The domain clock helper never returns a naive timestamp."""
    current = utc_now()

    assert current.tzinfo is UTC
    assert abs(datetime.now(UTC) - current) < timedelta(seconds=1)
