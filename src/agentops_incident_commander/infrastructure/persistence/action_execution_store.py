"""Transaction-owning durable ActionExecution application-store adapter."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.domain import ActionExecution, AuditEvent

from .repositories import ActionExecutionRepository


class PostgresActionExecutionStore:
    """Commit each claim, replay observation, and completion as its own durable boundary."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim(
        self,
        execution: ActionExecution,
        audit_event: AuditEvent,
        replay_audit_factory: Callable[[ActionExecution], AuditEvent],
    ) -> tuple[ActionExecution, bool]:
        async with self._sessions.begin() as session:
            repository = ActionExecutionRepository(session)
            stored, replayed = await repository.claim(execution, audit_event)
            if replayed:
                await repository.record_replay(
                    execution,
                    stored,
                    replay_audit_factory(stored),
                )
            return stored, replayed

    async def finish(
        self,
        expected: ActionExecution,
        completed: ActionExecution,
        audit_event: AuditEvent,
    ) -> ActionExecution:
        async with self._sessions.begin() as session:
            return await ActionExecutionRepository(session).finish(
                expected,
                completed,
                audit_event,
            )
