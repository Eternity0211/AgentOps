"""Crash-resumable Diagnosis graph execution and content-free checkpoint views."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentops_incident_commander.domain import InvalidDomainValueError
from agentops_incident_commander.workflows import (
    DiagnosisGraphState,
    DiagnosisRuntimeContext,
    GraphPhase,
    canonical_graph_state_bytes,
)

from .checkpoints import DiagnosisCheckpointIdentity

_CHECKPOINT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
_NODE_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_HASH_PATTERN = r"^[0-9a-f]{64}$"


class CheckpointExecutionStatus(StrEnum):
    READY = "READY"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    COMPLETE = "COMPLETE"


class DiagnosisCheckpointObservation(BaseModel):
    """Bounded checkpoint projection that cannot contain workflow payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    thread_id: str = Field(pattern=_CHECKPOINT_ID_PATTERN)
    checkpoint_id: str = Field(pattern=_CHECKPOINT_ID_PATTERN)
    parent_checkpoint_id: str | None = Field(default=None, pattern=_CHECKPOINT_ID_PATTERN)
    workflow_run_id: str = Field(pattern=_CHECKPOINT_ID_PATTERN)
    phase: GraphPhase
    status: CheckpointExecutionStatus
    checkpoint_sequence: int = Field(ge=0)
    next_nodes: tuple[str, ...] = Field(max_length=16)
    task_count: int = Field(ge=0, le=128)
    interrupt_count: int = Field(ge=0, le=128)
    state_fingerprint: str = Field(pattern=_HASH_PATTERN)
    created_at: datetime

    @field_validator("next_nodes")
    @classmethod
    def validate_node_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(re.fullmatch(_NODE_PATTERN, item) is None for item in value):
            raise ValueError("checkpoint next-node names are invalid")
        return value

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checkpoint timestamp must be timezone-aware")
        return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class DiagnosisRunOutcome:
    state: DiagnosisGraphState
    resumed: bool
    checkpoint: DiagnosisCheckpointObservation


class DiagnosisGraphRuntime(Protocol):
    async def ainvoke(
        self,
        input: DiagnosisGraphState | Command[Any] | None,
        config: RunnableConfig | None = None,
        *,
        context: DiagnosisRuntimeContext | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def aget_state(
        self, config: RunnableConfig, *, subgraphs: bool = False
    ) -> StateSnapshot: ...

    def aget_state_history(
        self,
        config: RunnableConfig,
        *,
        limit: int | None = None,
    ) -> AsyncIterator[StateSnapshot]: ...


class DiagnosisWorkflowRunner:
    """Start or continue one checkpointed run without replacing its durable state."""

    def __init__(self, graph: DiagnosisGraphRuntime) -> None:
        self._graph = graph

    async def run_or_resume(
        self, initial_state: DiagnosisGraphState, runtime: DiagnosisRuntimeContext
    ) -> DiagnosisRunOutcome:
        identity = DiagnosisCheckpointIdentity.from_state(initial_state)
        config = identity.config()
        before = await self._graph.aget_state(config)
        resumed = bool(before.values)
        if resumed:
            persisted = _state_from_snapshot(before)
            identity.require_matches(persisted)
        result = await self._graph.ainvoke(
            None if resumed else initial_state,
            config,
            context=runtime,
        )
        final_state = DiagnosisGraphState.model_validate(result)
        identity.require_matches(final_state)
        checkpoint = checkpoint_observation(await self._graph.aget_state(config), identity)
        return DiagnosisRunOutcome(final_state, resumed, checkpoint)

    async def history(
        self, state: DiagnosisGraphState, *, limit: int = 100
    ) -> tuple[DiagnosisCheckpointObservation, ...]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 512:
            raise InvalidDomainValueError("checkpoint history limit must be between 1 and 512")
        identity = DiagnosisCheckpointIdentity.from_state(state)
        observations = []
        async for snapshot in self._graph.aget_state_history(identity.config(), limit=limit + 1):
            if not isinstance(snapshot.values, dict) or not snapshot.values:
                continue
            observations.append(checkpoint_observation(snapshot, identity))
            if len(observations) == limit:
                break
        return tuple(observations)


def checkpoint_observation(
    snapshot: StateSnapshot, identity: DiagnosisCheckpointIdentity
) -> DiagnosisCheckpointObservation:
    """Project a LangGraph snapshot into validated identifiers, counts, and hashes only."""
    state = _state_from_snapshot(snapshot)
    identity.require_matches(state)
    checkpoint_id = _config_identifier(snapshot.config, "checkpoint_id")
    parent_checkpoint_id = (
        None
        if snapshot.parent_config is None
        else _config_identifier(snapshot.parent_config, "checkpoint_id")
    )
    created_at = _parse_created_at(snapshot.created_at)
    status = _checkpoint_status(snapshot)
    return DiagnosisCheckpointObservation(
        thread_id=identity.thread_id,
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        workflow_run_id=state.workflow_run_id,
        phase=state.phase,
        status=status,
        checkpoint_sequence=state.checkpoint_sequence,
        next_nodes=snapshot.next,
        task_count=len(snapshot.tasks),
        interrupt_count=len(snapshot.interrupts),
        state_fingerprint=sha256(canonical_graph_state_bytes(state)).hexdigest(),
        created_at=created_at,
    )


def _state_from_snapshot(snapshot: StateSnapshot) -> DiagnosisGraphState:
    if not isinstance(snapshot.values, dict) or not snapshot.values:
        raise InvalidDomainValueError("checkpoint does not contain Diagnosis graph state")
    return DiagnosisGraphState.model_validate(snapshot.values)


def _config_identifier(config: RunnableConfig, name: str) -> str:
    configurable = config.get("configurable")
    value = configurable.get(name) if isinstance(configurable, dict) else None
    if not isinstance(value, str) or not value:
        raise InvalidDomainValueError(f"checkpoint config is missing {name}")
    return value


def _parse_created_at(value: str | None) -> datetime:
    if not isinstance(value, str):
        raise InvalidDomainValueError("checkpoint creation timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidDomainValueError("checkpoint creation timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidDomainValueError("checkpoint creation timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _checkpoint_status(snapshot: StateSnapshot) -> CheckpointExecutionStatus:
    if snapshot.interrupts:
        return CheckpointExecutionStatus.INTERRUPTED
    if any(task.error is not None for task in snapshot.tasks):
        return CheckpointExecutionStatus.FAILED
    if not snapshot.next:
        return CheckpointExecutionStatus.COMPLETE
    return CheckpointExecutionStatus.READY


def compiled_diagnosis_runner(
    graph: CompiledStateGraph[
        DiagnosisGraphState,
        DiagnosisRuntimeContext,
        DiagnosisGraphState,
        DiagnosisGraphState,
    ],
) -> DiagnosisWorkflowRunner:
    """Type-preserving composition helper for the production compiled graph."""
    return DiagnosisWorkflowRunner(graph)
