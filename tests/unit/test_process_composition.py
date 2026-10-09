"""Tests proving API and worker are independent fail-closed processes."""

from __future__ import annotations

import asyncio
import inspect
import signal
from collections.abc import Coroutine
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentops_incident_commander.apps import api, config, worker

DATABASE_URL = "postgresql+asyncpg://agentops:local-only@postgres/agentops"


def test_api_settings_load_defaults_and_overrides() -> None:
    defaults = config.ApiSettings.load({"AGENTOPS_DATABASE_URL": DATABASE_URL})
    overridden = config.ApiSettings.load(
        {
            "AGENTOPS_DATABASE_URL": DATABASE_URL,
            "AGENTOPS_API_HOST": "127.0.0.1",
            "AGENTOPS_API_PORT": "8081",
        }
    )

    assert (defaults.host, defaults.port) == ("0.0.0.0", 8000)
    assert (overridden.host, overridden.port) == ("127.0.0.1", 8081)


def test_worker_settings_load_typed_values() -> None:
    settings = config.WorkerSettings.load(
        {
            "AGENTOPS_DATABASE_URL": DATABASE_URL,
            "AGENTOPS_WORKER_ID": "worker-1",
            "AGENTOPS_WORKER_POLL_SECONDS": "0.25",
            "AGENTOPS_RECOVERY_MUTATION_ENABLED": "true",
            "AGENTOPS_RECOVERY_DISPATCH_TIMEOUT_SECONDS": "12.5",
        }
    )

    assert settings.worker_id == "worker-1"
    assert settings.poll_interval_seconds == 0.25
    assert settings.max_concurrency == 4
    assert settings.shutdown_grace_seconds == 30
    assert settings.recovery_mutation_enabled is True
    assert settings.recovery_dispatch_timeout_seconds == 12.5


def test_worker_recovery_mutation_defaults_disabled() -> None:
    settings = config.WorkerSettings.load(
        {"AGENTOPS_DATABASE_URL": DATABASE_URL, "AGENTOPS_WORKER_ID": "worker-1"}
    )
    explicit = config.WorkerSettings.load(
        {
            "AGENTOPS_DATABASE_URL": DATABASE_URL,
            "AGENTOPS_WORKER_ID": "worker-1",
            "AGENTOPS_RECOVERY_MUTATION_ENABLED": "false",
        }
    )

    assert settings.recovery_mutation_enabled is False
    assert explicit.recovery_mutation_enabled is False
    assert settings.recovery_dispatch_timeout_seconds == 30


@pytest.mark.parametrize(
    ("loader", "environment", "message"),
    [
        (config.ApiSettings.load, {}, "AGENTOPS_DATABASE_URL is missing"),
        (
            config.ApiSettings.load,
            {"AGENTOPS_DATABASE_URL": "postgresql://unsafe"},
            r"must use postgresql\+asyncpg",
        ),
        (
            config.ApiSettings.load,
            {"AGENTOPS_DATABASE_URL": DATABASE_URL, "AGENTOPS_API_PORT": "nope"},
            "must be an integer",
        ),
        (
            config.ApiSettings.load,
            {"AGENTOPS_DATABASE_URL": DATABASE_URL, "AGENTOPS_API_PORT": "0"},
            "between 1 and 65535",
        ),
        (
            config.WorkerSettings.load,
            {"AGENTOPS_DATABASE_URL": DATABASE_URL},
            "AGENTOPS_WORKER_ID is missing",
        ),
        (
            config.WorkerSettings.load,
            {
                "AGENTOPS_DATABASE_URL": DATABASE_URL,
                "AGENTOPS_WORKER_ID": "worker-1",
                "AGENTOPS_WORKER_POLL_SECONDS": "never",
            },
            "must be numeric",
        ),
        (
            config.WorkerSettings.load,
            {
                "AGENTOPS_DATABASE_URL": DATABASE_URL,
                "AGENTOPS_WORKER_ID": "worker-1",
                "AGENTOPS_WORKER_POLL_SECONDS": "61",
            },
            "between 0.05 and 60",
        ),
        (
            config.WorkerSettings.load,
            {
                "AGENTOPS_DATABASE_URL": DATABASE_URL,
                "AGENTOPS_WORKER_ID": "worker-1",
                "AGENTOPS_WORKER_CONCURRENCY": "65",
            },
            "between 1 and 64",
        ),
        (
            config.WorkerSettings.load,
            {
                "AGENTOPS_DATABASE_URL": DATABASE_URL,
                "AGENTOPS_WORKER_ID": "worker-1",
                "AGENTOPS_WORKER_SHUTDOWN_GRACE_SECONDS": "0",
            },
            "between 0.1 and 300",
        ),
        (
            config.WorkerSettings.load,
            {
                "AGENTOPS_DATABASE_URL": DATABASE_URL,
                "AGENTOPS_WORKER_ID": "worker-1",
                "AGENTOPS_RECOVERY_MUTATION_ENABLED": "yes",
            },
            "must be true or false",
        ),
        (
            config.WorkerSettings.load,
            {
                "AGENTOPS_DATABASE_URL": DATABASE_URL,
                "AGENTOPS_WORKER_ID": "worker-1",
                "AGENTOPS_RECOVERY_DISPATCH_TIMEOUT_SECONDS": "301",
            },
            "between 0.1 and 300",
        ),
    ],
)
def test_process_settings_fail_closed(
    loader: Any, environment: dict[str, str], message: str
) -> None:
    with pytest.raises(config.ConfigurationError, match=message):
        loader(environment)


def test_api_exposes_health_without_worker_routes_or_tasks() -> None:
    settings = config.ApiSettings(DATABASE_URL, "127.0.0.1", 8000)
    app = api.create_app(settings)

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.json() == {"status": "healthy", "role": "api"}
    assert app.state.process_role == "api"
    assert app.state.settings is settings
    assert all("worker" not in getattr(route, "path", "") for route in app.routes)


def test_api_main_loads_settings_and_runs_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[FastAPI, str, int]] = []
    monkeypatch.setattr(
        "agentops_incident_commander.apps.api.os.environ",
        {"AGENTOPS_DATABASE_URL": DATABASE_URL},
    )
    monkeypatch.setattr(
        "agentops_incident_commander.apps.api.uvicorn.run",
        lambda app, host, port: calls.append((app, host, port)),
    )

    assert api.main() == 0
    assert calls[0][1:] == ("0.0.0.0", 8000)
    assert calls[0][0].state.process_role == "api"
    with pytest.raises(SystemExit, match="accepts no arguments"):
        api.main(("unexpected",))


@pytest.mark.anyio
async def test_worker_polls_and_stops_without_http() -> None:
    settings = config.WorkerSettings(DATABASE_URL, "worker-1", 0.05)
    stop = asyncio.Event()
    calls = 0

    async def cancelled() -> bool:
        return False

    async def execute(_: worker.CancellationProbe) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            stop.set()

    async def source(_: int) -> tuple[worker.WorkItem, ...]:
        return (worker.WorkItem(cancelled, execute),)

    await worker.WorkerService(settings, source).run(stop)

    assert calls == 2
    assert "fastapi" not in inspect.getsource(worker)


@pytest.mark.anyio
async def test_worker_default_poller_and_pre_stopped_service_exit() -> None:
    settings = config.WorkerSettings(DATABASE_URL, "worker-1", 0.05)
    assert await worker._no_work_yet(1) == ()
    stop = asyncio.Event()
    stop.set()

    await worker.serve(settings, stop)


@pytest.mark.anyio
async def test_worker_enforces_concurrency_and_checks_cancellation() -> None:
    settings = config.WorkerSettings(DATABASE_URL, "worker-1", 0.05, 3, 1)
    stop = asyncio.Event()
    running = 0
    maximum = 0
    cancelled_handler_calls = 0
    supplied = False

    async def not_cancelled() -> bool:
        return False

    async def already_cancelled() -> bool:
        return True

    async def execute(_: worker.CancellationProbe) -> None:
        nonlocal running, maximum
        running += 1
        maximum = max(maximum, running)
        if maximum == 2:
            stop.set()
        await asyncio.sleep(0)
        running -= 1

    async def must_not_execute(_: worker.CancellationProbe) -> None:
        nonlocal cancelled_handler_calls
        cancelled_handler_calls += 1

    async def source(capacity: int) -> tuple[worker.WorkItem, ...]:
        nonlocal supplied
        assert capacity == 3
        if supplied:
            return ()
        supplied = True
        return (
            worker.WorkItem(not_cancelled, execute),
            worker.WorkItem(not_cancelled, execute),
            worker.WorkItem(already_cancelled, must_not_execute),
        )

    await worker.WorkerService(settings, source).run(stop)
    assert maximum == 2
    assert cancelled_handler_calls == 0


@pytest.mark.anyio
async def test_worker_does_not_claim_while_at_capacity() -> None:
    settings = config.WorkerSettings(DATABASE_URL, "worker-1", 0.05, 1, 1)
    stop = asyncio.Event()
    source_calls = 0

    async def cancelled() -> bool:
        return False

    async def execute(_: worker.CancellationProbe) -> None:
        await asyncio.sleep(0.12)
        stop.set()

    async def source(_: int) -> tuple[worker.WorkItem, ...]:
        nonlocal source_calls
        source_calls += 1
        return (worker.WorkItem(cancelled, execute),)

    await worker.WorkerService(settings, source).run(stop)
    assert source_calls == 1


@pytest.mark.anyio
async def test_worker_rejects_source_capacity_violation() -> None:
    settings = config.WorkerSettings(DATABASE_URL, "worker-1", 0.05, 1, 1)

    async def cancelled() -> bool:
        return False

    async def execute(_: worker.CancellationProbe) -> None:
        return None

    async def source(_: int) -> tuple[worker.WorkItem, ...]:
        item = worker.WorkItem(cancelled, execute)
        return (item, item)

    with pytest.raises(RuntimeError, match="exceeded requested capacity"):
        await worker.WorkerService(settings, source).run(asyncio.Event())


@pytest.mark.anyio
async def test_worker_cancels_overdue_work_after_grace_period() -> None:
    settings = config.WorkerSettings(DATABASE_URL, "worker-1", 0.05, 1, 0.1)
    stop = asyncio.Event()
    was_cancelled = asyncio.Event()

    async def cancelled() -> bool:
        return False

    async def execute(_: worker.CancellationProbe) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            was_cancelled.set()

    async def source(_: int) -> tuple[worker.WorkItem, ...]:
        stop.set()
        return (worker.WorkItem(cancelled, execute),)

    await worker.WorkerService(settings, source).run(stop)
    assert was_cancelled.is_set()


@pytest.mark.anyio
async def test_work_handler_can_recheck_cancellation_at_safe_boundary() -> None:
    settings = config.WorkerSettings(DATABASE_URL, "worker-1", 0.05, 1, 1)
    stop = asyncio.Event()
    checks = 0
    observed: list[bool] = []

    async def cancellation_requested() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    async def execute(probe: worker.CancellationProbe) -> None:
        observed.append(await probe())
        stop.set()

    async def source(_: int) -> tuple[worker.WorkItem, ...]:
        return (worker.WorkItem(cancellation_requested, execute),)

    await worker.WorkerService(settings, source).run(stop)
    assert observed == [True]


@pytest.mark.anyio
async def test_process_signals_request_cooperative_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = config.WorkerSettings(DATABASE_URL, "worker-1", 0.05)
    handlers: dict[object, object] = {}
    restored: list[tuple[object, object]] = []

    monkeypatch.setattr(
        "agentops_incident_commander.apps.worker.signal.getsignal",
        lambda item: f"previous-{item}",
    )

    def install(item: object, handler: object) -> None:
        if callable(handler):
            handlers[item] = handler
        else:
            restored.append((item, handler))

    async def fake_serve(_: config.WorkerSettings, stop: asyncio.Event) -> None:
        handler = handlers[signal.SIGTERM]
        assert callable(handler)
        handler(signal.SIGTERM, None)
        await asyncio.sleep(0)
        assert stop.is_set()

    monkeypatch.setattr("agentops_incident_commander.apps.worker.signal.signal", install)
    monkeypatch.setattr(worker, "serve", fake_serve)
    await worker._run_process(settings)

    assert len(restored) == 2


def test_worker_main_owns_async_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[Coroutine[Any, Any, None]] = []
    monkeypatch.setattr(
        "agentops_incident_commander.apps.worker.os.environ",
        {"AGENTOPS_DATABASE_URL": DATABASE_URL, "AGENTOPS_WORKER_ID": "worker-1"},
    )

    def run(coroutine: Coroutine[Any, Any, None]) -> None:
        received.append(coroutine)
        coroutine.close()

    monkeypatch.setattr("agentops_incident_commander.apps.worker.asyncio.run", run)
    assert worker.main() == 0
    assert len(received) == 1
    with pytest.raises(SystemExit, match="accepts no arguments"):
        worker.main(("unexpected",))


def test_worker_main_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentops_incident_commander.apps.worker.os.environ",
        {"AGENTOPS_DATABASE_URL": DATABASE_URL, "AGENTOPS_WORKER_ID": "worker-1"},
    )

    def interrupt(coroutine: Coroutine[Any, Any, None]) -> None:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr("agentops_incident_commander.apps.worker.asyncio.run", interrupt)
    assert worker.main() == 0
