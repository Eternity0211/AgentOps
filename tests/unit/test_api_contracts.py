"""OpenAPI drift and stable problem-detail convention tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from agentops_incident_commander.apps.api import create_app
from agentops_incident_commander.apps.api_contracts import apply_openapi_conventions
from agentops_incident_commander.apps.api_v1 import SessionFactory
from agentops_incident_commander.apps.config import ApiSettings
from agentops_incident_commander.domain import ActorId, Principal, Role, TenantId

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ApiSettings("postgresql+asyncpg://unused:unused@localhost/unused", "127.0.0.1", 8000)


class SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


def session_factory() -> SessionContext:
    return SessionContext()


def app_for(principal: Principal | None) -> TestClient:
    async def resolve(_: Request) -> Principal | None:
        return principal

    app = create_app(
        SETTINGS,
        session_factory=cast(SessionFactory, session_factory),
        principal_resolver=resolve,
        request_id_factory=lambda: "request-contract-1",
    )
    return TestClient(app)


def test_openapi_matches_reviewable_contract_snapshot() -> None:
    app = create_app(SETTINGS)
    schema = app.openapi()
    assert app.openapi() is schema
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    snapshot = json.loads(
        (ROOT / "tests" / "snapshots" / "openapi_v1.json").read_text(encoding="utf-8")
    )

    assert hashlib.sha256(canonical).hexdigest() == snapshot["sha256"]
    assert {path: sorted(item) for path, item in schema["paths"].items()} == snapshot["paths"]
    assert sorted(schema["components"]["schemas"]) == snapshot["schemas"]

    for path, item in schema["paths"].items():
        for operation in item.values():
            for code, response in operation["responses"].items():
                assert "X-Request-ID" in response["headers"], (path, code)
                if code.startswith(("4", "5")):
                    assert list(response["content"]) == ["application/problem+json"]
    for path in (
        "/api/v1/incidents/{incident_id}/controls/start-investigation",
        "/api/v1/incidents/{incident_id}/controls/cancel",
    ):
        assert (
            "Idempotency-Replayed" in schema["paths"][path]["post"]["responses"]["200"]["headers"]
        )


def test_openapi_convention_transform_fails_safely_on_unrelated_shapes() -> None:
    schema: dict[str, Any] = {
        "paths": {
            "/healthz": {},
            "/api/v1/not-an-item": "invalid",
            "/api/v1/no-operation": {"get": []},
            "/api/v1/no-responses": {"get": {}},
            "/api/v1/bad-responses": {"get": {"responses": []}},
            "/api/v1/bad-response": {"get": {"responses": {"400": []}}},
            "/api/v1/example/controls/cancel": {"post": {"responses": {"200": []}}},
        }
    }
    assert apply_openapi_conventions(schema) is schema


def test_problem_details_are_stable_correlated_and_do_not_echo_invalid_input() -> None:
    operator = Principal(
        ActorId("operator-contract"),
        TenantId("tenant-contract"),
        frozenset({Role.OPERATOR}),
    )
    with app_for(operator) as client:
        missing = client.get("/api/v1/does-not-exist")
        invalid = client.post(
            "/api/v1/incidents/incident-1/controls/cancel",
            headers={"Idempotency-Key": "contains spaces"},
            json={"reason": "secret-invalid-value"},
        )

    assert missing.status_code == 404
    assert missing.json()["code"] == "RESOURCE_NOT_FOUND"
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.headers["x-request-id"] == missing.json()["request_id"]

    assert invalid.status_code == 422
    body = invalid.json()
    assert body["code"] == "REQUEST_VALIDATION_FAILED"
    assert body["type"].endswith(":request-validation-failed")
    assert body["instance"].endswith("/controls/cancel")
    assert body["errors"]
    assert "secret-invalid-value" not in invalid.text
    assert invalid.headers["x-request-id"] == "request-contract-1"


def test_authentication_problem_and_method_error_use_same_envelope() -> None:
    with app_for(None) as client:
        unauthenticated = client.get("/api/v1/incidents")
        method = client.delete("/api/v1/incidents")

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert method.status_code == 405
    assert method.json()["code"] == "METHOD_NOT_ALLOWED"
    assert "allow" in method.headers


def test_unexpected_errors_are_generic_and_http_fallback_remains_typed() -> None:
    app = create_app(
        SETTINGS,
        session_factory=cast(SessionFactory, session_factory),
        request_id_factory=lambda: "request-error-1",
    )

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("sensitive internal detail")

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(418, {"unsafe": "structured detail"})

    with TestClient(app, raise_server_exceptions=False) as client:
        internal = client.get("/boom")
        fallback = client.get("/teapot")

    assert internal.status_code == 500
    assert internal.json()["code"] == "INTERNAL_ERROR"
    assert "sensitive" not in internal.text
    assert fallback.status_code == 418
    assert fallback.json()["code"] == "HTTP_ERROR"
    assert fallback.json()["detail"] == "HTTP request failed"
