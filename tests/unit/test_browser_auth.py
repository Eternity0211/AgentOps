"""Tests for one-time OIDC browser transactions, server sessions, and CSRF."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from agentops_incident_commander.application.browser_auth import (
    BrowserAuthManager,
    BrowserAuthSettings,
    BrowserSession,
    LoginAttempt,
)
from agentops_incident_commander.domain import (
    ActorId,
    AuthenticationError,
    FederatedIdentity,
    Principal,
    Role,
    TenantId,
)

NOW = datetime(2026, 11, 27, 8, 0, tzinfo=UTC)
PRINCIPAL = Principal(ActorId("actor-1"), TenantId("tenant-1"), frozenset({Role.OPERATOR}))


class Store:
    def __init__(self) -> None:
        self.attempt: LoginAttempt | None = None
        self.session: BrowserSession | None = None
        self.revoked: list[str] = []

    async def save_login_attempt(self, attempt: LoginAttempt, *, now: datetime) -> None:
        assert now == NOW
        self.attempt = attempt

    async def consume_login_attempt(
        self, *, state_hash: str, transaction_hash: str, now: datetime
    ) -> LoginAttempt | None:
        assert now == NOW
        if (
            self.attempt is None
            or self.attempt.state_hash != state_hash
            or self.attempt.transaction_hash != transaction_hash
        ):
            return None
        return self.attempt

    async def create_session(self, session: BrowserSession, *, now: datetime) -> None:
        assert now == NOW
        self.session = session

    async def resolve_session(self, *, session_hash: str, now: datetime) -> BrowserSession | None:
        assert now == NOW
        return self.session if self.session and self.session.session_hash == session_hash else None

    async def revoke_session(self, *, session_hash: str, now: datetime) -> None:
        assert now == NOW
        self.revoked.append(session_hash)


class CodeClient:
    def __init__(self) -> None:
        self.values: list[tuple[str, str]] = []

    async def exchange(self, *, code: str, code_verifier: str) -> str:
        self.values.append((code, code_verifier))
        return "id-token"


class Verifier:
    def __init__(self) -> None:
        self.values: list[tuple[str, str | None]] = []

    async def verify(self, token: str, *, expected_nonce: str | None = None) -> FederatedIdentity:
        self.values.append((token, expected_nonce))
        return FederatedIdentity("https://identity.example.test", "user-1")


class Resolver:
    async def resolve(self, identity: FederatedIdentity, *, tenant_id: TenantId) -> Principal:
        assert identity.subject == "user-1"
        assert tenant_id == TenantId("tenant-1")
        return PRINCIPAL


def manager(store: Store) -> tuple[BrowserAuthManager, CodeClient, Verifier]:
    code = CodeClient()
    verifier = Verifier()
    return (
        BrowserAuthManager(
            BrowserAuthSettings(
                "https://identity.example.test/authorize",
                "agentops",
                "https://console.example.test/auth/callback",
            ),
            store,
            code,
            verifier,
            Resolver(),
        ),
        code,
        verifier,
    )


@pytest.mark.parametrize(
    "values",
    [
        ("http://identity.test/authorize", "agentops", "https://console.test/callback", 300, 300),
        ("https://user:pass@identity.test", "agentops", "https://console.test/callback", 300, 300),
        ("https://identity.test/path?x=1", "agentops", "https://console.test/callback", 300, 300),
        ("https://identity.test/path", "", "https://console.test/callback", 300, 300),
        ("https://identity.test/path", " agentops", "https://console.test/callback", 300, 300),
        ("https://identity.test/path", "agentops", "http://console.test/callback", 300, 300),
        ("https://identity.test/path", "agentops", "https://console.test/callback", 59, 300),
        ("https://identity.test/path", "agentops", "https://console.test/callback", 901, 300),
        ("https://identity.test/path", "agentops", "https://console.test/callback", 300, 299),
        ("https://identity.test/path", "agentops", "https://console.test/callback", 300, 86_401),
    ],
)
def test_browser_auth_settings_are_bounded(values: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        BrowserAuthSettings(*values)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_begin_creates_pkce_transaction_and_bounded_redirect() -> None:
    store = Store()
    auth, _, _ = manager(store)
    result = await auth.begin(TenantId("tenant-1"), now=NOW)
    query = parse_qs(urlsplit(result.authorization_url).query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["agentops"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["openid"]
    assert store.attempt is not None
    assert store.attempt.tenant_id == TenantId("tenant-1")
    assert store.attempt.expires_at == NOW + timedelta(minutes=5)
    assert query["nonce"] == [store.attempt.nonce]
    assert result.expires_at == store.attempt.expires_at
    assert result.transaction_cookie not in result.authorization_url


@pytest.mark.anyio
async def test_complete_verifies_nonce_and_creates_opaque_session() -> None:
    store = Store()
    auth, code_client, verifier = manager(store)
    start = await auth.begin(TenantId("tenant-1"), now=NOW)
    state = parse_qs(urlsplit(start.authorization_url).query)["state"][0]
    result = await auth.complete(
        code="authorization-code-value-1234567890",
        state=state,
        transaction_cookie=start.transaction_cookie,
        now=NOW,
    )
    assert store.attempt is not None and store.session is not None
    assert code_client.values == [
        ("authorization-code-value-1234567890", store.attempt.code_verifier)
    ]
    assert verifier.values == [("id-token", store.attempt.nonce)]
    assert store.session.principal == PRINCIPAL
    assert result.session_cookie not in {store.session.session_hash, result.csrf_cookie}
    assert result.expires_at == NOW + timedelta(hours=8)


@pytest.mark.anyio
async def test_complete_rejects_invalid_expired_or_unbounded_transactions() -> None:
    store = Store()
    auth, _, _ = manager(store)
    with pytest.raises(AuthenticationError, match="state"):
        await auth.complete(code="c" * 32, state="short", transaction_cookie="t" * 32, now=NOW)

    start = await auth.begin(TenantId("tenant-1"), now=NOW)
    state = parse_qs(urlsplit(start.authorization_url).query)["state"][0]
    assert store.attempt is not None
    store.attempt = LoginAttempt(
        store.attempt.state_hash,
        store.attempt.transaction_hash,
        store.attempt.tenant_id,
        store.attempt.nonce,
        store.attempt.code_verifier,
        NOW,
    )
    with pytest.raises(AuthenticationError, match="invalid or expired"):
        await auth.complete(
            code="c" * 32,
            state=state,
            transaction_cookie=start.transaction_cookie,
            now=NOW,
        )


@pytest.mark.anyio
async def test_session_resolution_requires_bound_csrf_for_mutations() -> None:
    store = Store()
    auth, _, _ = manager(store)
    start = await auth.begin(TenantId("tenant-1"), now=NOW)
    state = parse_qs(urlsplit(start.authorization_url).query)["state"][0]
    completed = await auth.complete(
        code="c" * 32, state=state, transaction_cookie=start.transaction_cookie, now=NOW
    )
    assert (
        await auth.resolve(
            session_cookie=completed.session_cookie,
            csrf_cookie=None,
            csrf_header=None,
            require_csrf=False,
            now=NOW,
        )
        == PRINCIPAL
    )
    assert (
        await auth.resolve(
            session_cookie=completed.session_cookie,
            csrf_cookie=completed.csrf_cookie,
            csrf_header=completed.csrf_cookie,
            require_csrf=True,
            now=NOW,
        )
        == PRINCIPAL
    )
    with pytest.raises(AuthenticationError, match="CSRF"):
        await auth.resolve(
            session_cookie=completed.session_cookie,
            csrf_cookie=completed.csrf_cookie,
            csrf_header="x" * 32,
            require_csrf=True,
            now=NOW,
        )


@pytest.mark.anyio
async def test_session_resolution_and_logout_fail_closed() -> None:
    store = Store()
    auth, _, _ = manager(store)
    with pytest.raises(AuthenticationError, match="browser session"):
        await auth.resolve(
            session_cookie="x" * 32,
            csrf_cookie=None,
            csrf_header=None,
            require_csrf=False,
            now=NOW,
        )
    with pytest.raises(AuthenticationError, match="browser session"):
        await auth.logout(session_cookie="short", now=NOW)
    await auth.logout(session_cookie="x" * 32, now=NOW)
    assert len(store.revoked) == 1
