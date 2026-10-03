"""Deterministic Alert fingerprinting, grouping, merging, and triage."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from threading import RLock
from types import MappingProxyType
from typing import Final

from .errors import InvalidDomainValueError, OptimisticVersionError
from .incidents import IncidentSeverity
from .values import AggregateVersion, AlertGroupId, AlertId, TenantId, as_utc

FINGERPRINT_SCHEMA_VERSION: Final[str] = "alert-fingerprint/v1"
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AlertTriageAction(StrEnum):
    """Whether an Alert opened a group or joined an existing group."""

    OPEN_GROUP = "OPEN_GROUP"
    MERGE_GROUP = "MERGE_GROUP"
    DUPLICATE = "DUPLICATE"


_SEVERITY_RANK: Final[Mapping[IncidentSeverity, int]] = MappingProxyType(
    {
        IncidentSeverity.SEV1: 1,
        IncidentSeverity.SEV2: 2,
        IncidentSeverity.SEV3: 3,
        IncidentSeverity.SEV4: 4,
    }
)


def _canonical_text(value: str, *, field: str, maximum: int = 256) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum:
        raise InvalidDomainValueError(f"{field} must contain 1-{maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise InvalidDomainValueError(f"{field} cannot contain control characters")
    return normalized


def _canonical_name(value: str, *, field: str) -> str:
    normalized = _canonical_text(value, field=field, maximum=128)
    if _NAME_PATTERN.fullmatch(normalized) is None:
        raise InvalidDomainValueError(f"{field} contains unsupported characters")
    return normalized


@dataclass(frozen=True, slots=True, order=True)
class AlertDimension:
    """One explicit grouping dimension included in an Alert fingerprint."""

    name: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _canonical_name(self.name, field="dimension name"))
        object.__setattr__(
            self, "value", _canonical_text(self.value, field="dimension value", maximum=256)
        )


@dataclass(frozen=True, slots=True)
class AlertFingerprint:
    """Versioned SHA-256 digest of the canonical grouping identity."""

    value: str
    schema_version: str = FINGERPRINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != FINGERPRINT_SCHEMA_VERSION:
            raise InvalidDomainValueError("unsupported Alert fingerprint schema version")
        if _FINGERPRINT_PATTERN.fullmatch(self.value) is None:
            raise InvalidDomainValueError("Alert fingerprint must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class Alert:
    """Normalized incoming Alert safe for deterministic grouping."""

    id: AlertId
    tenant_id: TenantId
    environment: str
    service: str
    rule: str
    severity: IncidentSeverity
    observed_at: datetime
    received_at: datetime
    dimensions: tuple[AlertDimension, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "environment", _canonical_name(self.environment, field="environment")
        )
        object.__setattr__(self, "service", _canonical_name(self.service, field="service"))
        object.__setattr__(self, "rule", _canonical_name(self.rule, field="rule"))
        observed_at = as_utc(self.observed_at)
        received_at = as_utc(self.received_at)
        if received_at < observed_at:
            raise InvalidDomainValueError("received_at cannot predate observed_at")
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "received_at", received_at)
        canonical_dimensions = tuple(sorted(self.dimensions))
        names = tuple(dimension.name for dimension in canonical_dimensions)
        if len(names) != len(set(names)):
            raise InvalidDomainValueError("Alert dimension names must be unique")
        object.__setattr__(self, "dimensions", canonical_dimensions)

    def fingerprint(self) -> AlertFingerprint:
        """Hash only the explicit stable grouping identity in canonical order."""
        canonical = {
            "dimensions": [
                {"name": dimension.name, "value": dimension.value} for dimension in self.dimensions
            ],
            "environment": self.environment,
            "rule": self.rule,
            "schema_version": FINGERPRINT_SCHEMA_VERSION,
            "service": self.service,
            "tenant_id": self.tenant_id.value,
        }
        encoded = json.dumps(
            canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return AlertFingerprint(hashlib.sha256(encoded).hexdigest())


@dataclass(frozen=True, slots=True)
class AlertGroup:
    """Immutable time-bounded aggregate of alerts with one fingerprint."""

    id: AlertGroupId
    fingerprint: AlertFingerprint
    tenant_id: TenantId
    environment: str
    service: str
    rule: str
    severity: IncidentSeverity
    first_observed_at: datetime
    last_observed_at: datetime
    first_received_at: datetime
    last_received_at: datetime
    alert_ids: tuple[AlertId, ...]
    occurrence_count: int
    version: AggregateVersion

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "environment", _canonical_name(self.environment, field="environment")
        )
        object.__setattr__(self, "service", _canonical_name(self.service, field="service"))
        object.__setattr__(self, "rule", _canonical_name(self.rule, field="rule"))
        for field_name in (
            "first_observed_at",
            "last_observed_at",
            "first_received_at",
            "last_received_at",
        ):
            object.__setattr__(self, field_name, as_utc(getattr(self, field_name)))
        if self.first_observed_at > self.last_observed_at:
            raise InvalidDomainValueError("Alert group observation range is reversed")
        if self.first_received_at > self.last_received_at:
            raise InvalidDomainValueError("Alert group receipt range is reversed")
        if not self.alert_ids or len(self.alert_ids) != len(set(self.alert_ids)):
            raise InvalidDomainValueError("Alert group IDs must be non-empty and unique")
        if self.occurrence_count != len(self.alert_ids):
            raise InvalidDomainValueError("occurrence_count must equal the unique Alert count")

    @classmethod
    def open(cls, group_id: AlertGroupId, alert: Alert) -> AlertGroup:
        """Create one group from its first normalized Alert."""
        return cls(
            id=group_id,
            fingerprint=alert.fingerprint(),
            tenant_id=alert.tenant_id,
            environment=alert.environment,
            service=alert.service,
            rule=alert.rule,
            severity=alert.severity,
            first_observed_at=alert.observed_at,
            last_observed_at=alert.observed_at,
            first_received_at=alert.received_at,
            last_received_at=alert.received_at,
            alert_ids=(alert.id,),
            occurrence_count=1,
            version=AggregateVersion.initial(),
        )

    def is_within(self, alert: Alert, window: timedelta) -> bool:
        """Return whether an equal-fingerprint Alert touches the bounded group window."""
        if alert.fingerprint() != self.fingerprint:
            return False
        return (
            self.first_observed_at - window <= alert.observed_at <= self.last_observed_at + window
        )

    def merge(
        self, alert: Alert, *, expected_version: AggregateVersion
    ) -> tuple[AlertGroup, AlertTriageAction]:
        """Merge a unique Alert, escalate severity, or identify an exact replay."""
        if expected_version != self.version:
            raise OptimisticVersionError(
                f"expected version {expected_version.value}, current version {self.version.value}"
            )
        if alert.fingerprint() != self.fingerprint:
            raise InvalidDomainValueError("cannot merge Alert with a different fingerprint")
        if alert.id in self.alert_ids:
            return self, AlertTriageAction.DUPLICATE

        severity = (
            alert.severity
            if _SEVERITY_RANK[alert.severity] < _SEVERITY_RANK[self.severity]
            else self.severity
        )
        return (
            replace(
                self,
                severity=severity,
                first_observed_at=min(self.first_observed_at, alert.observed_at),
                last_observed_at=max(self.last_observed_at, alert.observed_at),
                first_received_at=min(self.first_received_at, alert.received_at),
                last_received_at=max(self.last_received_at, alert.received_at),
                alert_ids=(*self.alert_ids, alert.id),
                occurrence_count=self.occurrence_count + 1,
                version=self.version.next(),
            ),
            AlertTriageAction.MERGE_GROUP,
        )


@dataclass(frozen=True, slots=True)
class AlertTriageDecision:
    """Observable result of deterministic Alert ingestion."""

    action: AlertTriageAction
    group: AlertGroup
    fingerprint: AlertFingerprint


def select_alert_group(
    groups: Iterable[AlertGroup], alert: Alert, window: timedelta
) -> AlertGroup | None:
    """Select the deterministic matching group shared by all persistence adapters."""
    candidates = [group for group in groups if group.is_within(alert, window)]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda group: (
            abs((group.last_observed_at - alert.observed_at).total_seconds()),
            group.first_observed_at,
            group.id.value,
        ),
    )


class AlertDeduplicator:
    """Thread-safe reference coordinator for one process.

    PostgreSQL persistence will replace the critical section with a unique key and row lock while
    retaining this exact grouping policy.
    """

    def __init__(
        self,
        *,
        window: timedelta,
        group_id_factory: Callable[[], AlertGroupId],
    ) -> None:
        if window <= timedelta(0):
            raise InvalidDomainValueError("deduplication window must be positive")
        self._window = window
        self._group_id_factory = group_id_factory
        self._groups: dict[AlertFingerprint, list[AlertGroup]] = {}
        self._lock = RLock()

    def ingest(self, alert: Alert) -> AlertTriageDecision:
        """Atomically open, merge, or replay an Alert group."""
        fingerprint = alert.fingerprint()
        with self._lock:
            groups = self._groups.setdefault(fingerprint, [])
            existing = select_alert_group(groups, alert, self._window)
            if existing is None:
                group = AlertGroup.open(self._group_id_factory(), alert)
                groups.append(group)
                return AlertTriageDecision(AlertTriageAction.OPEN_GROUP, group, fingerprint)

            index = groups.index(existing)
            group, action = existing.merge(alert, expected_version=existing.version)
            groups[index] = group
            return AlertTriageDecision(action, group, fingerprint)

    def groups(self) -> tuple[AlertGroup, ...]:
        """Return a stable immutable snapshot of all groups."""
        with self._lock:
            return tuple(
                sorted(
                    (group for groups in self._groups.values() for group in groups),
                    key=lambda group: group.id.value,
                )
            )
