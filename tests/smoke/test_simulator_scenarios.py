"""Fast in-process smoke coverage for the simulator baseline and six faults."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from agentops_incident_commander.simulator.app import ServiceCaller, ServiceName, create_app
from agentops_incident_commander.simulator.dependencies import (
    DependencyUnavailable,
    ReservationOutcome,
)
from agentops_incident_commander.simulator.fault_behavior import FaultBehavior, FaultScenario
from agentops_incident_commander.simulator.memory_fault import BoundedMemoryRetention
from agentops_incident_commander.simulator.models import CheckoutRequest

CHECKOUT = {
    "order_id": "smoke-order-1",
    "items": [{"sku": "smoke-widget", "quantity": 1}],
    "amount_minor": 500,
    "currency": "USD",
}
SCENARIO_TARGETS: dict[FaultScenario, ServiceName] = {
    "http-500": "order",
    "db-pool-exhaustion": "order",
    "redis-timeout": "inventory",
    "downstream-latency": "payment",
    "memory-leak": "order",
    "bad-configuration": "payment",
}


class SmokeCaller:
    """Return contract-valid downstream responses without network access."""

    async def post(
        self, service: str, path: str, payload: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]:
        if service == "inventory":
            return {"reservation_id": f"res-{payload['order_id']}"}
        if service == "payment":
            return {"authorization_id": f"auth-{payload['order_id']}"}
        return {
            "order_id": payload["order_id"],
            "status": "confirmed",
            "reservation_id": f"res-{payload['order_id']}",
            "authorization_id": f"auth-{payload['order_id']}",
            "correlation_id": correlation_id,
            "created": True,
        }


class SmokeOrderStore:
    """Minimal deterministic Order store with one controlled failure mode."""

    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    async def ready(self, correlation_id: str) -> None:
        if self.unavailable:
            raise DependencyUnavailable("synthetic PostgreSQL saturation")

    async def save(self, checkout: CheckoutRequest, correlation_id: str) -> bool:
        if self.unavailable:
            raise DependencyUnavailable("synthetic PostgreSQL saturation")
        return True

    async def close(self) -> None:
        return None


class SmokeInventoryStore:
    """Minimal deterministic Inventory store with one controlled timeout mode."""

    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    async def ready(self, correlation_id: str) -> None:
        if self.unavailable:
            raise DependencyUnavailable("synthetic Redis timeout")

    async def reserve(self, checkout: CheckoutRequest, correlation_id: str) -> ReservationOutcome:
        if self.unavailable:
            raise DependencyUnavailable("synthetic Redis timeout")
        return ReservationOutcome(f"res-{checkout.order_id}", True)

    async def close(self) -> None:
        return None


def make_client(
    service: ServiceName,
    *,
    behavior: FaultBehavior | None = None,
    unavailable: bool = False,
    sleeper: Any = None,
    retention: BoundedMemoryRetention | None = None,
) -> TestClient:
    """Compose one service with deterministic in-memory boundaries."""
    return TestClient(
        create_app(
            service,
            caller=cast(ServiceCaller, SmokeCaller()),
            order_store=SmokeOrderStore(unavailable=unavailable) if service == "order" else None,
            inventory_store=(
                SmokeInventoryStore(unavailable=unavailable) if service == "inventory" else None
            ),
            fault_behavior=behavior,
            sleeper=sleeper,
            memory_retention=retention,
        )
    )


def business_response(client: TestClient, service: ServiceName) -> Any:
    """Call the single business endpoint owned by a service role."""
    paths = {
        "gateway": "/v1/checkout",
        "order": "/v1/orders",
        "inventory": "/v1/reservations",
        "payment": "/v1/authorizations",
    }
    return client.post(paths[service], json=CHECKOUT, headers={"X-Correlation-ID": "smoke-1"})


@pytest.mark.parametrize("service", ["gateway", "order", "inventory", "payment"])
def test_baseline_services_are_live_ready_and_serve_business_requests(service: ServiceName) -> None:
    client = make_client(service)

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/versionz").json()["version"] == "1.0.0"
    assert business_response(client, service).status_code == 200


@pytest.mark.parametrize("scenario", list(SCENARIO_TARGETS))
def test_fault_symptom_then_fresh_baseline_cleanup(scenario: FaultScenario) -> None:
    target = SCENARIO_TARGETS[scenario]
    behavior = FaultBehavior(scenario=scenario, run_id=f"run-smoke-{scenario.replace('-', '')}")
    delays: list[float] = []

    async def record_delay(seconds: float) -> None:
        delays.append(seconds)

    retention = BoundedMemoryRetention(chunk_bytes=8, limit_bytes=16)
    unavailable = scenario in {"db-pool-exhaustion", "redis-timeout"}
    faulted = make_client(
        target,
        behavior=behavior,
        unavailable=unavailable,
        sleeper=record_delay,
        retention=retention,
    )

    assert faulted.get("/healthz").status_code == 200
    readiness = faulted.get("/readyz")
    response = business_response(faulted, target)
    expected_status = {
        "http-500": 500,
        "db-pool-exhaustion": 503,
        "redis-timeout": 503,
        "downstream-latency": 200,
        "memory-leak": 200,
        "bad-configuration": 503,
    }[scenario]
    assert response.status_code == expected_status
    assert readiness.status_code == (503 if unavailable or scenario == "bad-configuration" else 200)
    if scenario == "downstream-latency":
        assert delays == [3.0]
    if scenario == "memory-leak":
        assert retention.snapshot().retained_bytes == 8

    restored = make_client(target)
    assert restored.get("/healthz").status_code == 200
    assert restored.get("/readyz").status_code == 200
    assert business_response(restored, target).status_code == 200
