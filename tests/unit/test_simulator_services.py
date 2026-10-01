"""Contract tests for the four deterministic simulator HTTP services."""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agentops_incident_commander.simulator import app as simulator_app
from agentops_incident_commander.simulator import main as simulator_main

CHECKOUT = {
    "order_id": "order-123",
    "items": [{"sku": "widget-1", "quantity": 2}],
    "amount_minor": 2500,
    "currency": "USD",
}


@pytest.fixture
def anyio_backend() -> str:
    """Run async HTTP contract tests on the installed asyncio backend."""
    return "asyncio"


class FakeCaller:
    """Record internal calls and return deterministic service responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any], str]] = []

    async def post(
        self, service: str, path: str, payload: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]:
        self.calls.append((service, path, payload, correlation_id))
        if service == "inventory":
            return {"reservation_id": "res-order-123"}
        if service == "payment":
            return {"authorization_id": "auth-order-123"}
        return {
            "order_id": payload["order_id"],
            "status": "confirmed",
            "reservation_id": "res-order-123",
            "authorization_id": "auth-order-123",
            "correlation_id": correlation_id,
        }


class InvalidCaller:
    """Return an object that violates every downstream response contract."""

    async def post(
        self, service: str, path: str, payload: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]:
        return {}


class InProcessCaller:
    """Route internal HTTP calls into real ASGI service applications."""

    def __init__(self) -> None:
        self.apps: dict[str, Any] = {}

    async def post(
        self, service: str, path: str, payload: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]:
        transport = httpx.ASGITransport(app=self.apps[service])
        async with httpx.AsyncClient(transport=transport, base_url="http://service") as client:
            response = await client.post(
                path,
                json=payload,
                headers={simulator_app.CORRELATION_HEADER: correlation_id},
            )
        response.raise_for_status()
        body = response.json()
        assert isinstance(body, dict)
        return body


@pytest.mark.parametrize("service", ["gateway", "order", "inventory", "payment"])
def test_health_and_readiness_preserve_correlation(service: simulator_app.ServiceName) -> None:
    """Every service reports role and returns the same caller-supplied correlation ID."""
    client = TestClient(simulator_app.create_app(service, caller=FakeCaller()))
    headers = {simulator_app.CORRELATION_HEADER: "incident-42"}

    health = client.get("/healthz", headers=headers)
    ready = client.get("/readyz", headers=headers)

    assert health.json() == {
        "status": "ok",
        "service": service,
        "correlation_id": "incident-42",
    }
    assert ready.json()["status"] == "ready"
    assert health.headers[simulator_app.CORRELATION_HEADER] == "incident-42"


def test_missing_correlation_is_generated() -> None:
    """The ingress creates one correlation ID when the caller omitted it."""
    client = TestClient(
        simulator_app.create_app(
            "gateway", caller=FakeCaller(), correlation_factory=lambda: "generated-1"
        )
    )

    response = client.get("/healthz")

    assert response.headers[simulator_app.CORRELATION_HEADER] == "generated-1"
    assert response.json()["correlation_id"] == "generated-1"


def test_invalid_correlation_is_rejected_before_handler() -> None:
    """Control characters and whitespace cannot enter downstream headers or logs."""
    client = TestClient(simulator_app.create_app("gateway", caller=FakeCaller()))

    response = client.get("/healthz", headers={simulator_app.CORRELATION_HEADER: "not valid"})

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid correlation ID"}


def test_inventory_reservation_is_deterministic() -> None:
    """Inventory derives its reservation identifier from the client order ID."""
    client = TestClient(simulator_app.create_app("inventory", caller=FakeCaller()))

    response = client.post(
        "/v1/reservations",
        json=CHECKOUT,
        headers={simulator_app.CORRELATION_HEADER: "corr-1"},
    )

    assert response.json()["reservation_id"] == "res-order-123"
    assert response.json()["items"] == CHECKOUT["items"]
    assert response.json()["correlation_id"] == "corr-1"


def test_payment_authorization_is_deterministic() -> None:
    """Payment echoes bounded monetary data and derives a stable authorization ID."""
    client = TestClient(simulator_app.create_app("payment", caller=FakeCaller()))

    response = client.post("/v1/authorizations", json=CHECKOUT)

    assert response.json()["authorization_id"] == "auth-order-123"
    assert response.json()["amount_minor"] == 2500
    assert response.json()["currency"] == "USD"


def test_order_calls_inventory_then_payment_with_same_correlation() -> None:
    """Order propagates one correlation ID across its deterministic dependency chain."""
    caller = FakeCaller()
    client = TestClient(simulator_app.create_app("order", caller=caller))

    response = client.post(
        "/v1/orders",
        json=CHECKOUT,
        headers={simulator_app.CORRELATION_HEADER: "corr-order"},
    )

    assert response.json() == {
        "order_id": "order-123",
        "status": "confirmed",
        "reservation_id": "res-order-123",
        "authorization_id": "auth-order-123",
        "correlation_id": "corr-order",
    }
    assert [call[0] for call in caller.calls] == ["inventory", "payment"]
    assert {call[3] for call in caller.calls} == {"corr-order"}


def test_gateway_forwards_checkout_and_correlation() -> None:
    """Gateway exposes only checkout and forwards the validated request to Order."""
    caller = FakeCaller()
    client = TestClient(simulator_app.create_app("gateway", caller=caller))

    response = client.post(
        "/v1/checkout",
        json=CHECKOUT,
        headers={simulator_app.CORRELATION_HEADER: "corr-gateway"},
    )

    assert response.status_code == 200
    assert caller.calls == [("order", "/v1/orders", CHECKOUT, "corr-gateway")]


@pytest.mark.parametrize("service,path", [("gateway", "/v1/checkout"), ("order", "/v1/orders")])
def test_invalid_downstream_contract_becomes_bad_gateway(
    service: simulator_app.ServiceName, path: str
) -> None:
    """Missing downstream identifiers never become unhandled KeyErrors or false success."""
    client = TestClient(simulator_app.create_app(service, caller=InvalidCaller()))

    response = client.post(path, json=CHECKOUT)

    assert response.status_code == 502
    assert "returned invalid data" in response.json()["detail"]


def test_checkout_schema_rejects_invalid_business_input() -> None:
    """Invalid quantities and currencies never reach an internal caller."""
    caller = FakeCaller()
    client = TestClient(simulator_app.create_app("gateway", caller=caller))
    invalid = {**CHECKOUT, "currency": "usd", "items": [{"sku": "x", "quantity": 0}]}

    response = client.post("/v1/checkout", json=invalid)

    assert response.status_code == 422
    assert caller.calls == []


@pytest.mark.anyio
async def test_real_four_service_request_chain() -> None:
    """One real ASGI request crosses all four roles with one correlation ID."""
    caller = InProcessCaller()
    caller.apps.update(
        inventory=simulator_app.create_app("inventory", caller=caller),
        payment=simulator_app.create_app("payment", caller=caller),
    )
    caller.apps["order"] = simulator_app.create_app("order", caller=caller)
    gateway = simulator_app.create_app("gateway", caller=caller)
    transport = httpx.ASGITransport(app=gateway)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/v1/checkout",
            json=CHECKOUT,
            headers={simulator_app.CORRELATION_HEADER: "corr-e2e"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "order_id": "order-123",
        "status": "confirmed",
        "reservation_id": "res-order-123",
        "authorization_id": "auth-order-123",
        "correlation_id": "corr-e2e",
    }


@pytest.mark.anyio
async def test_httpx_caller_propagates_header_and_returns_object() -> None:
    """The production caller uses the configured URL and correlation header."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers[simulator_app.CORRELATION_HEADER] == "corr-http"
        assert str(request.url) == "http://order:8000/v1/orders"
        return httpx.Response(200, json={"status": "confirmed"})

    caller = simulator_app.HttpxServiceCaller(
        {"order": "http://order:8000"}, transport=httpx.MockTransport(handler)
    )

    assert await caller.post("order", "/v1/orders", CHECKOUT, "corr-http") == {
        "status": "confirmed"
    }


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["status", "json", "array"])
async def test_httpx_caller_maps_downstream_failures(mode: str) -> None:
    """HTTP, malformed JSON, and wrong-shape responses become bounded 502 errors."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if mode == "status":
            return httpx.Response(503, text="unavailable")
        if mode == "json":
            return httpx.Response(200, text="not-json")
        return httpx.Response(200, json=[])

    caller = simulator_app.HttpxServiceCaller(
        {"order": "http://order:8000"}, transport=httpx.MockTransport(handler)
    )

    with pytest.raises(HTTPException) as raised:
        await caller.post("order", "/v1/orders", CHECKOUT, "corr-http")
    assert raised.value.status_code == 502


@pytest.mark.anyio
async def test_httpx_caller_rejects_unknown_service() -> None:
    """No caller can turn an arbitrary service name into an outbound URL."""
    caller = simulator_app.HttpxServiceCaller({})

    with pytest.raises(HTTPException) as raised:
        await caller.post("unknown", "/", {}, "corr-http")
    assert raised.value.status_code == 500


def test_default_caller_reads_service_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production composition accepts explicit internal service locations."""
    monkeypatch.setenv("ORDER_SERVICE_URL", "http://custom-order:9000")

    app = simulator_app.create_app("gateway")

    assert app.title == "AgentOps Simulator Gateway"


def test_unknown_service_role_is_rejected() -> None:
    """Programmatic composition cannot create an unapproved service role."""
    with pytest.raises(ValueError, match="unknown simulator service"):
        simulator_app.create_app(cast(simulator_app.ServiceName, "unknown"))


def test_simulator_cli_runs_selected_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """The container CLI constructs the requested app and bounded listener."""
    captured: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int) -> None:
        captured.update(app=app, host=host, port=port)

    monkeypatch.setattr("agentops_incident_commander.simulator.main.uvicorn.run", fake_run)

    assert simulator_main.main(("inventory", "--host", "127.0.0.1", "--port", "9001")) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
