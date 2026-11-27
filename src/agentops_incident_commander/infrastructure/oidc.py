"""Bounded OIDC ID/access-token verification without application-role trust."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit

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

    async def verify(self, token: str) -> FederatedIdentity:
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
            return FederatedIdentity(issuer=claims["iss"], subject=claims["sub"])
        except (PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("OIDC token validation failed") from exc
