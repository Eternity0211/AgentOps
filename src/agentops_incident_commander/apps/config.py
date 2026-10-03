"""Fail-closed environment contracts shared by control-plane processes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


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


def _integer(environment: Mapping[str, str], name: str, default: int) -> int:
    raw = environment.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not 1 <= value <= 65_535:
        raise ConfigurationError(f"{name} must be between 1 and 65535")
    return value


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Configuration owned only by the HTTP API process."""

    database_url: str
    host: str
    port: int

    @classmethod
    def load(cls, environment: Mapping[str, str]) -> ApiSettings:
        return cls(
            database_url=_database_url(environment),
            host=environment.get("AGENTOPS_API_HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=_integer(environment, "AGENTOPS_API_PORT", 8000),
        )


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    """Configuration owned only by the background worker process."""

    database_url: str
    worker_id: str
    poll_interval_seconds: float

    @classmethod
    def load(cls, environment: Mapping[str, str]) -> WorkerSettings:
        raw_interval = environment.get("AGENTOPS_WORKER_POLL_SECONDS", "1")
        try:
            interval = float(raw_interval)
        except ValueError as exc:
            raise ConfigurationError("AGENTOPS_WORKER_POLL_SECONDS must be numeric") from exc
        if not 0.05 <= interval <= 60:
            raise ConfigurationError("AGENTOPS_WORKER_POLL_SECONDS must be between 0.05 and 60")
        return cls(
            database_url=_database_url(environment),
            worker_id=_required(environment, "AGENTOPS_WORKER_ID"),
            poll_interval_seconds=interval,
        )
