"""Tests for immutable simulator deployment markers."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from agentops_incident_commander.simulator import app as simulator_app
from agentops_incident_commander.simulator.deployment import (
    DeploymentMarker,
    SimulatorDeploymentState,
)


def test_default_marker_is_stable_and_has_no_synthetic_predecessor() -> None:
    """Direct runs get an explicit baseline identity without invented history."""
    marker = DeploymentMarker.from_environment("gateway", {})

    assert marker == DeploymentMarker(
        service="gateway",
        deployment_id="baseline-gateway-v1",
        version="1.0.0",
        previous_version=None,
    )
    assert marker.attributes() == {
        "event.name": "service.deployment.changed",
        "event.schema.version": "1.0",
        "service.name": "agentops-simulator-gateway",
        "service.version": "1.0.0",
        "deployment.id": "baseline-gateway-v1",
    }


def test_marker_records_a_valid_previous_version() -> None:
    """A controlled rollout can identify both sides of a version transition."""
    marker = DeploymentMarker.from_environment(
        "order",
        {
            "SERVICE_VERSION": "1.1.0-rc.1",
            "DEPLOYMENT_ID": "fault-http-500:order:002",
            "PREVIOUS_SERVICE_VERSION": "1.0.0",
        },
    )

    assert marker.attributes()["service.previous_version"] == "1.0.0"
    assert marker.version == "1.1.0-rc.1"


@pytest.mark.parametrize(
    "environment",
    [
        {"SERVICE_VERSION": ""},
        {"SERVICE_VERSION": "bad version"},
        {"SERVICE_VERSION": "x" * 65},
        {"DEPLOYMENT_ID": "bad\nforged=true"},
        {"DEPLOYMENT_ID": "x" * 129},
        {"PREVIOUS_SERVICE_VERSION": "bad/version"},
    ],
)
def test_marker_rejects_ambiguous_or_injectable_values(
    environment: dict[str, str],
) -> None:
    """Free text and oversized identifiers cannot enter diagnostic records."""
    with pytest.raises(ValueError, match="invalid"):
        DeploymentMarker.from_environment("payment", environment)


def test_version_endpoint_and_startup_event_share_one_marker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Runtime verification and deployment logs expose identical immutable facts."""
    marker = DeploymentMarker(
        service="payment",
        deployment_id="payment-release-42",
        version="2.0.0",
        previous_version="1.9.0",
    )
    caplog.set_level(logging.INFO, logger="agentops.simulator.telemetry")
    app = simulator_app.create_app("payment", deployment_marker=marker)

    with TestClient(app) as client:
        first = client.get(
            "/versionz",
            headers={simulator_app.CORRELATION_HEADER: "corr-version"},
        )
        second = client.get("/versionz")

    assert first.json() == {
        "service": "payment",
        "deployment_id": "payment-release-42",
        "version": "2.0.0",
        "previous_version": "1.9.0",
        "schema_version": "1.0",
        "correlation_id": "corr-version",
    }
    assert second.status_code == 200
    deployment_events = []
    for record in caplog.records:
        try:
            value = json.loads(record.message)
        except json.JSONDecodeError:
            continue
        if value.get("event.name") == "service.deployment.changed":
            deployment_events.append(value)
    assert deployment_events == [marker.attributes()]


def test_mutable_deployment_state_is_visible_to_version_endpoint() -> None:
    marker = DeploymentMarker("payment", "fault-release-2", "2.0.0", "1.0.0")
    state = SimulatorDeploymentState(marker)
    app = simulator_app.create_app("payment", deployment_state=state)

    state.transition(
        service="payment",
        expected_version="2.0.0",
        stable_version="1.0.0",
        deployment_id="sim-rollback-operation",
    )
    with TestClient(app) as client:
        response = client.get("/versionz")

    assert response.json()["version"] == "1.0.0"
    assert response.json()["previous_version"] == "2.0.0"
    assert state.transition_count == 1


def test_create_app_rejects_two_deployment_sources() -> None:
    marker = DeploymentMarker("payment", "release-2", "2.0.0", "1.0.0")
    with pytest.raises(ValueError, match="mutually exclusive"):
        simulator_app.create_app(
            "payment",
            deployment_marker=marker,
            deployment_state=SimulatorDeploymentState(marker),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"service": "payment"},
        {"expected_version": "3.0.0"},
        {"expected_version": "bad version"},
        {"stable_version": "bad version"},
        {"deployment_id": "bad deployment"},
    ],
)
def test_deployment_state_rejects_invalid_transition(change: dict[str, str]) -> None:
    state = SimulatorDeploymentState(DeploymentMarker("order", "release-2", "2.0.0", "1.0.0"))
    values = {
        "service": "order",
        "expected_version": "2.0.0",
        "stable_version": "1.0.0",
        "deployment_id": "operation-1",
        **change,
    }
    with pytest.raises(ValueError, match=r"invalid|does not match|changed"):
        state.transition(**values)
    assert state.transition_count == 0


def test_deployment_state_rejects_untyped_marker() -> None:
    with pytest.raises(ValueError, match="invalid simulator deployment marker"):
        SimulatorDeploymentState("invalid")  # type: ignore[arg-type]
