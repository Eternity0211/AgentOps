"""Bounded, observable PostgreSQL and Redis clients for the simulator."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import asyncpg  # type: ignore[import-untyped]
import redis.asyncio as redis_asyncio
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer
from redis.exceptions import RedisError

from agentops_incident_commander.simulator.models import CheckoutRequest

logger = logging.getLogger("agentops.simulator.dependencies")


class DependencyUnavailable(RuntimeError):
    """A bounded dependency operation could not complete."""


class InventoryInsufficient(RuntimeError):
    """The atomic inventory reservation could not satisfy all line items."""


@dataclass(frozen=True, slots=True)
class ReservationOutcome:
    """Result of an idempotent inventory reservation."""

    reservation_id: str
    created: bool


class OrderStore(Protocol):
    """Persistence boundary used by the Order service."""

    async def ready(self, correlation_id: str) -> None: ...

    async def save(self, checkout: CheckoutRequest, correlation_id: str) -> bool: ...

    async def close(self) -> None: ...


class InventoryStore(Protocol):
    """Atomic stock boundary used by the Inventory service."""

    async def ready(self, correlation_id: str) -> None: ...

    async def reserve(
        self, checkout: CheckoutRequest, correlation_id: str
    ) -> ReservationOutcome: ...

    async def close(self) -> None: ...


class PgConnection(Protocol):
    """Subset of asyncpg connection behavior used by the adapter."""

    async def execute(self, query: str, *args: object) -> str: ...

    async def fetchval(self, query: str, *args: object) -> object: ...


class PgPool(Protocol):
    """Subset of asyncpg pool behavior used by the adapter."""

    def acquire(self) -> AbstractAsyncContextManager[PgConnection]: ...

    async def close(self) -> None: ...


class RedisClient(Protocol):
    """Subset of redis-py behavior used by the adapter."""

    async def ping(self) -> bool: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...

    async def aclose(self) -> None: ...


def _read_secret(path: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise DependencyUnavailable("dependency credential file is unavailable") from error
    if not value or len(value) > 4096:
        raise DependencyUnavailable("dependency credential file is invalid")
    return value


async def _observe[ResultT](
    dependency: str,
    operation: str,
    correlation_id: str,
    action: Awaitable[ResultT],
    tracer: Tracer | None = None,
) -> ResultT:
    started_at = time.monotonic()
    result = "ok"
    selected_tracer = tracer or trace.get_tracer(__name__)
    try:
        with selected_tracer.start_as_current_span(
            f"{dependency}.{operation}",
            kind=SpanKind.CLIENT,
            attributes={
                "db.system.name": dependency,
                "db.operation.name": operation,
                "agentops.correlation_id": correlation_id,
            },
        ) as span:
            try:
                return await action
            except Exception:
                result = "error"
                span.set_status(Status(StatusCode.ERROR))
                raise
    finally:
        logger.info(
            json.dumps(
                {
                    "event": "dependency_operation",
                    "dependency": dependency,
                    "operation": operation,
                    "result": result,
                    "duration_ms": round((time.monotonic() - started_at) * 1000, 3),
                    "correlation_id": correlation_id,
                },
                sort_keys=True,
            )
        )


class PostgresOrderStore:
    """Idempotent Order persistence backed by a bounded asyncpg pool."""

    _schema = """
        CREATE TABLE IF NOT EXISTS simulator_orders (
            order_id text PRIMARY KEY,
            items jsonb NOT NULL,
            amount_minor bigint NOT NULL CHECK (amount_minor > 0),
            currency character(3) NOT NULL,
            correlation_id text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """

    def __init__(
        self,
        environment: Mapping[str, str] | None = None,
        *,
        tracer: Tracer | None = None,
    ) -> None:
        source = os.environ if environment is None else environment
        self._host = source.get("SIMULATOR_DB_HOST", "simulator-postgres")
        self._port = int(source.get("SIMULATOR_DB_PORT", "5432"))
        self._database = source.get("SIMULATOR_DB_NAME", "commerce")
        self._user = source.get("SIMULATOR_DB_USER", "simulator")
        self._password_file = source.get(
            "SIMULATOR_DB_PASSWORD_FILE", "/run/secrets/simulator_db_password"
        )
        self._timeout = float(source.get("DEPENDENCY_TIMEOUT_SECONDS", "2"))
        self._pool: PgPool | None = None
        self._pool_lock = asyncio.Lock()
        self._tracer = tracer

    async def _get_pool(self) -> PgPool:
        if self._pool is None:
            async with self._pool_lock:
                if self._pool is None:
                    password = _read_secret(self._password_file)
                    try:
                        pool = await asyncio.wait_for(
                            asyncpg.create_pool(
                                host=self._host,
                                port=self._port,
                                database=self._database,
                                user=self._user,
                                password=password,
                                min_size=1,
                                max_size=5,
                                command_timeout=self._timeout,
                            ),
                            timeout=self._timeout,
                        )
                    except (asyncpg.PostgresError, OSError, TimeoutError) as error:
                        raise DependencyUnavailable("postgres connection failed") from error
                    self._pool = cast(PgPool, pool)
        return self._pool

    async def _with_connection[ResultT](
        self, operation: Callable[[PgConnection], Awaitable[ResultT]]
    ) -> ResultT:
        pool = await self._get_pool()
        try:
            async with pool.acquire() as connection:
                return cast(
                    ResultT,
                    await asyncio.wait_for(operation(connection), timeout=self._timeout),
                )
        except (asyncpg.PostgresError, OSError, TimeoutError) as error:
            raise DependencyUnavailable("postgres operation failed") from error

    async def ready(self, correlation_id: str) -> None:
        async def action() -> None:
            async def query(connection: PgConnection) -> None:
                await connection.fetchval("SELECT 1")

            await self._with_connection(query)

        await _observe("postgres", "ready", correlation_id, action(), self._tracer)

    async def save(self, checkout: CheckoutRequest, correlation_id: str) -> bool:
        async def action() -> bool:
            async def query(connection: PgConnection) -> bool:
                await connection.execute(self._schema)
                inserted = await connection.fetchval(
                    """
                    INSERT INTO simulator_orders
                        (order_id, items, amount_minor, currency, correlation_id)
                    VALUES ($1, $2::jsonb, $3, $4, $5)
                    ON CONFLICT (order_id) DO NOTHING
                    RETURNING order_id
                    """,
                    checkout.order_id,
                    json.dumps([item.model_dump() for item in checkout.items]),
                    checkout.amount_minor,
                    checkout.currency,
                    correlation_id,
                )
                return inserted is not None

            return await self._with_connection(query)

        return await _observe("postgres", "save_order", correlation_id, action(), self._tracer)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


RESERVE_SCRIPT = """
local reservation = KEYS[1]
if redis.call('EXISTS', reservation) == 1 then return 2 end
for i = 2, #KEYS do
  redis.call('SETNX', KEYS[i], 100)
  local requested = tonumber(ARGV[i - 1])
  if tonumber(redis.call('GET', KEYS[i])) < requested then return 0 end
end
for i = 2, #KEYS do
  redis.call('DECRBY', KEYS[i], tonumber(ARGV[i - 1]))
end
redis.call('SET', reservation, ARGV[#ARGV], 'EX', 3600)
return 1
"""


class RedisInventoryStore:
    """Atomic, idempotent Inventory reservation backed by Redis Lua."""

    def __init__(
        self,
        environment: Mapping[str, str] | None = None,
        *,
        client: RedisClient | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        source = os.environ if environment is None else environment
        timeout = float(source.get("DEPENDENCY_TIMEOUT_SECONDS", "2"))
        if client is None:
            password = _read_secret(
                source.get(
                    "SIMULATOR_REDIS_PASSWORD_FILE",
                    "/run/secrets/simulator_redis_password",
                )
            )
            client = cast(
                RedisClient,
                redis_asyncio.Redis(
                    host=source.get("SIMULATOR_REDIS_HOST", "simulator-redis"),
                    port=int(source.get("SIMULATOR_REDIS_PORT", "6379")),
                    password=password,
                    socket_connect_timeout=timeout,
                    socket_timeout=timeout,
                    decode_responses=True,
                ),
            )
        self._client = client
        self._timeout = timeout
        self._tracer = tracer

    async def _bounded[ResultT](self, action: Awaitable[ResultT]) -> ResultT:
        try:
            return cast(ResultT, await asyncio.wait_for(action, timeout=self._timeout))
        except (RedisError, OSError, TimeoutError) as error:
            raise DependencyUnavailable("redis operation failed") from error

    async def ready(self, correlation_id: str) -> None:
        await _observe(
            "redis",
            "ready",
            correlation_id,
            self._bounded(self._client.ping()),
            self._tracer,
        )

    async def reserve(self, checkout: CheckoutRequest, correlation_id: str) -> ReservationOutcome:
        async def action() -> ReservationOutcome:
            reservation_id = f"res-{checkout.order_id}"
            keys = [f"reservation:{checkout.order_id}"]
            keys.extend(f"stock:{item.sku}" for item in checkout.items)
            quantities: Sequence[object] = [item.quantity for item in checkout.items]
            result = await self._bounded(
                self._client.eval(
                    RESERVE_SCRIPT,
                    len(keys),
                    *keys,
                    *quantities,
                    correlation_id,
                )
            )
            if result == 0:
                raise InventoryInsufficient("insufficient inventory")
            if result not in (1, 2):
                raise DependencyUnavailable("redis returned an invalid reservation result")
            return ReservationOutcome(reservation_id, created=result == 1)

        return await _observe("redis", "reserve_inventory", correlation_id, action(), self._tracer)

    async def close(self) -> None:
        await self._client.aclose()
