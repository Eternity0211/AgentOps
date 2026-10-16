"""HTTP-free control-plane worker process composition."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from agentops_incident_commander.application import (
    NOOP_CONTROL_PLANE_OBSERVER,
    ControlPlaneObserver,
)
from agentops_incident_commander.infrastructure import create_control_plane_observer

from .config import WorkerSettings
from .observability import ProcessControlPlaneObserver, shutdown_process_observer

CancellationProbe = Callable[[], Awaitable[bool]]
WorkHandler = Callable[[CancellationProbe, ControlPlaneObserver], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WorkItem:
    """A leased job with explicit safe-boundary cancellation access."""

    cancellation_requested: CancellationProbe
    execute: WorkHandler


WorkSource = Callable[[int], Awaitable[Sequence[WorkItem]]]


async def _no_work_yet(_: int) -> Sequence[WorkItem]:
    """Explicit placeholder until the dedicated JobLease batch supplies a poller."""
    return ()


class WorkerService:
    """Bounded polling lifecycle that contains no HTTP application."""

    def __init__(
        self,
        settings: WorkerSettings,
        source: WorkSource = _no_work_yet,
        observer: ControlPlaneObserver = NOOP_CONTROL_PLANE_OBSERVER,
    ) -> None:
        self._settings = settings
        self._source = source
        self._observer = observer

    async def run(self, stop: asyncio.Event) -> None:
        """Poll until shutdown, checking the stop signal between bounded waits."""
        active: set[asyncio.Task[None]] = set()
        while not stop.is_set():
            await self._reap(active)
            capacity = self._settings.max_concurrency - len(active)
            if capacity > 0:
                items = tuple(await self._source(capacity))
                if len(items) > capacity:
                    raise RuntimeError("worker source exceeded requested capacity")
                active.update(
                    asyncio.create_task(self._execute(item, self._observer)) for item in items
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._settings.poll_interval_seconds)
            except TimeoutError:
                continue
        await self._drain(active)

    @staticmethod
    async def _execute(item: WorkItem, observer: ControlPlaneObserver) -> None:
        if await item.cancellation_requested():
            return
        await item.execute(item.cancellation_requested, observer)

    @staticmethod
    async def _reap(active: set[asyncio.Task[None]]) -> None:
        done = {task for task in active if task.done()}
        active.difference_update(done)
        if done:
            await asyncio.gather(*done, return_exceptions=True)

    async def _drain(self, active: set[asyncio.Task[None]]) -> None:
        if not active:
            return
        _, pending = await asyncio.wait(active, timeout=self._settings.shutdown_grace_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)


async def serve(
    settings: WorkerSettings,
    stop: asyncio.Event | None = None,
    *,
    source: WorkSource = _no_work_yet,
    control_plane_observer: ProcessControlPlaneObserver | None = None,
    telemetry_environment: Mapping[str, str] | None = None,
) -> None:
    """Run the worker lifecycle; process signal wiring remains at the CLI boundary."""
    shutdown = asyncio.Event() if stop is None else stop
    observer = (
        control_plane_observer
        if control_plane_observer is not None
        else create_control_plane_observer(
            service_name="agentops-worker",
            environment=telemetry_environment,
        )
    )
    try:
        await WorkerService(settings, source, observer).run(shutdown)
    finally:
        await shutdown_process_observer(observer, process_role="worker")


async def _run_process(settings: WorkerSettings) -> None:
    """Translate process termination signals into cooperative worker shutdown."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = (signal.SIGINT, signal.SIGTERM)
    previous = {item: signal.getsignal(item) for item in signals}

    def request_stop(_: int, __: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    try:
        for item in signals:
            signal.signal(item, request_stop)
        await serve(settings, stop, telemetry_environment=os.environ)
    finally:
        for item, handler in previous.items():
            signal.signal(item, handler)


def main(argv: Sequence[str] | None = None) -> int:
    """Load worker-only settings and run without exposing an HTTP server."""
    if argv:
        raise SystemExit("agentops-worker accepts no arguments")
    settings = WorkerSettings.load(os.environ)
    try:
        asyncio.run(_run_process(settings))
    except KeyboardInterrupt:
        return 0
    return 0
