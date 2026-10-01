"""FastAPI applications for the Gateway, Order, Inventory, and Payment services."""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal, Protocol
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from agentops_incident_commander.simulator.dependencies import (
    DependencyUnavailable,
    InventoryInsufficient,
    InventoryStore,
    OrderStore,
    PostgresOrderStore,
    RedisInventoryStore,
)
from agentops_incident_commander.simulator.models import CheckoutRequest

ServiceName = Literal["gateway", "order", "inventory", "payment"]
CORRELATION_HEADER = "X-Correlation-ID"
CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ReservationResult(BaseModel):
    """Minimum trusted response from Inventory."""

    reservation_id: str = Field(min_length=1, max_length=80)


class AuthorizationResult(BaseModel):
    """Minimum trusted response from Payment."""

    authorization_id: str = Field(min_length=1, max_length=80)


class OrderResult(BaseModel):
    """Validated Order response returned through the Gateway."""

    order_id: str
    status: Literal["confirmed"]
    reservation_id: str
    authorization_id: str
    correlation_id: str
    created: bool


class ServiceCaller(Protocol):
    """Typed boundary for internal simulator HTTP calls."""

    async def post(
        self, service: str, path: str, payload: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]: ...


class HttpxServiceCaller:
    """Bounded internal HTTP caller that always propagates correlation."""

    def __init__(
        self,
        service_urls: dict[str, str],
        *,
        timeout_seconds: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._service_urls = service_urls
        self._timeout = timeout_seconds
        self._transport = transport

    async def post(
        self, service: str, path: str, payload: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]:
        base_url = self._service_urls.get(service)
        if base_url is None:
            raise HTTPException(status_code=500, detail=f"unknown downstream service: {service}")
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{base_url}{path}",
                    json=payload,
                    headers={CORRELATION_HEADER: correlation_id},
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(
                status_code=502,
                detail=f"downstream {service} request failed",
            ) from error
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=502, detail=f"downstream {service} returned invalid data"
            )
        return body


def _default_caller() -> HttpxServiceCaller:
    return HttpxServiceCaller(
        {
            "order": os.getenv("ORDER_SERVICE_URL", "http://order:8000"),
            "inventory": os.getenv("INVENTORY_SERVICE_URL", "http://inventory:8000"),
            "payment": os.getenv("PAYMENT_SERVICE_URL", "http://payment:8000"),
        }
    )


def _correlation_id(request: Request) -> str:
    return str(request.state.correlation_id)


def _validate_downstream[ModelT: BaseModel](
    model: type[ModelT], body: dict[str, Any], service: str
) -> ModelT:
    try:
        return model.model_validate(body)
    except ValidationError as error:
        raise HTTPException(
            status_code=502, detail=f"downstream {service} returned invalid data"
        ) from error


def create_app(
    service: ServiceName,
    *,
    caller: ServiceCaller | None = None,
    order_store: OrderStore | None = None,
    inventory_store: InventoryStore | None = None,
    correlation_factory: Callable[[], str] | None = None,
) -> FastAPI:
    """Create one role-specific simulator application."""
    selected_order_store = (order_store or PostgresOrderStore()) if service == "order" else None
    selected_inventory_store = (
        (inventory_store or RedisInventoryStore()) if service == "inventory" else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        try:
            yield
        finally:
            if selected_order_store is not None:
                await selected_order_store.close()
            if selected_inventory_store is not None:
                await selected_inventory_store.close()

    app = FastAPI(
        title=f"AgentOps Simulator {service.title()}",
        version="1.0.0",
        lifespan=lifespan,
    )
    downstream = caller or _default_caller()
    new_correlation = correlation_factory or (lambda: str(uuid4()))

    @app.middleware("http")
    async def correlation_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        supplied = request.headers.get(CORRELATION_HEADER)
        if supplied is not None and CORRELATION_PATTERN.fullmatch(supplied) is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "invalid correlation ID"},
            )
        correlation_id = supplied or new_correlation()
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = correlation_id
        return response

    @app.get("/healthz")
    async def health(request: Request) -> dict[str, str]:
        return {
            "status": "ok",
            "service": service,
            "correlation_id": _correlation_id(request),
        }

    @app.get("/readyz")
    async def ready(request: Request) -> dict[str, str]:
        correlation_id = _correlation_id(request)
        try:
            if selected_order_store is not None:
                await selected_order_store.ready(correlation_id)
            if selected_inventory_store is not None:
                await selected_inventory_store.ready(correlation_id)
        except DependencyUnavailable as error:
            raise HTTPException(
                status_code=503, detail="required dependency unavailable"
            ) from error
        return {
            "status": "ready",
            "service": service,
            "correlation_id": _correlation_id(request),
        }

    if service == "inventory":

        @app.post("/v1/reservations")
        async def reserve(checkout: CheckoutRequest, request: Request) -> dict[str, Any]:
            assert selected_inventory_store is not None
            try:
                outcome = await selected_inventory_store.reserve(checkout, _correlation_id(request))
            except InventoryInsufficient as error:
                raise HTTPException(status_code=409, detail="insufficient inventory") from error
            except DependencyUnavailable as error:
                raise HTTPException(
                    status_code=503, detail="inventory dependency unavailable"
                ) from error
            return {
                "reservation_id": outcome.reservation_id,
                "status": "reserved" if outcome.created else "already_reserved",
                "items": [item.model_dump() for item in checkout.items],
                "correlation_id": _correlation_id(request),
            }

    elif service == "payment":

        @app.post("/v1/authorizations")
        async def authorize(checkout: CheckoutRequest, request: Request) -> dict[str, Any]:
            return {
                "authorization_id": f"auth-{checkout.order_id}",
                "status": "authorized",
                "amount_minor": checkout.amount_minor,
                "currency": checkout.currency,
                "correlation_id": _correlation_id(request),
            }

    elif service == "order":

        @app.post("/v1/orders")
        async def create_order(checkout: CheckoutRequest, request: Request) -> dict[str, Any]:
            assert selected_order_store is not None
            correlation_id = _correlation_id(request)
            payload = checkout.model_dump(mode="json")
            reservation = await downstream.post(
                "inventory", "/v1/reservations", payload, correlation_id
            )
            authorization = await downstream.post(
                "payment", "/v1/authorizations", payload, correlation_id
            )
            validated_reservation = _validate_downstream(
                ReservationResult, reservation, "inventory"
            )
            validated_authorization = _validate_downstream(
                AuthorizationResult, authorization, "payment"
            )
            try:
                created = await selected_order_store.save(checkout, correlation_id)
            except DependencyUnavailable as error:
                raise HTTPException(
                    status_code=503, detail="order dependency unavailable"
                ) from error
            return {
                "order_id": checkout.order_id,
                "status": "confirmed",
                "reservation_id": validated_reservation.reservation_id,
                "authorization_id": validated_authorization.authorization_id,
                "correlation_id": correlation_id,
                "created": created,
            }

    elif service == "gateway":

        @app.post("/v1/checkout")
        async def checkout(checkout: CheckoutRequest, request: Request) -> dict[str, Any]:
            correlation_id = _correlation_id(request)
            order = await downstream.post(
                "order", "/v1/orders", checkout.model_dump(mode="json"), correlation_id
            )
            return _validate_downstream(OrderResult, order, "order").model_dump()

    else:
        raise ValueError(f"unknown simulator service: {service}")

    return app
