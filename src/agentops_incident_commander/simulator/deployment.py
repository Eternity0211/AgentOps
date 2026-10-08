"""Validated deployment markers shared by runtime reporting and telemetry."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock

from agentops_incident_commander.simulator.app_types import ServiceName

VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
DEPLOYMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _validated(value: str, pattern: re.Pattern[str], field: str) -> str:
    if pattern.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")
    return value


@dataclass(frozen=True, slots=True)
class DeploymentMarker:
    """Immutable facts that identify one simulator deployment."""

    service: ServiceName
    deployment_id: str
    version: str
    previous_version: str | None
    schema_version: str = "1.0"

    @classmethod
    def from_environment(
        cls,
        service: ServiceName,
        environment: Mapping[str, str] | None = None,
    ) -> DeploymentMarker:
        source = os.environ if environment is None else environment
        version = _validated(source.get("SERVICE_VERSION", "1.0.0"), VERSION_PATTERN, "version")
        deployment_id = _validated(
            source.get("DEPLOYMENT_ID", f"baseline-{service}-v1"),
            DEPLOYMENT_ID_PATTERN,
            "deployment ID",
        )
        previous = source.get("PREVIOUS_SERVICE_VERSION")
        previous_version = (
            _validated(previous, VERSION_PATTERN, "previous version") if previous else None
        )
        return cls(
            service=service,
            deployment_id=deployment_id,
            version=version,
            previous_version=previous_version,
        )

    def attributes(self) -> dict[str, str]:
        """Return a bounded OTLP attribute set without optional null values."""
        attributes = {
            "event.name": "service.deployment.changed",
            "event.schema.version": self.schema_version,
            "service.name": f"agentops-simulator-{self.service}",
            "service.version": self.version,
            "deployment.id": self.deployment_id,
        }
        if self.previous_version is not None:
            attributes["service.previous_version"] = self.previous_version
        return attributes


class SimulatorDeploymentState:
    """Thread-safe mutable deployment state reserved for local recovery E2E tests."""

    def __init__(self, marker: DeploymentMarker) -> None:
        if not isinstance(marker, DeploymentMarker):
            raise ValueError("invalid simulator deployment marker")
        self._marker = marker
        self._transition_count = 0
        self._lock = RLock()

    def current(self) -> DeploymentMarker:
        with self._lock:
            return self._marker

    @property
    def transition_count(self) -> int:
        with self._lock:
            return self._transition_count

    def transition(
        self,
        *,
        service: str,
        expected_version: str,
        stable_version: str,
        deployment_id: str,
    ) -> DeploymentMarker:
        expected = _validated(expected_version, VERSION_PATTERN, "expected version")
        stable = _validated(stable_version, VERSION_PATTERN, "stable version")
        operation = _validated(deployment_id, DEPLOYMENT_ID_PATTERN, "deployment ID")
        with self._lock:
            current = self._marker
            if current.service != service:
                raise ValueError("simulator rollback service does not match deployment state")
            if current.version != expected:
                raise ValueError("simulator rollback current version changed")
            self._marker = DeploymentMarker(
                service=current.service,
                deployment_id=operation,
                version=stable,
                previous_version=current.version,
            )
            self._transition_count += 1
            return self._marker
