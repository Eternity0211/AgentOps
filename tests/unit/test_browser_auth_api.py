"""Tests for FastAPI OIDC redirects, secure cookies, CSRF logout, and request resolution."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentops_incident_commander.application.browser_auth import (
    BrowserAuthManager,
    BrowserAuthSettings,
)
from agentops_incident_commander.apps.browser_auth import (
    CSRF_COOKIE,
    CSRF_HEADER,
    LOGIN_COOKIE,
    SESSION_COOKIE,
    BrowserAuthRuntime,
    build_browser_auth_router,
)
from agentops_incident_commander.domain import (
    ActorId,
    AuthenticationError,
    Principal,
    Role,
    TenantId,
)

NOW = datetime(2026, 11, 27, 8, 0, tzinfo=UTC)


class Runtime:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.started: list[str] = []
        self.completed: list[tuple[str, str, str]] = []
        self.logout_requests: list[Request] = []

    async def begin(self, tenant_id: Any) -> tuple[str, str, datetime]:
        if self.fail:
            raise AuthenticationError("login refused")
        self.started.append(tenant_id.value)
        return (
            "https://identity.example.test/authorize?state=opaque",
            "transaction-cookie-value-1234567890",
            NOW + timedelta(minutes=5),
        )

    async def complete(
        self, *, code: str, state: str, transaction_cookie: str
    ) -> tuple[str, str, datetime]:
        if self.fail:
            raise AuthenticationError("callback refused")
        self.completed.append((code, state, transaction_cookie))
        return (
            "session-cookie-value-12345678901234567890",
            "csrf-cookie-value-12345678901234567890",
            NOW + timedelta(hours=8),
        )

    async def logout(self, request: Request) -> None:
        if self.fail:
            raise AuthenticationError("logout refused")
        self.logout_requests.append(request)


def app(runtime: Runtime) -> FastAPI:
    value = FastAPI()
    value.include_router(build_browser_auth_router(cast(BrowserAuthRuntime, runtime)))
    return value


def test_login_redirect_sets_host_only_secure_transaction_cookie() -> None:
    runtime = Runtime()
    with TestClient(app(runtime), base_url="https://console.example.test") as client:
        response = client.get("/auth/login?tenant_id=tenant-1", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://identity.example.test/")
    cookie = response.headers["set-cookie"]
    assert LOGIN_COOKIE in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert runtime.started == ["tenant-1"]


def test_callback_rotates_transaction_into_session_and_csrf_cookies() -> None:
    runtime = Runtime()
    with TestClient(app(runtime), base_url="https://console.example.test") as client:
        client.cookies.set(LOGIN_COOKIE, "transaction-cookie-value-1234567890")
        response = client.get(
            "/auth/callback?code=authorization-code-value-1234567890&state=state-value-12345678901234567890",
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookies = response.headers.get_list("set-cookie")
    assert any(SESSION_COOKIE in item and "HttpOnly" in item for item in cookies)
    assert any(CSRF_COOKIE in item and "HttpOnly" not in item for item in cookies)
    assert runtime.completed == [
        (
            "authorization-code-value-1234567890",
            "state-value-12345678901234567890",
            "transaction-cookie-value-1234567890",
        )
    ]


def test_logout_clears_browser_cookies() -> None:
    runtime = Runtime()
    with TestClient(app(runtime), base_url="https://console.example.test") as client:
        response = client.post("/auth/logout")
    assert response.status_code == 204
    cookies = response.headers.get_list("set-cookie")
    assert any(SESSION_COOKIE in item and "Max-Age=0" in item for item in cookies)
    assert any(CSRF_COOKIE in item and "Max-Age=0" in item for item in cookies)
    assert len(runtime.logout_requests) == 1


@pytest.mark.parametrize(
    "path",
    [
        "/auth/login?tenant_id=tenant-1",
        "/auth/callback?code=authorization-code-value-1234567890&state=state-value-12345678901234567890",
    ],
)
def test_login_and_callback_fail_closed(path: str) -> None:
    with TestClient(app(Runtime(fail=True)), base_url="https://console.example.test") as client:
        response = client.get(path, follow_redirects=False)
    assert response.status_code == 401


def test_logout_failure_is_unauthorized() -> None:
    with TestClient(app(Runtime(fail=True)), base_url="https://console.example.test") as client:
        response = client.post("/auth/logout")
    assert response.status_code == 401


class Context(AbstractAsyncContextManager[Any]):
    async def __aenter__(self) -> object:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> Context:
        return self


class Manager:
    def __init__(self) -> None:
        self.logout_values: list[str] = []

    async def begin(self, tenant_id: TenantId, *, now: datetime) -> Any:
        assert tenant_id == TenantId("tenant-1") and now == NOW
        return type(
            "Start",
            (),
            {
                "authorization_url": "https://identity.example.test/authorize",
                "transaction_cookie": "t" * 32,
                "expires_at": NOW + timedelta(minutes=5),
            },
        )()

    async def complete(self, **values: Any) -> Any:
        assert values["now"] == NOW
        return type(
            "Complete",
            (),
            {
                "session_cookie": "s" * 32,
                "csrf_cookie": "c" * 32,
                "expires_at": NOW + timedelta(hours=8),
            },
        )()

    async def resolve(self, **values: Any) -> Principal:
        assert values["now"] == NOW
        return Principal(ActorId("actor-1"), TenantId("tenant-1"), frozenset({Role.VIEWER}))

    async def logout(self, *, session_cookie: str, now: datetime) -> None:
        assert now == NOW
        self.logout_values.append(session_cookie)


@pytest.mark.anyio
async def test_runtime_coordinates_transactions_principal_and_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()
    manager = Manager()
    runtime = BrowserAuthRuntime(
        BrowserAuthSettings(
            "https://identity.example.test/authorize",
            "agentops",
            "https://console.example.test/auth/callback",
        ),
        cast(Any, lambda: context),
        cast(Any, object()),
        cast(Any, object()),
        clock=lambda: NOW,
    )
    assert isinstance(runtime._manager(object()), BrowserAuthManager)
    monkeypatch.setattr(runtime, "_manager", lambda _: manager)
    assert await runtime.begin(TenantId("tenant-1")) == (
        "https://identity.example.test/authorize",
        "t" * 32,
        NOW + timedelta(minutes=5),
    )
    assert await runtime.complete(code="c" * 32, state="a" * 32, transaction_cookie="t" * 32) == (
        "s" * 32,
        "c" * 32,
        NOW + timedelta(hours=8),
    )

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/approvals/a/approve",
        "headers": [
            (b"cookie", f"{SESSION_COOKIE}={'s' * 32}; {CSRF_COOKIE}={'c' * 32}".encode()),
            (CSRF_HEADER.lower().encode(), ("c" * 32).encode()),
        ],
    }
    request = Request(scope)
    principal = await runtime.principal(request)
    assert principal is not None and principal.actor_id == ActorId("actor-1")
    await runtime.logout(request)
    assert manager.logout_values == ["s" * 32]


@pytest.mark.anyio
async def test_runtime_returns_none_or_refuses_when_session_cookie_is_missing() -> None:
    runtime = BrowserAuthRuntime(
        BrowserAuthSettings(
            "https://identity.example.test/authorize",
            "agentops",
            "https://console.example.test/auth/callback",
        ),
        cast(Any, lambda: Context()),
        cast(Any, object()),
        cast(Any, object()),
        clock=lambda: NOW,
    )
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    assert await runtime.principal(request) is None
    with pytest.raises(AuthenticationError, match="missing"):
        await runtime.logout(request)
