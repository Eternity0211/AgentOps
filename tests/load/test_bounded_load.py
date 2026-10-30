"""Bounded in-process API and worker load checks used by the measured load runner."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from evaluation.contracts import load_json_object
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from agentops_incident_commander.apps.api import create_app
from agentops_incident_commander.apps.config import ApiSettings, WorkerSettings
from agentops_incident_commander.apps.worker import WorkerService, WorkItem

ROOT = Path(__file__).resolve().parents[2]
PLAN = load_json_object(ROOT / "evaluation" / "load" / "v1" / "plan.json")
WORKLOADS = {item["workload_id"]: item for item in PLAN["workloads"]}


@pytest.mark.anyio
async def test_bounded_api_health_load() -> None:
    config = WORKLOADS["api-health"]
    request_ids = iter(f"load-request-{index}" for index in range(config["operations"]))

    async def principal(_: Request) -> None:
        return None

    app = create_app(
        ApiSettings("postgresql+asyncpg://unused:unused@localhost/unused", "127.0.0.1", 8000),
        session_factory=lambda: None,  # type: ignore[arg-type]
        principal_resolver=principal,
        request_id_factory=lambda: next(request_ids),
        telemetry_environment={"OTEL_SDK_ENABLED": "false"},
    )
    semaphore = asyncio.Semaphore(config["concurrency"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://load.test") as client:

        async def request() -> tuple[int, str | None]:
            async with semaphore:
                response = await client.get("/healthz")
                return response.status_code, response.headers.get("X-Request-ID")

        results = await asyncio.gather(*(request() for _ in range(config["operations"])))
    assert all(status == 200 for status, _ in results)
    assert len({request_id for _, request_id in results}) == config["operations"]


@pytest.mark.anyio
async def test_bounded_worker_processing_load() -> None:
    config = WORKLOADS["worker-processing"]
    settings = WorkerSettings(
        "postgresql+asyncpg://unused:unused@localhost/unused",
        "worker-load",
        0.001,
        config["concurrency"],
        1,
    )
    stop = asyncio.Event()
    supplied = 0
    completed = 0
    running = 0
    maximum = 0
    lock = asyncio.Lock()

    async def cancelled() -> bool:
        return False

    async def execute(_: Any, __: object) -> None:
        nonlocal completed, maximum, running
        async with lock:
            running += 1
            maximum = max(maximum, running)
        await asyncio.sleep(0.001)
        async with lock:
            running -= 1
            completed += 1
            if completed == config["operations"]:
                stop.set()

    async def source(capacity: int) -> tuple[WorkItem, ...]:
        nonlocal supplied
        count = min(capacity, config["operations"] - supplied)
        supplied += count
        return tuple(WorkItem(cancelled, execute) for _ in range(count))

    await WorkerService(settings, source).run(stop)
    assert supplied == completed == config["operations"]
    assert maximum == config["concurrency"]
