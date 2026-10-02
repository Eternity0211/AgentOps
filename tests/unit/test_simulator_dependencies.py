"""Unit tests for bounded simulator PostgreSQL and Redis adapters."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import pytest
from redis.exceptions import RedisError

from agentops_incident_commander.simulator import dependencies
from agentops_incident_commander.simulator.models import CheckoutRequest


@pytest.fixture
def anyio_backend() -> str:
    """Run async adapter tests on asyncio."""
    return "asyncio"


@pytest.fixture
def checkout() -> CheckoutRequest:
    """Return a valid request shared by persistence tests."""
    return CheckoutRequest.model_validate(
        {
            "order_id": "order-123",
            "items": [{"sku": "widget-1", "quantity": 2}],
            "amount_minor": 2500,
            "currency": "USD",
        }
    )


class FakeConnection:
    """Record SQL calls and return a configured insertion result."""

    def __init__(self, inserted: object = "order-123") -> None:
        self.inserted = inserted
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.failure: Exception | None = None

    async def execute(self, query: str, *args: object) -> str:
        if self.failure is not None:
            raise self.failure
        self.execute_calls.append((query, args))
        return "CREATE TABLE"

    async def fetchval(self, query: str, *args: object) -> object:
        if self.failure is not None:
            raise self.failure
        self.fetch_calls.append((query, args))
        if query == "SELECT 1":
            return 1
        return self.inserted


class FakePool:
    """Supply one connection through the asyncpg acquire shape."""

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.closed = False
        self.acquire_failure: Exception | None = None

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[FakeConnection]:
        if self.acquire_failure is not None:
            raise self.acquire_failure
        yield self.connection

    def get_size(self) -> int:
        return 1

    def get_idle_size(self) -> int:
        return 1

    async def close(self) -> None:
        self.closed = True


class BoundedFakePool:
    """Model a five-slot asyncpg pool closely enough to prove saturation and release."""

    def __init__(
        self,
        *,
        fail_after: int | None = None,
        pause_first: bool = False,
        fail_release: bool = False,
    ) -> None:
        self.connection = FakeConnection()
        self.capacity = 5
        self._semaphore = asyncio.Semaphore(self.capacity)
        self.fail_after = fail_after
        self.pause_first = pause_first
        self.fail_release = fail_release
        self.first_started = asyncio.Event()
        self.first_release = asyncio.Event()
        self.entered = 0
        self.active = 0
        self.closed = False

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[FakeConnection]:
        if self.fail_after is not None and self.entered >= self.fail_after:
            raise OSError("acquire failed")
        self.entered += 1
        if self.pause_first and self.entered == 1:
            self.first_started.set()
            await self.first_release.wait()
        await self._semaphore.acquire()
        self.active += 1
        try:
            yield self.connection
        finally:
            self.active -= 1
            self._semaphore.release()
            if self.fail_release:
                raise OSError("release failed")

    def get_size(self) -> int:
        return self.capacity

    def get_idle_size(self) -> int:
        return self.capacity - self.active

    async def close(self) -> None:
        self.closed = True


class FakeRedis:
    """Record Redis calls and return configurable Lua outcomes."""

    def __init__(self, result: object = 1) -> None:
        self.result = result
        self.closed = False
        self.failure: Exception | None = None
        self.eval_calls: list[tuple[str, int, tuple[object, ...]]] = []

    async def ping(self) -> bool:
        if self.failure is not None:
            raise self.failure
        return True

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        if self.failure is not None:
            raise self.failure
        self.eval_calls.append((script, numkeys, keys_and_args))
        return self.result

    async def aclose(self) -> None:
        self.closed = True


def test_secret_reader_accepts_trimmed_value(tmp_path: Path) -> None:
    """Credential files are read locally and surrounding line endings are ignored."""
    secret = tmp_path / "password.txt"
    secret.write_text("correct-horse\n", encoding="utf-8")

    assert dependencies._read_secret(str(secret)) == "correct-horse"


@pytest.mark.parametrize("value", [None, "", "x" * 4097])
def test_secret_reader_rejects_missing_or_invalid_value(tmp_path: Path, value: str | None) -> None:
    """Missing, empty, and unreasonably large credentials fail closed."""
    secret = tmp_path / "password.txt"
    if value is not None:
        secret.write_text(value, encoding="utf-8")

    with pytest.raises(dependencies.DependencyUnavailable, match="credential file"):
        dependencies._read_secret(str(secret))


@pytest.mark.anyio
async def test_postgres_save_is_idempotent_and_observable(
    checkout: CheckoutRequest,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Order writes use ON CONFLICT and emit metadata without request payloads."""
    connection = FakeConnection()
    pool = FakePool(connection)
    store = dependencies.PostgresOrderStore({"DEPENDENCY_TIMEOUT_SECONDS": "1"})
    store._pool = pool
    caplog.set_level(logging.INFO, logger="agentops.simulator.dependencies")

    assert await store.save(checkout, "corr-db") is True
    connection.inserted = None
    assert await store.save(checkout, "corr-db") is False

    insert_query, insert_args = connection.fetch_calls[-1]
    assert "ON CONFLICT (order_id) DO NOTHING" in insert_query
    assert insert_args == (
        "order-123",
        '[{"sku": "widget-1", "quantity": 2}]',
        2500,
        "USD",
        "corr-db",
    )
    event = json.loads(caplog.records[-1].message)
    assert event | {"duration_ms": 0} == {
        "event": "dependency_operation",
        "dependency": "postgres",
        "operation": "save_order",
        "result": "ok",
        "duration_ms": 0,
        "correlation_id": "corr-db",
    }
    assert "widget-1" not in caplog.text


@pytest.mark.anyio
async def test_postgres_ready_and_close() -> None:
    """Readiness probes the selected pool and shutdown releases it."""
    connection = FakeConnection()
    pool = FakePool(connection)
    store = dependencies.PostgresOrderStore({"DEPENDENCY_TIMEOUT_SECONDS": "1"})
    store._pool = pool

    await store.ready("corr-ready")
    await store.close()
    await store.close()

    assert connection.fetch_calls == [("SELECT 1", ())]
    assert pool.closed is True
    assert store._pool is None


@pytest.mark.anyio
async def test_postgres_creates_one_bounded_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent first use initializes one credentialed pool and reuses it."""
    secret = tmp_path / "db-password.txt"
    secret.write_text("db-secret", encoding="utf-8")
    pool = FakePool(FakeConnection())
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[dict[str, object]] = []

    async def create_pool(**kwargs: object) -> FakePool:
        calls.append(kwargs)
        started.set()
        await release.wait()
        return pool

    monkeypatch.setattr(
        "agentops_incident_commander.simulator.dependencies.asyncpg.create_pool", create_pool
    )
    store = dependencies.PostgresOrderStore(
        {
            "SIMULATOR_DB_HOST": "db",
            "SIMULATOR_DB_PORT": "5544",
            "SIMULATOR_DB_NAME": "shop",
            "SIMULATOR_DB_USER": "app",
            "SIMULATOR_DB_PASSWORD_FILE": str(secret),
            "DEPENDENCY_TIMEOUT_SECONDS": "1",
        }
    )

    first = asyncio.create_task(store._get_pool())
    await started.wait()
    second = asyncio.create_task(store._get_pool())
    release.set()

    assert await first is pool
    assert await second is pool
    assert len(calls) == 1
    assert calls[0]["password"] == "db-secret"
    assert calls[0]["host"] == "db"
    assert calls[0]["port"] == 5544
    assert calls[0]["min_size"] == 1
    assert calls[0]["max_size"] == 5


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [OSError("offline"), asyncpg.PostgresError("bad")])
async def test_postgres_maps_pool_creation_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """Connection setup failures collapse to the stable dependency error."""
    secret = tmp_path / "db-password.txt"
    secret.write_text("db-secret", encoding="utf-8")

    async def create_pool(**kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(
        "agentops_incident_commander.simulator.dependencies.asyncpg.create_pool", create_pool
    )
    store = dependencies.PostgresOrderStore(
        {
            "SIMULATOR_DB_PASSWORD_FILE": str(secret),
            "DEPENDENCY_TIMEOUT_SECONDS": "1",
        }
    )

    with pytest.raises(dependencies.DependencyUnavailable, match="connection failed"):
        await store._get_pool()


@pytest.mark.anyio
async def test_postgres_maps_timeout_and_operation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pool timeout and connection errors never escape the adapter boundary."""
    secret = tmp_path / "db-password.txt"
    secret.write_text("db-secret", encoding="utf-8")

    async def slow_pool(**kwargs: object) -> None:
        await asyncio.sleep(1)

    monkeypatch.setattr(
        "agentops_incident_commander.simulator.dependencies.asyncpg.create_pool", slow_pool
    )
    store = dependencies.PostgresOrderStore(
        {
            "SIMULATOR_DB_PASSWORD_FILE": str(secret),
            "DEPENDENCY_TIMEOUT_SECONDS": "0.001",
        }
    )
    with pytest.raises(dependencies.DependencyUnavailable, match="connection failed"):
        await store._get_pool()

    pool = FakePool(FakeConnection())
    pool.acquire_failure = OSError("lost")
    store._pool = pool
    with pytest.raises(dependencies.DependencyUnavailable, match="operation failed"):
        await store.ready("corr-fail")


@pytest.mark.anyio
async def test_postgres_pool_exhaustion_is_bounded_observable_and_released(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fault holds exactly five slots, times out acquisition, and releases on close."""
    pool = BoundedFakePool()
    store = dependencies.PostgresOrderStore(
        {"DEPENDENCY_TIMEOUT_SECONDS": "0.001"}, exhaust_pool=True
    )
    store._pool = pool
    caplog.set_level(logging.INFO, logger="agentops.simulator.dependencies")

    with pytest.raises(dependencies.DependencyUnavailable, match="operation failed"):
        await store.ready("corr-exhausted")

    assert pool.active == pool.get_size() == 5
    assert pool.get_idle_size() == 0
    pool_event = next(
        json.loads(record.message)
        for record in caplog.records
        if "dependency_pool_acquire_timeout" in record.message
    )
    assert pool_event == {
        "dependency": "postgres",
        "event": "dependency_pool_acquire_timeout",
        "pool_idle": 0,
        "pool_size": 5,
    }
    assert "db-pool-exhaustion" not in caplog.text

    await store.close()
    assert pool.active == 0
    assert pool.closed is True


@pytest.mark.anyio
async def test_postgres_pool_exhaustion_activation_is_single_and_repeatable() -> None:
    """Concurrent probes share one fixed set of held connections without growth."""
    pool = BoundedFakePool()
    store = dependencies.PostgresOrderStore(
        {"DEPENDENCY_TIMEOUT_SECONDS": "0.001"}, exhaust_pool=True
    )
    store._pool = pool

    results = await asyncio.gather(
        store.ready("corr-one"), store.ready("corr-two"), return_exceptions=True
    )

    assert all(isinstance(result, dependencies.DependencyUnavailable) for result in results)
    assert pool.active == 5
    assert pool.entered == 7
    await store.close()


@pytest.mark.anyio
async def test_postgres_pool_exhaustion_serializes_first_activation() -> None:
    """A second initializer rechecks state after waiting for the activation lock."""
    pool = BoundedFakePool(pause_first=True)
    store = dependencies.PostgresOrderStore({"DEPENDENCY_TIMEOUT_SECONDS": "1"}, exhaust_pool=True)
    store._pool = pool

    first = asyncio.create_task(store._activate_pool_exhaustion(pool))
    await pool.first_started.wait()
    second = asyncio.create_task(store._activate_pool_exhaustion(pool))
    pool.first_release.set()
    await asyncio.gather(first, second)

    assert pool.entered == pool.active == 5
    await store.close()


@pytest.mark.anyio
async def test_postgres_pool_exhaustion_partial_activation_releases_slots() -> None:
    """A driver failure while filling the pool cannot leak the slots already acquired."""
    pool = BoundedFakePool(fail_after=2)
    store = dependencies.PostgresOrderStore({"DEPENDENCY_TIMEOUT_SECONDS": "1"}, exhaust_pool=True)
    store._pool = pool

    with pytest.raises(dependencies.DependencyUnavailable, match="saturation failed"):
        await store.ready("corr-partial")

    assert pool.active == 0
    await store.close()


@pytest.mark.anyio
async def test_postgres_pool_release_attempts_every_holder_before_failing() -> None:
    """Driver release errors are reported only after every held slot is attempted."""
    pool = BoundedFakePool(fail_release=True)
    store = dependencies.PostgresOrderStore({"DEPENDENCY_TIMEOUT_SECONDS": "1"}, exhaust_pool=True)
    store._pool = pool
    await store._activate_pool_exhaustion(pool)

    with pytest.raises(dependencies.DependencyUnavailable, match="pool release failed"):
        await store.close()

    assert pool.active == 0
    assert pool.closed is True
    assert store._pool is None


@pytest.mark.anyio
async def test_redis_ready_reserve_duplicate_and_close(checkout: CheckoutRequest) -> None:
    """Redis exposes readiness and maps both Lua success outcomes."""
    client = FakeRedis(1)
    store = dependencies.RedisInventoryStore({"DEPENDENCY_TIMEOUT_SECONDS": "1"}, client=client)

    await store.ready("corr-redis")
    created = await store.reserve(checkout, "corr-redis")
    client.result = 2
    duplicate = await store.reserve(checkout, "corr-redis")
    await store.close()

    assert created == dependencies.ReservationOutcome("res-order-123", created=True)
    assert duplicate == dependencies.ReservationOutcome("res-order-123", created=False)
    script, key_count, arguments = client.eval_calls[0]
    assert script == dependencies.RESERVE_SCRIPT
    assert key_count == 2
    assert arguments == ("reservation:order-123", "stock:widget-1", 2, "corr-redis")
    assert client.closed is True


def test_redis_script_prechecks_all_stock_before_decrement() -> None:
    """The atomic Lua script cannot partially decrement before rejecting low stock."""
    insufficient = dependencies.RESERVE_SCRIPT.index("then return 0")
    decrement = dependencies.RESERVE_SCRIPT.index("DECRBY")

    assert insufficient < decrement


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("result", "exception", "message"),
    [
        (0, dependencies.InventoryInsufficient, "insufficient inventory"),
        (9, dependencies.DependencyUnavailable, "invalid reservation result"),
    ],
)
async def test_redis_maps_unsuccessful_lua_results(
    checkout: CheckoutRequest,
    result: int,
    exception: type[Exception],
    message: str,
) -> None:
    """Insufficient stock and invalid server results are distinct failures."""
    store = dependencies.RedisInventoryStore(client=FakeRedis(result))

    with pytest.raises(exception, match=message):
        await store.reserve(checkout, "corr-redis")


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [RedisError("offline"), OSError("closed")])
async def test_redis_maps_client_failures_and_logs_error(
    failure: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Redis transport failures are bounded and observed without leaking details."""
    client = FakeRedis()
    client.failure = failure
    store = dependencies.RedisInventoryStore(client=client)
    caplog.set_level(logging.INFO, logger="agentops.simulator.dependencies")

    with pytest.raises(dependencies.DependencyUnavailable, match="redis operation failed"):
        await store.ready("corr-error")

    event = json.loads(caplog.records[-1].message)
    assert event["result"] == "error"
    assert event["correlation_id"] == "corr-error"
    assert "offline" not in caplog.text


@pytest.mark.anyio
async def test_redis_maps_timeout() -> None:
    """A hung Redis operation stops at the configured adapter deadline."""

    class SlowRedis(FakeRedis):
        async def ping(self) -> bool:
            await asyncio.sleep(1)
            return True

    store = dependencies.RedisInventoryStore(
        {"DEPENDENCY_TIMEOUT_SECONDS": "0.001"}, client=SlowRedis()
    )

    with pytest.raises(dependencies.DependencyUnavailable, match="redis operation failed"):
        await store.ready("corr-timeout")


def test_redis_default_client_uses_secret_and_bounded_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production composition creates Redis from secret-file credentials."""
    secret = tmp_path / "redis-password.txt"
    secret.write_text("redis-secret", encoding="utf-8")
    captured: dict[str, Any] = {}
    client = FakeRedis()

    def create_client(**kwargs: object) -> FakeRedis:
        captured.update(kwargs)
        return client

    monkeypatch.setattr(
        "agentops_incident_commander.simulator.dependencies.redis_asyncio.Redis", create_client
    )

    store = dependencies.RedisInventoryStore(
        {
            "SIMULATOR_REDIS_HOST": "cache",
            "SIMULATOR_REDIS_PORT": "6380",
            "SIMULATOR_REDIS_PASSWORD_FILE": str(secret),
            "DEPENDENCY_TIMEOUT_SECONDS": "3",
        }
    )

    assert store._client is client
    assert captured == {
        "host": "cache",
        "port": 6380,
        "password": "redis-secret",
        "socket_connect_timeout": 3.0,
        "socket_timeout": 3.0,
        "decode_responses": True,
    }
