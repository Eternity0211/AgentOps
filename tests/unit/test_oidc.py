"""Tests for bounded asymmetric OIDC verification."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from agentops_incident_commander.domain import AuthenticationError
from agentops_incident_commander.infrastructure import (
    HttpJwksProvider,
    HttpOidcCodeClient,
    OidcTokenVerifier,
    OidcVerifierSettings,
)

ISSUER = "https://identity.example.test/realms/agentops"
AUDIENCE = "agentops-control-plane"
KEY_ID = "signing-key-1"


class Jwks:
    def __init__(self, document: dict[str, object]) -> None:
        self.document = document

    async def load(self) -> dict[str, object]:
        return self.document


@pytest.fixture
def key_pair() -> tuple[Any, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": KEY_ID, "alg": "RS256", "use": "sig"})
    return private_key, public_jwk


def token(private_key: Any, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": "external-user-1",
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "tenant_id": "attacker-controlled-tenant",
        "roles": ["ADMIN"],
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KEY_ID})


def verifier(jwk_document: dict[str, object]) -> OidcTokenVerifier:
    return OidcTokenVerifier(OidcVerifierSettings(ISSUER, AUDIENCE), Jwks(jwk_document))


@pytest.mark.anyio
async def test_verified_token_yields_identity_only_and_ignores_authority_claims(
    key_pair: tuple[Any, dict[str, object]],
) -> None:
    private_key, public_jwk = key_pair
    identity = await verifier({"keys": [public_jwk]}).verify(token(private_key))
    assert identity.issuer == ISSUER
    assert identity.subject == "external-user-1"
    assert not hasattr(identity, "roles")
    assert not hasattr(identity, "tenant_id")


@pytest.mark.anyio
async def test_nonce_is_verified_when_browser_flow_requires_it(
    key_pair: tuple[Any, dict[str, object]],
) -> None:
    private_key, public_jwk = key_pair
    value = token(private_key, nonce="expected-nonce")
    identity = await verifier({"keys": [public_jwk]}).verify(value, expected_nonce="expected-nonce")
    assert identity.subject == "external-user-1"
    with pytest.raises(AuthenticationError, match="nonce"):
        await verifier({"keys": [public_jwk]}).verify(value, expected_nonce="different-nonce")
    with pytest.raises(AuthenticationError, match="nonce"):
        await verifier({"keys": [public_jwk]}).verify(
            token(private_key), expected_nonce="expected-nonce"
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"issuer": "http://identity.example.test"},
        {"issuer": "https://user:password@identity.example.test"},
        {"issuer": "https://identity.example.test?query=yes"},
        {"issuer": "https://identity.example.test#fragment"},
        {"issuer": "https://[invalid"},
        {"issuer": "https://" + "a" * 2048},
        {"audience": ""},
        {"audience": " audience"},
        {"audience": "a" * 256},
        {"algorithms": ()},
        {"algorithms": ("HS256",)},
        {"algorithms": ("RS256", "RS256")},
        {"leeway_seconds": -1},
        {"leeway_seconds": 301},
        {"max_token_bytes": 1023},
        {"max_token_bytes": 65_537},
    ],
)
def test_settings_are_bounded(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {"issuer": ISSUER, "audience": AUDIENCE}
    values.update(kwargs)
    with pytest.raises(ValueError):
        OidcVerifierSettings(**values)  # type: ignore[arg-type]


@pytest.mark.anyio
@pytest.mark.parametrize("raw", ["", "not-a-token"])
async def test_absent_or_malformed_token_is_rejected(raw: str) -> None:
    with pytest.raises(AuthenticationError):
        await verifier({"keys": []}).verify(raw)


@pytest.mark.anyio
async def test_oversized_token_is_rejected_before_jwks_lookup() -> None:
    bounded = OidcTokenVerifier(
        OidcVerifierSettings(ISSUER, AUDIENCE, max_token_bytes=1024), Jwks({"keys": []})
    )
    with pytest.raises(AuthenticationError, match="size limit"):
        await bounded.verify("x" * 1025)


@pytest.mark.anyio
async def test_algorithm_and_key_identifier_are_required(
    key_pair: tuple[Any, dict[str, object]],
) -> None:
    private_key, _ = key_pair
    raw = jwt.encode({"sub": "user"}, private_key, algorithm="RS256", headers={"kid": ""})
    with pytest.raises(AuthenticationError, match="algorithm or key"):
        await verifier({"keys": []}).verify(raw)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "document",
    [
        {},
        {"keys": "not-a-list"},
        {"keys": []},
        {"keys": [{"kid": KEY_ID, "alg": "RS256", "use": "enc"}]},
        {"keys": [{"kid": KEY_ID, "alg": "ES256"}]},
    ],
)
async def test_invalid_or_missing_jwks_is_rejected(
    document: dict[str, object], key_pair: tuple[Any, dict[str, object]]
) -> None:
    private_key, _ = key_pair
    with pytest.raises(AuthenticationError):
        await verifier(document).verify(token(private_key))


@pytest.mark.anyio
async def test_ambiguous_or_invalid_key_is_rejected(
    key_pair: tuple[Any, dict[str, object]],
) -> None:
    private_key, public_jwk = key_pair
    with pytest.raises(AuthenticationError, match="ambiguous"):
        await verifier({"keys": [public_jwk, public_jwk]}).verify(token(private_key))
    invalid = {"kid": KEY_ID, "alg": "RS256", "use": "sig", "kty": "invalid"}
    with pytest.raises(AuthenticationError, match="validation failed"):
        await verifier({"keys": [invalid]}).verify(token(private_key))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.example.test"},
        {"aud": "different-audience"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"sub": ""},
        {"sub": 42},
        {"iat": None},
    ],
)
async def test_invalid_claims_are_rejected(
    overrides: dict[str, object], key_pair: tuple[Any, dict[str, object]]
) -> None:
    private_key, public_jwk = key_pair
    with pytest.raises(AuthenticationError, match="validation failed"):
        await verifier({"keys": [public_jwk]}).verify(token(private_key, **overrides))


@pytest.mark.anyio
async def test_http_jwks_provider_accepts_only_bounded_json_documents() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "application/json"
        return httpx.Response(200, json={"keys": []})

    provider = HttpJwksProvider(
        "https://identity.example.test/jwks", transport=httpx.MockTransport(handler)
    )
    assert await provider.load() == {"keys": []}

    for response in (
        httpx.Response(302, headers={"Location": "https://evil.example.test"}),
        httpx.Response(200, content=b"x" * 1025),
        httpx.Response(200, json=[]),
        httpx.Response(200, content=b"not-json"),
    ):
        bounded = HttpJwksProvider(
            "https://identity.example.test/jwks",
            max_response_bytes=1024,
            transport=httpx.MockTransport(lambda _, value=response: value),
        )
        with pytest.raises(AuthenticationError):
            await bounded.load()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"url": "http://identity.example.test/jwks"},
        {"url": "https://user:pass@identity.example.test/jwks"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 31},
        {"max_response_bytes": 100},
        {"max_response_bytes": 1_048_577},
    ],
)
def test_http_jwks_settings_are_bounded(kwargs: dict[str, object]) -> None:
    url = str(kwargs.pop("url", "https://identity.example.test/jwks"))
    with pytest.raises(ValueError):
        HttpJwksProvider(url, **kwargs)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_http_code_client_sends_pkce_and_returns_only_bounded_id_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "grant_type=authorization_code" in body
        assert "code_verifier=" + "v" * 43 in body
        assert "client_secret=" + "s" * 32 in body
        return httpx.Response(200, json={"id_token": "signed-id-token"})

    client = HttpOidcCodeClient(
        "https://identity.example.test/token",
        client_id="agentops",
        client_secret="s" * 32,
        redirect_uri="https://console.example.test/auth/callback",
        transport=httpx.MockTransport(handler),
    )
    assert await client.exchange(code="c" * 32, code_verifier="v" * 43) == "signed-id-token"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": "invalid_grant"}),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"id_token": ""}),
        httpx.Response(200, json=[]),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, content=b"x" * 1025),
    ],
)
async def test_http_code_client_rejects_invalid_responses(response: httpx.Response) -> None:
    client = HttpOidcCodeClient(
        "https://identity.example.test/token",
        client_id="agentops",
        redirect_uri="https://console.example.test/auth/callback",
        max_response_bytes=1024,
        transport=httpx.MockTransport(lambda _: response),
    )
    with pytest.raises(AuthenticationError):
        await client.exchange(code="c" * 32, code_verifier="v" * 43)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"token_endpoint": "http://identity.example.test/token"},
        {"redirect_uri": "http://console.example.test/callback"},
        {"client_id": ""},
        {"client_secret": "short"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 31},
        {"max_response_bytes": 100},
        {"max_response_bytes": 1_048_577},
    ],
)
def test_http_code_client_settings_are_bounded(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "token_endpoint": "https://identity.example.test/token",
        "client_id": "agentops",
        "redirect_uri": "https://console.example.test/auth/callback",
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        HttpOidcCodeClient(**values)  # type: ignore[arg-type]
