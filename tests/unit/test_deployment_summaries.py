"""Deployment-to-incident-window correlation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from agentops_incident_commander.domain import (
    DEPLOYMENT_SUMMARY_SCHEMA_VERSION,
    MAX_DEPLOYMENT_CHANGES,
    ArtifactId,
    DeploymentObservation,
    DeploymentRecordReference,
    IncidentDeploymentWindow,
    IncidentId,
    InvalidDomainValueError,
    summarize_deployments,
)

NOW = datetime(2026, 10, 4, 8, tzinfo=UTC)


def change(
    index: int,
    minutes: int,
    version: str,
    *,
    service: str = "order",
    environment: str = "production",
    artifact_id: str = "artifact-deployments",
) -> DeploymentObservation:
    return DeploymentObservation(
        DeploymentRecordReference(ArtifactId(artifact_id), index),
        service,
        environment,
        version,
        NOW + timedelta(minutes=minutes),
    )


def window(start: int = 0, end: int = 10) -> IncidentDeploymentWindow:
    return IncidentDeploymentWindow(
        IncidentId("incident-1"),
        NOW + timedelta(minutes=start),
        NOW + timedelta(minutes=end),
    )


def test_summary_correlates_previous_and_inclusive_window_changes() -> None:
    changes = (
        change(4, 11, "4.0.0"),
        change(2, 0, "2.0.0", artifact_id="artifact-window"),
        change(0, -10, "0.9.0"),
        change(3, 10, "3.0.0", artifact_id="artifact-window"),
        change(1, -1, "1.0.0"),
    )
    result = summarize_deployments(
        changes,
        window=window(),
        service=" order ",
        environment=" production ",
    )

    assert result.incident_id == IncidentId("incident-1")
    assert result.service == "order"
    assert result.environment == "production"
    assert result.window_started_at == NOW
    assert result.window_ended_at == NOW + timedelta(minutes=10)
    assert result.previous_deployment == changes[4]
    assert tuple(item.version for item in result.window_changes) == ("2.0.0", "3.0.0")
    assert result.changed_during_window
    assert result.observed_change_count == 5
    assert result.superseded_before_count == 1
    assert result.ignored_after_count == 1
    assert result.source_artifact_ids == (
        ArtifactId("artifact-deployments"),
        ArtifactId("artifact-window"),
    )
    assert result.schema_version == DEPLOYMENT_SUMMARY_SCHEMA_VERSION


def test_summary_supports_empty_history_without_inventing_a_deployment() -> None:
    result = summarize_deployments((), window=window(), service="order", environment="production")
    assert result.previous_deployment is None
    assert result.window_changes == ()
    assert not result.changed_during_window
    assert result.observed_change_count == 0
    assert result.superseded_before_count == 0
    assert result.ignored_after_count == 0
    assert result.source_artifact_ids == ()


def test_single_previous_deployment_is_not_counted_as_superseded() -> None:
    result = summarize_deployments(
        (change(0, -1, "1.0.0"),),
        window=window(),
        service="order",
        environment="production",
    )
    assert result.previous_deployment is not None
    assert result.superseded_before_count == 0


def test_window_and_observation_normalize_utc() -> None:
    east = timezone(timedelta(hours=8))
    deployment = DeploymentObservation(
        DeploymentRecordReference(ArtifactId("artifact"), 0),
        " order ",
        " production ",
        " 1.0.0 ",
        NOW.astimezone(east),
    )
    incident_window = IncidentDeploymentWindow(
        IncidentId("incident"), NOW.astimezone(east), NOW.astimezone(east)
    )
    assert deployment.service == "order"
    assert deployment.environment == "production"
    assert deployment.version == "1.0.0"
    assert deployment.occurred_at == NOW
    assert incident_window.started_at == incident_window.ended_at == NOW


@pytest.mark.parametrize("record_index", [-1, MAX_DEPLOYMENT_CHANGES, True, 1.5])
def test_reference_rejects_invalid_record_index(record_index: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="outside"):
        DeploymentRecordReference(ArtifactId("artifact"), record_index)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service", ""),
        ("service", "x" * 257),
        ("service", "bad\x00service"),
        ("environment", ""),
        ("environment", "x" * 257),
        ("environment", "bad\x00environment"),
        ("version", ""),
        ("version", "x" * 257),
        ("version", "bad\x00version"),
    ],
)
def test_observation_text_is_bounded(field: str, value: str) -> None:
    values = {"service": "order", "environment": "production", "version": "1.0.0"}
    values[field] = value
    with pytest.raises(InvalidDomainValueError, match=field):
        DeploymentObservation(
            DeploymentRecordReference(ArtifactId("artifact"), 0),
            values["service"],
            values["environment"],
            values["version"],
            NOW,
        )


@pytest.mark.parametrize(("field", "value"), [("service", ""), ("environment", "")])
def test_summary_target_text_is_bounded(field: str, value: str) -> None:
    values = {"service": "order", "environment": "production"}
    values[field] = value
    with pytest.raises(InvalidDomainValueError, match=field):
        summarize_deployments((), window=window(), **values)


def test_incident_window_rejects_reversed_times() -> None:
    with pytest.raises(InvalidDomainValueError, match="reversed"):
        IncidentDeploymentWindow(IncidentId("incident"), NOW, NOW - timedelta(seconds=1))


def test_summary_rejects_excess_changes() -> None:
    changes = tuple(
        change(
            index % MAX_DEPLOYMENT_CHANGES,
            index,
            str(index),
            artifact_id=f"artifact-{index // MAX_DEPLOYMENT_CHANGES}",
        )
        for index in range(MAX_DEPLOYMENT_CHANGES + 1)
    )
    with pytest.raises(InvalidDomainValueError, match="count"):
        summarize_deployments(changes, window=window(), service="order", environment="production")


@pytest.mark.parametrize(
    "deployment",
    [
        change(0, 0, "1.0.0", service="payment"),
        change(0, 0, "1.0.0", environment="staging"),
    ],
)
def test_summary_rejects_mixed_service_or_environment(
    deployment: DeploymentObservation,
) -> None:
    with pytest.raises(InvalidDomainValueError, match="mix"):
        summarize_deployments(
            (deployment,), window=window(), service="order", environment="production"
        )


def test_summary_rejects_duplicate_raw_positions_or_timestamps() -> None:
    with pytest.raises(InvalidDomainValueError, match="record positions"):
        summarize_deployments(
            (change(0, 0, "1.0.0"), change(0, 1, "2.0.0")),
            window=window(),
            service="order",
            environment="production",
        )
    with pytest.raises(InvalidDomainValueError, match="timestamps"):
        summarize_deployments(
            (change(0, 0, "1.0.0"), change(1, 0, "2.0.0")),
            window=window(),
            service="order",
            environment="production",
        )
