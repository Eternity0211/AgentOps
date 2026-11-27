"""OIDC browser login orchestration with server-owned sessions and CSRF binding."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from agentops_incident_commander.domain import (
    AuthenticationError,
    FederatedIdentity,
    Principal,
    TenantId,
    as_utc,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_secret(value: str, *, label: str) -> str:
    if not 32 <= len(value) <= 512 or not value.isascii():
        raise AuthenticationError(f"{label} is missing or invalid")
    return value


@dataclass(frozen=True, slots=True)
class BrowserAuthSettings:
    authorization_endpoint: str
    client_id: str
    redirect_uri: str
    login_ttl_seconds: int = 300
    session_ttl_seconds: int = 28_800

    def __post_init__(self) -> None:
        for label, value in (
            ("authorization endpoint", self.authorization_endpoint),
            ("redirect URI", self.redirect_uri),
        ):
            parsed = urlsplit(value)
            if (
                len(value) > 2048
                or parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ValueError(f"OIDC {label} must be a bounded HTTPS URL")
        if urlsplit(self.authorization_endpoint).query:
            raise ValueError("OIDC authorization endpoint cannot contain a query")
        if (
            not self.client_id
            or len(self.client_id) > 255
            or self.client_id.strip() != self.client_id
        ):
            raise ValueError("OIDC client ID must be between 1 and 255 characters")
        if not 60 <= self.login_ttl_seconds <= 900:
            raise ValueError("OIDC login TTL must be between 60 and 900 seconds")
        if not 300 <= self.session_ttl_seconds <= 86_400:
            raise ValueError("browser session TTL must be between 300 and 86400 seconds")


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    state_hash: str
    transaction_hash: str
    tenant_id: TenantId
    nonce: str
    code_verifier: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class LoginStart:
    authorization_url: str
    transaction_cookie: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class BrowserSession:
    session_hash: str
    csrf_hash: str
    principal: Principal
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class LoginCompletion:
    session_cookie: str
    csrf_cookie: str
    expires_at: datetime


class BrowserAuthStore(Protocol):
    async def save_login_attempt(self, attempt: LoginAttempt, *, now: datetime) -> None: ...

    async def consume_login_attempt(
        self, *, state_hash: str, transaction_hash: str, now: datetime
    ) -> LoginAttempt | None: ...

    async def create_session(self, session: BrowserSession, *, now: datetime) -> None: ...

    async def resolve_session(
        self, *, session_hash: str, now: datetime
    ) -> BrowserSession | None: ...

    async def revoke_session(self, *, session_hash: str, now: datetime) -> None: ...


class OidcCodeClient(Protocol):
    async def exchange(self, *, code: str, code_verifier: str) -> str: ...


class OidcIdentityVerifier(Protocol):
    async def verify(
        self, token: str, *, expected_nonce: str | None = None
    ) -> FederatedIdentity: ...


class TenantPrincipalResolver(Protocol):
    async def resolve(self, identity: FederatedIdentity, *, tenant_id: TenantId) -> Principal: ...


class BrowserAuthManager:
    """Create and consume one-time OIDC transactions without trusting browser authority."""

    def __init__(
        self,
        settings: BrowserAuthSettings,
        store: BrowserAuthStore,
        code_client: OidcCodeClient,
        identity_verifier: OidcIdentityVerifier,
        principal_resolver: TenantPrincipalResolver,
    ) -> None:
        self._settings = settings
        self._store = store
        self._code_client = code_client
        self._identity_verifier = identity_verifier
        self._principal_resolver = principal_resolver

    async def begin(self, tenant_id: TenantId, *, now: datetime) -> LoginStart:
        current = as_utc(now)
        state = secrets.token_urlsafe(32)
        transaction = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        expires_at = current + timedelta(seconds=self._settings.login_ttl_seconds)
        await self._store.save_login_attempt(
            LoginAttempt(
                state_hash=_digest(state),
                transaction_hash=_digest(transaction),
                tenant_id=tenant_id,
                nonce=nonce,
                code_verifier=verifier,
                expires_at=expires_at,
            ),
            now=current,
        )
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(
            b"="
        )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.client_id,
                "redirect_uri": self._settings.redirect_uri,
                "scope": "openid",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge.decode("ascii"),
                "code_challenge_method": "S256",
            }
        )
        return LoginStart(
            authorization_url=f"{self._settings.authorization_endpoint}?{query}",
            transaction_cookie=transaction,
            expires_at=expires_at,
        )

    async def complete(
        self, *, code: str, state: str, transaction_cookie: str, now: datetime
    ) -> LoginCompletion:
        current = as_utc(now)
        attempt = await self._store.consume_login_attempt(
            state_hash=_digest(_bounded_secret(state, label="OIDC state")),
            transaction_hash=_digest(
                _bounded_secret(transaction_cookie, label="OIDC transaction cookie")
            ),
            now=current,
        )
        if attempt is None or attempt.expires_at <= current:
            raise AuthenticationError("OIDC login transaction is invalid or expired")
        id_token = await self._code_client.exchange(
            code=_bounded_secret(code, label="OIDC authorization code"),
            code_verifier=attempt.code_verifier,
        )
        identity = await self._identity_verifier.verify(id_token, expected_nonce=attempt.nonce)
        principal = await self._principal_resolver.resolve(identity, tenant_id=attempt.tenant_id)
        raw_session = secrets.token_urlsafe(48)
        raw_csrf = secrets.token_urlsafe(32)
        expires_at = current + timedelta(seconds=self._settings.session_ttl_seconds)
        await self._store.create_session(
            BrowserSession(
                session_hash=_digest(raw_session),
                csrf_hash=_digest(raw_csrf),
                principal=principal,
                expires_at=expires_at,
            ),
            now=current,
        )
        return LoginCompletion(raw_session, raw_csrf, expires_at)

    async def resolve(
        self,
        *,
        session_cookie: str,
        csrf_cookie: str | None,
        csrf_header: str | None,
        require_csrf: bool,
        now: datetime,
    ) -> Principal:
        current = as_utc(now)
        raw_session = _bounded_secret(session_cookie, label="browser session")
        session = await self._store.resolve_session(session_hash=_digest(raw_session), now=current)
        if session is None or session.expires_at <= current:
            raise AuthenticationError("browser session is invalid or expired")
        if require_csrf:
            cookie = _bounded_secret(csrf_cookie or "", label="CSRF cookie")
            header = _bounded_secret(csrf_header or "", label="CSRF header")
            if not hmac.compare_digest(cookie, header) or not hmac.compare_digest(
                _digest(cookie), session.csrf_hash
            ):
                raise AuthenticationError("CSRF validation failed")
        return session.principal

    async def logout(self, *, session_cookie: str, now: datetime) -> None:
        raw_session = _bounded_secret(session_cookie, label="browser session")
        await self._store.revoke_session(session_hash=_digest(raw_session), now=as_utc(now))
