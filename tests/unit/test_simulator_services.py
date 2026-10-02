"""Contract tests for the four deterministic simulator HTTP services."""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agentops_incident_commander.simulator import app as simulator_app
from agentops_incident_commander.simulator import main as simulator_main
from agentops_incident_commander.simulator.dependencies import (
    DependencyUnavailable,
    InventoryInsufficient,
    ReservationOutcome,
)
from agentops_incident_commander.simulator.fault_behavior import FaultBehavior
from agentops_incident_commander.simulator.memory_fault import BoundedMemoryRetention
from agentops_incident_commander.simulator.models import CheckoutRequest

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
            "created": True,
        }


class FakeOrderStore:
    """In-memory Order persistence boundary for HTTP contract tests."""

    def __init__(self) -> None:
        self.saved: set[str] = set()
        self.closed = False
        self.failure: Exception | None = None

    async def ready(self, correlation_id: str) -> None:
        if self.failure is not None:
            raise self.failure

    async def save(self, checkout: CheckoutRequest, correlation_id: str) -> bool:
        if self.failure is not None:
            raise self.failure
        created = checkout.order_id not in self.saved
        self.saved.add(checkout.order_id)
        return created

    async def close(self) -> None:
        self.closed = True


class FakeInventoryStore:
    """In-memory Inventory persistence boundary for HTTP contract tests."""

    def __init__(self) -> None:
        self.reserved: set[str] = set()
        self.closed = False
        self.failure: Exception | None = None

    async def ready(self, correlation_id: str) -> None:
        if self.failure is not None:
            raise self.failure

    async def reserve(self, checkout: CheckoutRequest, correlation_id: str) -> ReservationOutcome:
        if self.failure is not None:
            raise self.failure
        created = checkout.order_id not in self.reserved
        self.reserved.add(checkout.order_id)
        return ReservationOutcome(f"res-{checkout.order_id}", created)

    async def close(self) -> None:
        self.closed = True


def create_test_app(
    service: simulator_app.ServiceName,
    caller: simulator_app.ServiceCaller | None = None,
) -> Any:
    """Compose a service without opening production dependency connections."""
    return simulator_app.create_app(
        service,
        caller=caller or FakeCaller(),
        order_store=FakeOrderStore() if service == "order" else None,
        inventory_store=FakeInventoryStore() if service == "inventory" else None,
    )


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
    client = TestClient(create_test_app(service))
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
    client = TestClient(create_test_app("inventory"))

    response = client.post(
        "/v1/reservations",
        json=CHECKOUT,
        headers={simulator_app.CORRELATION_HEADER: "corr-1"},
    )

    assert response.json()["reservation_id"] == "res-order-123"
    assert response.json()["items"] == CHECKOUT["items"]
    assert response.json()["correlation_id"] == "corr-1"


def test_inventory_duplicate_reservation_is_idempotent() -> None:
    """A repeated client order ID reports the existing reservation without duplication."""
    store = FakeInventoryStore()
    client = TestClient(
        simulator_app.create_app("inventory", caller=FakeCaller(), inventory_store=store)
    )

    first = client.post("/v1/reservations", json=CHECKOUT)
    second = client.post("/v1/reservations", json=CHECKOUT)

    assert first.json()["status"] == "reserved"
    assert second.json()["status"] == "already_reserved"
    assert store.reserved == {"order-123"}


@pytest.mark.parametrize(
    ("failure", "status_code", "detail"),
    [
        (InventoryInsufficient("low stock"), 409, "insufficient inventory"),
        (DependencyUnavailable("offline"), 503, "inventory dependency unavailable"),
    ],
)
def test_inventory_maps_store_failures(failure: Exception, status_code: int, detail: str) -> None:
    """Expected Redis failure classes become stable, non-sensitive HTTP responses."""
    store = FakeInventoryStore()
    store.failure = failure
    client = TestClient(
        simulator_app.create_app("inventory", caller=FakeCaller(), inventory_store=store)
    )

    response = client.post("/v1/reservations", json=CHECKOUT)

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}


def test_payment_authorization_is_deterministic() -> None:
    """Payment echoes bounded monetary data and derives a stable authorization ID."""
    client = TestClient(simulator_app.create_app("payment", caller=FakeCaller()))

    response = client.post("/v1/authorizations", json=CHECKOUT)

    assert response.json()["authorization_id"] == "auth-order-123"
    assert response.json()["amount_minor"] == 2500
    assert response.json()["currency"] == "USD"


def test_downstream_latency_fault_delays_only_payment_business_path() -> None:
    """Payment uses the fixed delay while health, readiness, and version remain baseline."""
    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    client = TestClient(
        simulator_app.create_app(
            "payment",
            fault_behavior=FaultBehavior("downstream-latency", "run-abcdef123456"),
            sleeper=sleep,
        )
    )

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    response = client.post("/v1/authorizations", json=CHECKOUT)
    version = client.get("/versionz").json()

    assert response.status_code == 200
    assert delays == [simulator_app.DOWNSTREAM_LATENCY_SECONDS]
    assert version["version"] == "1.0.0"
    assert "downstream-latency" not in str(version)


def test_bad_configuration_fault_keeps_payment_live_but_unready() -> None:
    client = TestClient(
        simulator_app.create_app(
            "payment",
            fault_behavior=FaultBehavior("bad-configuration", "run-abcdef123456"),
        )
    )
    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    response = client.post("/v1/authorizations", json=CHECKOUT)
    version = client.get("/versionz").json()
    assert ready.status_code == 503
    assert ready.json() == {"detail": "service configuration unavailable"}
    assert response.status_code == 503
    assert response.json() == {"detail": "payment configuration unavailable"}
    assert version["version"] == "1.0.0"
    assert "bad-configuration" not in str(version)


def test_order_calls_inventory_then_payment_with_same_correlation() -> None:
    """Order propagates one correlation ID across its deterministic dependency chain."""
    caller = FakeCaller()
    client = TestClient(create_test_app("order", caller))

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
        "created": True,
    }
    assert [call[0] for call in caller.calls] == ["inventory", "payment"]
    assert {call[3] for call in caller.calls} == {"corr-order"}


def test_order_duplicate_save_is_idempotent() -> None:
    """A duplicate order is confirmed but reports that no second row was created."""
    store = FakeOrderStore()
    client = TestClient(simulator_app.create_app("order", caller=FakeCaller(), order_store=store))

    first = client.post("/v1/orders", json=CHECKOUT)
    second = client.post("/v1/orders", json=CHECKOUT)

    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert store.saved == {"order-123"}


def test_order_maps_store_unavailability() -> None:
    """A PostgreSQL failure cannot be reported as a confirmed order."""
    store = FakeOrderStore()
    store.failure = DependencyUnavailable("offline")
    client = TestClient(simulator_app.create_app("order", caller=FakeCaller(), order_store=store))

    response = client.post("/v1/orders", json=CHECKOUT)

    assert response.status_code == 503
    assert response.json() == {"detail": "order dependency unavailable"}


def test_deployment_http_500_fault_is_bounded_to_order_business_path() -> None:
    """Faulty Order returns generic 500 without calling dependencies or exposing its label."""
    caller = FakeCaller()
    store = FakeOrderStore()
    app = simulator_app.create_app(
        "order",
        caller=caller,
        order_store=store,
        fault_behavior=FaultBehavior("http-500", "run-abcdef123456"),
    )
    client = TestClient(app)

    health = client.get("/healthz")
    ready = client.get("/readyz")
    first = client.post("/v1/orders", json=CHECKOUT)
    second = client.post("/v1/orders", json=CHECKOUT)

    assert health.status_code == ready.status_code == 200
    assert first.status_code == second.status_code == 500
    assert first.json() == {"detail": "internal server error"}
    assert "fault" not in first.text
    assert caller.calls == []
    assert store.saved == set()


def test_http_500_overlay_environment_links_fault_and_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generated overlay fields activate the symptom and an opaque version transition."""
    monkeypatch.setenv("SIMULATOR_FAULT_SCENARIO", "http-500")
    monkeypatch.setenv("SIMULATOR_FAULT_RUN_ID", "run-abcdef123456")
    monkeypatch.setenv("SERVICE_VERSION", "2.0.0")
    monkeypatch.setenv("PREVIOUS_SERVICE_VERSION", "1.0.0")
    monkeypatch.setenv("DEPLOYMENT_ID", "run-abcdef123456")
    client = TestClient(
        simulator_app.create_app("order", caller=FakeCaller(), order_store=FakeOrderStore())
    )

    version = client.get("/versionz").json()
    response = client.post("/v1/orders", json=CHECKOUT)

    assert version["version"] == "2.0.0"
    assert version["previous_version"] == "1.0.0"
    assert version["deployment_id"] == "run-abcdef123456"
    assert "http-500" not in str(version)
    assert response.status_code == 500


def test_database_pool_fault_composes_bounded_store_and_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order remains live while readiness and persistence expose database unavailability."""
    caller = FakeCaller()
    store = FakeOrderStore()
    store.failure = DependencyUnavailable("pool exhausted")
    captured: dict[str, object] = {}

    def create_store(*, tracer: object, exhaust_pool: bool) -> FakeOrderStore:
        captured.update(tracer=tracer, exhaust_pool=exhaust_pool)
        return store

    monkeypatch.setattr(simulator_app, "PostgresOrderStore", create_store)
    app = simulator_app.create_app(
        "order",
        caller=caller,
        fault_behavior=FaultBehavior("db-pool-exhaustion", "run-abcdef123456"),
    )
    client = TestClient(app)

    health = client.get("/healthz")
    ready = client.get("/readyz")
    response = client.post("/v1/orders", json=CHECKOUT)
    version = client.get("/versionz").json()

    assert captured["exhaust_pool"] is True
    assert health.status_code == 200
    assert ready.status_code == 503
    assert response.status_code == 503
    assert response.json() == {"detail": "order dependency unavailable"}
    assert [call[0] for call in caller.calls] == ["inventory", "payment"]
    assert version["version"] == "1.0.0"
    assert "db-pool-exhaustion" not in str(version)


def test_memory_fault_retains_only_on_order_business_requests() -> None:
    retention = BoundedMemoryRetention(chunk_bytes=4, limit_bytes=8)
    client = TestClient(
        simulator_app.create_app(
            "order",
            caller=FakeCaller(),
            order_store=FakeOrderStore(),
            fault_behavior=FaultBehavior("memory-leak", "run-abcdef123456"),
            memory_retention=retention,
        )
    )
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert retention.retain().retained_bytes == 4
    assert client.post("/v1/orders", json=CHECKOUT).status_code == 200
    assert retention.retain().retained_bytes == 8


def test_redis_timeout_fault_composes_inventory_store_and_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inventory stays live while readiness and reservations expose Redis unavailability."""
    store = FakeInventoryStore()
    store.failure = DependencyUnavailable("redis timed out")
    captured: dict[str, object] = {}

    def create_store(*, tracer: object, force_timeout: bool) -> FakeInventoryStore:
        captured.update(tracer=tracer, force_timeout=force_timeout)
        return store

    monkeypatch.setattr(simulator_app, "RedisInventoryStore", create_store)
    app = simulator_app.create_app(
        "inventory",
        caller=FakeCaller(),
        fault_behavior=FaultBehavior("redis-timeout", "run-abcdef123456"),
    )
    client = TestClient(app)

    health = client.get("/healthz")
    ready = client.get("/readyz")
    response = client.post("/v1/reservations", json=CHECKOUT)
    version = client.get("/versionz").json()

    assert captured["force_timeout"] is True
    assert health.status_code == 200
    assert ready.status_code == 503
    assert response.status_code == 503
    assert response.json() == {"detail": "inventory dependency unavailable"}
    assert version["version"] == "1.0.0"
    assert "redis-timeout" not in str(version)


@pytest.mark.parametrize("service", ["order", "inventory"])
def test_dependency_unavailability_fails_readiness(service: simulator_app.ServiceName) -> None:
    """Dependency-aware readiness fails closed without exposing adapter details."""
    store: FakeOrderStore | FakeInventoryStore
    if service == "order":
        store = FakeOrderStore()
        app = simulator_app.create_app("order", caller=FakeCaller(), order_store=store)
    else:
        store = FakeInventoryStore()
        app = simulator_app.create_app("inventory", caller=FakeCaller(), inventory_store=store)
    store.failure = DependencyUnavailable("secret internal detail")

    response = TestClient(app).get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"detail": "required dependency unavailable"}


@pytest.mark.parametrize("service", ["order", "inventory"])
def test_dependency_store_closes_with_application(service: simulator_app.ServiceName) -> None:
    """Service shutdown releases its selected database client."""
    store: FakeOrderStore | FakeInventoryStore
    if service == "order":
        store = FakeOrderStore()
        app = simulator_app.create_app("order", caller=FakeCaller(), order_store=store)
    else:
        store = FakeInventoryStore()
        app = simulator_app.create_app("inventory", caller=FakeCaller(), inventory_store=store)

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200

    assert store.closed is True


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
    client = TestClient(create_test_app(service, InvalidCaller()))

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
        inventory=simulator_app.create_app(
            "inventory", caller=caller, inventory_store=FakeInventoryStore()
        ),
        payment=simulator_app.create_app("payment", caller=caller),
    )
    caller.apps["order"] = simulator_app.create_app(
        "order", caller=caller, order_store=FakeOrderStore()
    )
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
        "created": True,
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
@pytest.mark.parametrize("mode", ["status", "json", "array", "timeout"])
async def test_httpx_caller_maps_downstream_failures(mode: str) -> None:
    """HTTP, malformed JSON, and wrong-shape responses become bounded 502 errors."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if mode == "timeout":
            raise httpx.ReadTimeout("slow downstream", request=request)
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
    monkeypatch.setattr(
        "agentops_incident_commander.simulator.main.create_app", lambda service: service
    )

    assert simulator_main.main(("inventory", "--host", "127.0.0.1", "--port", "9001")) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
    assert captured["app"] == "inventory"
