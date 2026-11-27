"""FastAPI routes and request principal resolution for production browser authentication."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from agentops_incident_commander.application import FederatedPrincipalResolver
from agentops_incident_commander.application.browser_auth import (
    BrowserAuthManager,
    BrowserAuthSettings,
    OidcCodeClient,
    OidcIdentityVerifier,
)
from agentops_incident_commander.domain import (
    AuthenticationError,
    Principal,
    TenantId,
    utc_now,
)
from agentops_incident_commander.infrastructure.persistence import (
    PostgresBrowserAuthStore,
    PostgresTenantMembershipStore,
)

from .api_v1 import Clock, SessionFactory

LOGIN_COOKIE = "__Host-agentops_oidc"
SESSION_COOKIE = "__Host-agentops_session"
CSRF_COOKIE = "__Host-agentops_csrf"
CSRF_HEADER = "X-CSRF-Token"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class BrowserAuthRuntime:
    def __init__(
        self,
        settings: BrowserAuthSettings,
        session_factory: SessionFactory,
        code_client: OidcCodeClient,
        identity_verifier: OidcIdentityVerifier,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self._code_client = code_client
        self._identity_verifier = identity_verifier
        self._clock = clock

    def _manager(self, session: object) -> BrowserAuthManager:
        store = PostgresBrowserAuthStore(session)  # type: ignore[arg-type]
        resolver = FederatedPrincipalResolver(PostgresTenantMembershipStore(session))  # type: ignore[arg-type]
        return BrowserAuthManager(
            self.settings,
            store,
            self._code_client,
            self._identity_verifier,
            resolver,
        )

    async def begin(self, tenant_id: TenantId) -> tuple[str, str, datetime]:
        async with self._session_factory() as session, session.begin():
            result = await self._manager(session).begin(tenant_id, now=self._clock())
        return result.authorization_url, result.transaction_cookie, result.expires_at

    async def complete(
        self, *, code: str, state: str, transaction_cookie: str
    ) -> tuple[str, str, datetime]:
        async with self._session_factory() as session, session.begin():
            result = await self._manager(session).complete(
                code=code,
                state=state,
                transaction_cookie=transaction_cookie,
                now=self._clock(),
            )
        return result.session_cookie, result.csrf_cookie, result.expires_at

    async def principal(self, request: Request) -> Principal | None:
        session_cookie = request.cookies.get(SESSION_COOKIE)
        if session_cookie is None:
            return None
        async with self._session_factory() as session:
            return await self._manager(session).resolve(
                session_cookie=session_cookie,
                csrf_cookie=request.cookies.get(CSRF_COOKIE),
                csrf_header=request.headers.get(CSRF_HEADER),
                require_csrf=request.method in _UNSAFE_METHODS,
                now=self._clock(),
            )

    async def logout(self, request: Request) -> None:
        session_cookie = request.cookies.get(SESSION_COOKIE)
        if session_cookie is None:
            raise AuthenticationError("browser session is missing")
        async with self._session_factory() as session, session.begin():
            manager = self._manager(session)
            await manager.resolve(
                session_cookie=session_cookie,
                csrf_cookie=request.cookies.get(CSRF_COOKIE),
                csrf_header=request.headers.get(CSRF_HEADER),
                require_csrf=True,
                now=self._clock(),
            )
            await manager.logout(session_cookie=session_cookie, now=self._clock())


def _authentication_failure(exc: AuthenticationError) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc))


def build_browser_auth_router(runtime: BrowserAuthRuntime) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["authentication"])

    @router.get("/login", include_in_schema=False)
    async def login(tenant_id: str = Query(min_length=1, max_length=128)) -> Response:
        try:
            url, transaction, expires_at = await runtime.begin(TenantId(tenant_id))
        except (AuthenticationError, ValueError) as exc:
            raise _authentication_failure(AuthenticationError(str(exc))) from exc
        response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            LOGIN_COOKIE,
            transaction,
            expires=expires_at,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response

    @router.get("/callback", include_in_schema=False)
    async def callback(request: Request, code: str, state: str) -> Response:
        transaction = request.cookies.get(LOGIN_COOKIE, "")
        try:
            session_cookie, csrf_cookie, expires_at = await runtime.complete(
                code=code, state=state, transaction_cookie=transaction
            )
        except AuthenticationError as exc:
            raise _authentication_failure(exc) from exc
        response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie(LOGIN_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        response.set_cookie(
            SESSION_COOKIE,
            session_cookie,
            expires=expires_at,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf_cookie,
            expires=expires_at,
            secure=True,
            httponly=False,
            samesite="strict",
            path="/",
        )
        return response

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request) -> Response:
        try:
            await runtime.logout(request)
        except AuthenticationError as exc:
            raise _authentication_failure(exc) from exc
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        response.delete_cookie(
            CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="strict"
        )
        return response

    return router
