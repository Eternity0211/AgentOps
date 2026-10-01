"""Tests for immutable simulator deployment markers."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from agentops_incident_commander.simulator import app as simulator_app
from agentops_incident_commander.simulator.deployment import DeploymentMarker


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
