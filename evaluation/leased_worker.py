"""Transaction-owning leased evaluation worker; handlers own typed workflow composition."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.domain import JobLease, OpaqueIdentifier
from agentops_incident_commander.infrastructure.persistence.repositories import JobRepository


class LeasedEvaluationWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        worker_id: OpaqueIdentifier,
        handler: Callable[[JobLease], Awaitable[None]],
        *,
        lease_seconds: float = 30,
    ) -> None:
        if not 3 <= lease_seconds <= 300:
            raise ValueError("lease duration must be between 3 and 300 seconds")
        self.sessions, self.worker_id, self.handler = sessions, worker_id, handler
        self.duration = timedelta(seconds=lease_seconds)
        self.interval = lease_seconds / 3

    async def run_once(self, capacity: int = 1) -> int:
        async with self.sessions.begin() as session:
            leases = await JobRepository(session).claim(
                self.worker_id, now=datetime.now(UTC), lease_duration=self.duration, limit=capacity
            )
        tasks = [asyncio.create_task(self._execute(lease)) for lease in leases]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(leases)

    async def _renew(self, lease: JobLease) -> None:
        while True:
            await asyncio.sleep(self.interval)
            async with self.sessions.begin() as session:
                await JobRepository(session).heartbeat(
                    lease.job.id,
                    self.worker_id,
                    now=datetime.now(UTC),
                    lease_duration=self.duration,
                )

    async def _execute(self, lease: JobLease) -> None:
        action = asyncio.ensure_future(self.handler(lease))
        renewal = asyncio.create_task(self._renew(lease))
        try:
            done, _ = await asyncio.wait((action, renewal), return_when=asyncio.FIRST_COMPLETED)
            if renewal in done:
                await renewal  # Lease loss prevents successful completion.
            await action
            async with self.sessions.begin() as session:
                await JobRepository(session).complete(
                    lease.job.id, self.worker_id, completed_at=datetime.now(UTC)
                )
        except asyncio.CancelledError:
            raise  # Leave lease for deterministic stale recovery.
        except Exception:
            action.cancel()
            await asyncio.gather(action, return_exceptions=True)
            if renewal.done():
                raise  # Lost authority: leave the new owner and queue state untouched.
            async with self.sessions.begin() as session:
                now = datetime.now(UTC)
                await JobRepository(session).fail(
                    lease.job.id,
                    self.worker_id,
                    failed_at=now,
                    retry_at=now,
                    error="EVALUATION_WORKFLOW_FAILED",
                )
            raise
        finally:
            action.cancel()
            renewal.cancel()
            await asyncio.gather(action, renewal, return_exceptions=True)
