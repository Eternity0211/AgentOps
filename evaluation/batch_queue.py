"""Bounded deterministic dispatch for an isolated evaluation queue, not a runtime broker."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.domain import Job, JobLease, OpaqueIdentifier
from evaluation.leased_worker import LeasedEvaluationWorker


class BatchQueue:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        expected: int,
        concurrency: int,
        timeout: float = 180,
    ) -> None:
        if not 1 <= concurrency <= expected <= 16 or not 3 <= timeout <= 600:
            raise ValueError("invalid isolated batch bounds")
        self.sessions, self.expected = sessions, expected
        self.concurrency, self.timeout = concurrency, timeout
        self.ready = asyncio.Event()
        self.entries: dict[
            str, tuple[Job, Callable[[JobLease], Awaitable[None]], asyncio.Future[None]]
        ] = {}
        self.active = self.peak = 0

    async def consume(self, job: Job, handler: Callable[[JobLease], Awaitable[None]]) -> None:
        if job.id.value in self.entries or len(self.entries) >= self.expected:
            raise ValueError("duplicate or excess batch job")
        done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.entries[job.id.value] = (job, handler, done)
        if len(self.entries) == self.expected:
            self.ready.set()
        try:
            await asyncio.wait_for(asyncio.shield(done), self.timeout)
        finally:
            if not done.done():
                done.cancel()

    async def dispatch(self, lease: JobLease) -> None:
        entry = self.entries.get(lease.job.id.value)
        if entry is None or entry[0] != lease.job or entry[2].cancelled():
            raise ValueError("batch job identity mismatch")
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await entry[1](lease)
        finally:
            self.active -= 1

    async def run(self) -> int:
        completed = 0
        try:
            await asyncio.wait_for(self.ready.wait(), self.timeout)
            worker = LeasedEvaluationWorker(
                self.sessions, OpaqueIdentifier("isolated-batch-worker"), self.dispatch
            )
            while completed < self.expected:
                count = await asyncio.wait_for(worker.run_once(self.concurrency), self.timeout)
                if not count:
                    raise ValueError("batch queue incomplete")
                completed += count
            for _, _, done in self.entries.values():
                if not done.done():
                    done.set_result(None)
            return completed
        except BaseException:
            for _, _, done in self.entries.values():
                if not done.done():
                    done.set_exception(ValueError("isolated batch did not complete"))
            raise
