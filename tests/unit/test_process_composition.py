"""Tests proving API and worker are independent fail-closed processes."""

from __future__ import annotations

import asyncio
import inspect
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
        }
    )

    assert settings.worker_id == "worker-1"
    assert settings.poll_interval_seconds == 0.25


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

    async def poll() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            stop.set()

    await worker.WorkerService(settings, poll).run(stop)

    assert calls == 2
    assert "fastapi" not in inspect.getsource(worker)


@pytest.mark.anyio
async def test_worker_default_poller_and_pre_stopped_service_exit() -> None:
    settings = config.WorkerSettings(DATABASE_URL, "worker-1", 0.05)
    await worker._no_work_yet()
    stop = asyncio.Event()
    stop.set()

    await worker.serve(settings, stop)


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
