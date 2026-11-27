"""Bounded OIDC ID/access-token verification without application-role trust."""

from __future__ import annotations

import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK, PyJWTError

from agentops_incident_commander.domain import AuthenticationError, FederatedIdentity

_SUPPORTED_ALGORITHMS = frozenset({"RS256", "ES256"})


class JwksProvider(Protocol):
    async def load(self) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class OidcVerifierSettings:
    issuer: str
    audience: str
    algorithms: tuple[str, ...] = ("RS256",)
    leeway_seconds: int = 30
    max_token_bytes: int = 16_384

    def __post_init__(self) -> None:
        try:
            parsed = urlsplit(self.issuer)
        except (AttributeError, ValueError) as exc:
            raise ValueError("OIDC issuer must be a bounded HTTPS issuer URL") from exc
        if (
            len(self.issuer) > 2048
            or parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OIDC issuer must be a bounded HTTPS issuer URL")
        if not self.audience or len(self.audience) > 255 or self.audience.strip() != self.audience:
            raise ValueError("OIDC audience must be between 1 and 255 characters")
        if not self.algorithms or not set(self.algorithms) <= _SUPPORTED_ALGORITHMS:
            raise ValueError("OIDC algorithms must be an explicit supported asymmetric allowlist")
        if len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("OIDC algorithms cannot contain duplicates")
        if not 0 <= self.leeway_seconds <= 300:
            raise ValueError("OIDC leeway must be between 0 and 300 seconds")
        if not 1024 <= self.max_token_bytes <= 65_536:
            raise ValueError("OIDC token bound must be between 1024 and 65536 bytes")


class OidcTokenVerifier:
    """Verify asymmetric signature and mandatory OIDC claims, then return identity only."""

    def __init__(self, settings: OidcVerifierSettings, jwks: JwksProvider) -> None:
        self._settings = settings
        self._jwks = jwks

    async def verify(self, token: str, *, expected_nonce: str | None = None) -> FederatedIdentity:
        if not token or len(token.encode("utf-8")) > self._settings.max_token_bytes:
            raise AuthenticationError("OIDC token is absent or exceeds the size limit")
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise AuthenticationError("OIDC token header is invalid") from exc
        algorithm = header.get("alg")
        key_id = header.get("kid")
        if algorithm not in self._settings.algorithms or not isinstance(key_id, str) or not key_id:
            raise AuthenticationError("OIDC token algorithm or key identifier is not allowed")

        document = await self._jwks.load()
        keys = document.get("keys")
        if not isinstance(keys, Sequence) or isinstance(keys, (str, bytes)):
            raise AuthenticationError("OIDC JWKS document is invalid")
        matches = [
            item
            for item in keys
            if isinstance(item, Mapping)
            and item.get("kid") == key_id
            and item.get("alg") == algorithm
            and item.get("use", "sig") == "sig"
        ]
        if len(matches) != 1:
            raise AuthenticationError("OIDC signing key is absent or ambiguous")
        try:
            signing_key = PyJWK.from_dict(dict(matches[0]), algorithm=cast(str, algorithm)).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=list(self._settings.algorithms),
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                leeway=self._settings.leeway_seconds,
                options={"require": ["iss", "sub", "aud", "exp", "iat"]},
            )
            if expected_nonce is not None:
                nonce = claims.get("nonce")
                if not isinstance(nonce, str) or not hmac.compare_digest(nonce, expected_nonce):
                    raise AuthenticationError("OIDC token nonce validation failed")
            return FederatedIdentity(issuer=claims["iss"], subject=claims["sub"])
        except AuthenticationError:
            raise
        except (PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("OIDC token validation failed") from exc


class HttpJwksProvider:
    """Fetch one bounded JWKS document over HTTPS with no redirect following."""

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 65_536,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("JWKS URL must be HTTPS without user information")
        if not 0.1 <= timeout_seconds <= 30:
            raise ValueError("JWKS timeout must be between 0.1 and 30 seconds")
        if not 1024 <= max_response_bytes <= 1_048_576:
            raise ValueError("JWKS response bound must be between 1024 and 1048576 bytes")
        self._url = url
        self._timeout = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    async def load(self) -> Mapping[str, object]:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, transport=self._transport
            ) as client:
                response = await client.get(self._url, headers={"Accept": "application/json"})
            if response.status_code != 200 or len(response.content) > self._max_response_bytes:
                raise AuthenticationError("OIDC JWKS endpoint returned an invalid response")
            value = response.json()
            if not isinstance(value, Mapping):
                raise AuthenticationError("OIDC JWKS endpoint returned an invalid document")
            return cast(Mapping[str, object], value)
        except AuthenticationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthenticationError("OIDC JWKS endpoint is unavailable") from exc


class HttpOidcCodeClient:
    """Exchange one PKCE authorization code for a bounded ID token response."""

    def __init__(
        self,
        token_endpoint: str,
        *,
        client_id: str,
        redirect_uri: str,
        client_secret: str | None = None,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 65_536,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        for value in (token_endpoint, redirect_uri):
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError("OIDC token endpoint and redirect URI must be HTTPS")
        if not client_id or len(client_id) > 255:
            raise ValueError("OIDC client ID is invalid")
        if client_secret is not None and not 16 <= len(client_secret) <= 4096:
            raise ValueError("OIDC client secret is invalid")
        if not 0.1 <= timeout_seconds <= 30:
            raise ValueError("OIDC token timeout must be between 0.1 and 30 seconds")
        if not 1024 <= max_response_bytes <= 1_048_576:
            raise ValueError("OIDC token response bound must be between 1024 and 1048576 bytes")
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._timeout = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    async def exchange(self, *, code: str, code_verifier: str) -> str:
        data = {
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        }
        if self._client_secret is not None:
            data["client_secret"] = self._client_secret
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, transport=self._transport
            ) as client:
                response = await client.post(
                    self._token_endpoint,
                    data=data,
                    headers={"Accept": "application/json"},
                )
            if response.status_code != 200 or len(response.content) > self._max_response_bytes:
                raise AuthenticationError("OIDC token exchange was rejected")
            value = response.json()
            token = value.get("id_token") if isinstance(value, Mapping) else None
            if not isinstance(token, str) or not token or len(token) > 65_536:
                raise AuthenticationError("OIDC token exchange omitted a bounded ID token")
            return token
        except AuthenticationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthenticationError("OIDC token endpoint is unavailable") from exc
