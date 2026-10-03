"""HTTP-free control-plane worker process composition."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence

from .config import WorkerSettings

WorkPoller = Callable[[], Awaitable[None]]


async def _no_work_yet() -> None:
    """Explicit placeholder until the dedicated JobLease batch supplies a poller."""


class WorkerService:
    """Bounded polling lifecycle that contains no HTTP application."""

    def __init__(self, settings: WorkerSettings, poll: WorkPoller = _no_work_yet) -> None:
        self._settings = settings
        self._poll = poll

    async def run(self, stop: asyncio.Event) -> None:
        """Poll until shutdown, checking the stop signal between bounded waits."""
        while not stop.is_set():
            await self._poll()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._settings.poll_interval_seconds)
            except TimeoutError:
                continue


async def serve(settings: WorkerSettings, stop: asyncio.Event | None = None) -> None:
    """Run the worker lifecycle; process signal wiring remains at the CLI boundary."""
    shutdown = asyncio.Event() if stop is None else stop
    await WorkerService(settings).run(shutdown)


def main(argv: Sequence[str] | None = None) -> int:
    """Load worker-only settings and run without exposing an HTTP server."""
    if argv:
        raise SystemExit("agentops-worker accepts no arguments")
    settings = WorkerSettings.load(os.environ)
    try:
        asyncio.run(serve(settings))
    except KeyboardInterrupt:
        return 0
    return 0
