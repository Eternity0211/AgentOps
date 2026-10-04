"""Deterministic deployment summaries correlated to explicit incident windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from .errors import InvalidDomainValueError
from .values import ArtifactId, IncidentId, as_utc

DEPLOYMENT_SUMMARY_SCHEMA_VERSION: Final = "1.0.0"
MAX_DEPLOYMENT_CHANGES: Final = 1_000


def _text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 256 or "\x00" in normalized:
        raise InvalidDomainValueError(f"deployment {field} must be bounded non-null text")
    return normalized


@dataclass(frozen=True, slots=True, order=True)
class DeploymentRecordReference:
    artifact_id: ArtifactId
    record_index: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.record_index, int)
            or isinstance(self.record_index, bool)
            or not 0 <= self.record_index < MAX_DEPLOYMENT_CHANGES
        ):
            raise InvalidDomainValueError(
                "deployment Artifact record index is outside collector bounds"
            )


@dataclass(frozen=True, slots=True)
class DeploymentObservation:
    reference: DeploymentRecordReference
    service: str
    environment: str
    version: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        for field in ("service", "environment", "version"):
            object.__setattr__(self, field, _text(getattr(self, field), field=field))
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))


@dataclass(frozen=True, slots=True)
class IncidentDeploymentWindow:
    incident_id: IncidentId
    started_at: datetime
    ended_at: datetime

    def __post_init__(self) -> None:
        started_at = as_utc(self.started_at)
        ended_at = as_utc(self.ended_at)
        if ended_at < started_at:
            raise InvalidDomainValueError("deployment incident window is reversed")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "ended_at", ended_at)


@dataclass(frozen=True, slots=True)
class DeploymentWindowSummary:
    incident_id: IncidentId
    service: str
    environment: str
    window_started_at: datetime
    window_ended_at: datetime
    previous_deployment: DeploymentObservation | None
    window_changes: tuple[DeploymentObservation, ...]
    changed_during_window: bool
    observed_change_count: int
    superseded_before_count: int
    ignored_after_count: int
    source_artifact_ids: tuple[ArtifactId, ...]
    schema_version: str = DEPLOYMENT_SUMMARY_SCHEMA_VERSION


def summarize_deployments(
    changes: tuple[DeploymentObservation, ...],
    *,
    window: IncidentDeploymentWindow,
    service: str,
    environment: str,
) -> DeploymentWindowSummary:
    """Correlate one service/environment history with an inclusive incident window."""
    normalized_service = _text(service, field="service")
    normalized_environment = _text(environment, field="environment")
    if len(changes) > MAX_DEPLOYMENT_CHANGES:
        raise InvalidDomainValueError("deployment change count exceeds limit")

    positions: set[DeploymentRecordReference] = set()
    timestamps: set[datetime] = set()
    for change in changes:
        if change.service != normalized_service or change.environment != normalized_environment:
            raise InvalidDomainValueError("deployment summary cannot mix services or environments")
        if change.reference in positions:
            raise InvalidDomainValueError("deployment Artifact record positions must be unique")
        if change.occurred_at in timestamps:
            raise InvalidDomainValueError("deployment change timestamps must be unique")
        positions.add(change.reference)
        timestamps.add(change.occurred_at)

    ordered = tuple(sorted(changes, key=lambda item: (item.occurred_at, item.reference)))
    before = tuple(item for item in ordered if item.occurred_at < window.started_at)
    during = tuple(
        item for item in ordered if window.started_at <= item.occurred_at <= window.ended_at
    )
    after = tuple(item for item in ordered if item.occurred_at > window.ended_at)
    previous = before[-1] if before else None
    return DeploymentWindowSummary(
        incident_id=window.incident_id,
        service=normalized_service,
        environment=normalized_environment,
        window_started_at=window.started_at,
        window_ended_at=window.ended_at,
        previous_deployment=previous,
        window_changes=during,
        changed_during_window=bool(during),
        observed_change_count=len(ordered),
        superseded_before_count=max(0, len(before) - 1),
        ignored_after_count=len(after),
        source_artifact_ids=tuple(
            sorted({item.reference.artifact_id for item in ordered}, key=lambda item: item.value)
        ),
    )
