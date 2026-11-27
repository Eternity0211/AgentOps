"""Fail-closed environment contracts shared by control-plane processes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """A process cannot start from incomplete or unsafe configuration."""


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"required setting {name} is missing")
    return value


def _database_url(environment: Mapping[str, str]) -> str:
    value = _required(environment, "AGENTOPS_DATABASE_URL")
    if not value.startswith("postgresql+asyncpg://"):
        raise ConfigurationError("AGENTOPS_DATABASE_URL must use postgresql+asyncpg")
    return value


def _integer(
    environment: Mapping[str, str],
    name: str,
    default: int,
    minimum: int = 1,
    maximum: int = 65_535,
) -> int:
    raw = environment.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_float(
    environment: Mapping[str, str], name: str, default: float, minimum: float, maximum: float
) -> float:
    raw = environment.get(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(environment: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environment.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _https_url(environment: Mapping[str, str], name: str) -> str:
    value = _required(environment, name)
    parsed = urlsplit(value)
    if (
        len(value) > 2048
        or parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ConfigurationError(f"{name} must be a bounded HTTPS URL")
    return value


@dataclass(frozen=True, slots=True)
class OidcApiSettings:
    issuer: str
    audience: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_url: str
    client_id: str
    redirect_uri: str
    client_secret: str | None
    login_ttl_seconds: int
    session_ttl_seconds: int

    @classmethod
    def load_optional(cls, environment: Mapping[str, str]) -> OidcApiSettings | None:
        names = (
            "AGENTOPS_OIDC_ISSUER",
            "AGENTOPS_OIDC_AUDIENCE",
            "AGENTOPS_OIDC_AUTHORIZATION_ENDPOINT",
            "AGENTOPS_OIDC_TOKEN_ENDPOINT",
            "AGENTOPS_OIDC_JWKS_URL",
            "AGENTOPS_OIDC_CLIENT_ID",
            "AGENTOPS_OIDC_REDIRECT_URI",
        )
        if not any(environment.get(name, "").strip() for name in names):
            return None
        secret = environment.get("AGENTOPS_OIDC_CLIENT_SECRET")
        if secret is not None:
            secret = secret.strip()
            if not 16 <= len(secret) <= 4096:
                raise ConfigurationError(
                    "AGENTOPS_OIDC_CLIENT_SECRET must be between 16 and 4096 characters"
                )
        return cls(
            issuer=_https_url(environment, "AGENTOPS_OIDC_ISSUER"),
            audience=_required(environment, "AGENTOPS_OIDC_AUDIENCE"),
            authorization_endpoint=_https_url(environment, "AGENTOPS_OIDC_AUTHORIZATION_ENDPOINT"),
            token_endpoint=_https_url(environment, "AGENTOPS_OIDC_TOKEN_ENDPOINT"),
            jwks_url=_https_url(environment, "AGENTOPS_OIDC_JWKS_URL"),
            client_id=_required(environment, "AGENTOPS_OIDC_CLIENT_ID"),
            redirect_uri=_https_url(environment, "AGENTOPS_OIDC_REDIRECT_URI"),
            client_secret=secret,
            login_ttl_seconds=_integer(
                environment, "AGENTOPS_OIDC_LOGIN_TTL_SECONDS", 300, 60, 900
            ),
            session_ttl_seconds=_integer(
                environment, "AGENTOPS_SESSION_TTL_SECONDS", 28_800, 300, 86_400
            ),
        )


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Configuration owned only by the HTTP API process."""

    database_url: str
    host: str
    port: int
    oidc: OidcApiSettings | None = None

    @classmethod
    def load(cls, environment: Mapping[str, str]) -> ApiSettings:
        return cls(
            database_url=_database_url(environment),
            host=environment.get("AGENTOPS_API_HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=_integer(environment, "AGENTOPS_API_PORT", 8000),
            oidc=OidcApiSettings.load_optional(environment),
        )


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    """Configuration owned only by the background worker process."""

    database_url: str
    worker_id: str
    poll_interval_seconds: float
    max_concurrency: int = 4
    shutdown_grace_seconds: float = 30.0
    recovery_mutation_enabled: bool = False
    recovery_dispatch_timeout_seconds: float = 30.0

    @classmethod
    def load(cls, environment: Mapping[str, str]) -> WorkerSettings:
        return cls(
            database_url=_database_url(environment),
            worker_id=_required(environment, "AGENTOPS_WORKER_ID"),
            poll_interval_seconds=_bounded_float(
                environment, "AGENTOPS_WORKER_POLL_SECONDS", 1, 0.05, 60
            ),
            max_concurrency=_integer(environment, "AGENTOPS_WORKER_CONCURRENCY", 4, maximum=64),
            shutdown_grace_seconds=_bounded_float(
                environment, "AGENTOPS_WORKER_SHUTDOWN_GRACE_SECONDS", 30, 0.1, 300
            ),
            recovery_mutation_enabled=_boolean(
                environment, "AGENTOPS_RECOVERY_MUTATION_ENABLED", False
            ),
            recovery_dispatch_timeout_seconds=_bounded_float(
                environment,
                "AGENTOPS_RECOVERY_DISPATCH_TIMEOUT_SECONDS",
                30,
                0.1,
                300,
            ),
        )
