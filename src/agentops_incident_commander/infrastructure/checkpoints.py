"""Strict PostgreSQL checkpoint composition for Diagnosis LangGraph runs."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agentops_incident_commander.application import (
    NOOP_CONTROL_PLANE_OBSERVER,
    ControlPlaneComponent,
    ControlPlaneObservation,
    ControlPlaneObserver,
    ControlPlaneOperation,
    ControlPlaneOutcome,
    safely_record,
    utc_observation_time,
)
from agentops_incident_commander.domain import (
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    StructuredLogEvent,
    StructuredLogSeverity,
    TenantId,
    WorkflowRunId,
)
from agentops_incident_commander.structured_logging import emit_structured_log
from agentops_incident_commander.workflows import ApprovalWaitState, DiagnosisGraphState

# LangGraph reserves non-empty namespaces for compiled subgraphs; Diagnosis is the root graph.
DIAGNOSIS_CHECKPOINT_NAMESPACE = ""
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ALLOWED_CHECKPOINT_TYPES = (
    ("agentops_incident_commander.workflows.approval_graph", "ApprovalWaitState"),
    ("agentops_incident_commander.workflows.approval_graph", "ApprovalGraphPhase"),
    ("agentops_incident_commander.workflows.state", "DiagnosisGraphState"),
    ("agentops_incident_commander.workflows.state", "GraphBudgetState"),
    ("agentops_incident_commander.workflows.state", "GraphPhase"),
    ("agentops_incident_commander.workflows.state", "GraphPromptReference"),
)
logger = logging.getLogger("agentops.control_plane.checkpoints")


@dataclass(frozen=True, slots=True)
class DiagnosisCheckpointIdentity:
    tenant_id: str
    incident_id: str
    workflow_run_id: str
    correlation_id: str
    causation_id: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None
            for value in (
                self.tenant_id,
                self.incident_id,
                self.workflow_run_id,
                self.correlation_id,
                self.causation_id,
            )
        ):
            raise InvalidDomainValueError("checkpoint correlation identifiers are invalid")

    @classmethod
    def from_state(cls, state: DiagnosisGraphState) -> DiagnosisCheckpointIdentity:
        if not isinstance(state, DiagnosisGraphState):
            raise InvalidDomainValueError("checkpoint identity requires Diagnosis graph state")
        return cls(
            state.tenant_id,
            state.incident_id,
            state.workflow_run_id,
            state.correlation_id,
            state.causation_id,
        )

    @property
    def thread_id(self) -> str:
        canonical = json.dumps(
            {
                "incident_id": self.incident_id,
                "tenant_id": self.tenant_id,
                "workflow_run_id": self.workflow_run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"diagnosis-{sha256(canonical.encode('utf-8')).hexdigest()}"

    def config(self) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": self.thread_id,
                "checkpoint_ns": DIAGNOSIS_CHECKPOINT_NAMESPACE,
            },
            "metadata": {
                "tenant_id": self.tenant_id,
                "incident_id": self.incident_id,
                "workflow_run_id": self.workflow_run_id,
                "correlation_id": self.correlation_id,
                "causation_id": self.causation_id,
            },
        }

    def require_matches(self, state: DiagnosisGraphState) -> None:
        if self != DiagnosisCheckpointIdentity.from_state(state):
            raise InvalidDomainValueError("checkpoint identity does not match graph state")


@dataclass(frozen=True, slots=True)
class ApprovalCheckpointIdentity:
    tenant_id: str
    incident_id: str
    workflow_run_id: str
    correlation_id: str
    causation_id: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None
            for value in (
                self.tenant_id,
                self.incident_id,
                self.workflow_run_id,
                self.correlation_id,
                self.causation_id,
            )
        ):
            raise InvalidDomainValueError("Approval checkpoint identifiers are invalid")

    @classmethod
    def from_state(cls, state: ApprovalWaitState) -> ApprovalCheckpointIdentity:
        if not isinstance(state, ApprovalWaitState):
            raise InvalidDomainValueError("Approval checkpoint identity requires Approval state")
        return cls(
            state.tenant_id,
            state.incident_id,
            state.workflow_run_id,
            state.correlation_id,
            state.causation_id,
        )

    @property
    def thread_id(self) -> str:
        canonical = json.dumps(
            {
                "incident_id": self.incident_id,
                "tenant_id": self.tenant_id,
                "workflow_run_id": self.workflow_run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"approval-{sha256(canonical.encode('utf-8')).hexdigest()}"

    def config(self) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": self.thread_id,
                "checkpoint_ns": "",
            },
            "metadata": {
                "tenant_id": self.tenant_id,
                "incident_id": self.incident_id,
                "workflow_run_id": self.workflow_run_id,
                "correlation_id": self.correlation_id,
                "causation_id": self.causation_id,
            },
        }

    def require_matches(self, state: ApprovalWaitState) -> None:
        if self != ApprovalCheckpointIdentity.from_state(state):
            raise InvalidDomainValueError("Approval checkpoint identity does not match state")


def diagnosis_checkpoint_config(state: DiagnosisGraphState) -> RunnableConfig:
    """Create the only supported thread/run correlation config for Diagnosis state."""
    return DiagnosisCheckpointIdentity.from_state(state).config()


def approval_checkpoint_config(state: ApprovalWaitState) -> RunnableConfig:
    return ApprovalCheckpointIdentity.from_state(state).config()


def diagnosis_checkpoint_serializer() -> JsonPlusSerializer:
    """Allow only project state types required by checkpoint reconstruction."""
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_json_modules=_ALLOWED_CHECKPOINT_TYPES,
        allowed_msgpack_modules=_ALLOWED_CHECKPOINT_TYPES,
    )


class ObservedCheckpointSaver(BaseCheckpointSaver[Any]):
    """Fail-open telemetry proxy around the authoritative PostgreSQL saver."""

    def __init__(
        self,
        delegate: BaseCheckpointSaver[Any],
        observer: ControlPlaneObserver,
    ) -> None:
        super().__init__(serde=delegate.serde)
        self._delegate = delegate
        self._observer = observer

    @property
    def config_specs(self) -> list[Any]:
        return list(self._delegate.config_specs)

    def get_next_version(self, current: Any, channel: None) -> Any:
        return self._delegate.get_next_version(current, channel)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        started_ns = time.monotonic_ns()
        try:
            value = await self._delegate.aget_tuple(config)
        except BaseException:
            _record_checkpoint_observation(
                self._observer,
                config,
                operation=ControlPlaneOperation.CHECKPOINT_RESTORE,
                outcome=ControlPlaneOutcome.FAILED,
                started_ns=started_ns,
                route="FAILED",
                result_code="CHECKPOINT_IO_ERROR",
            )
            raise
        observed_config = (
            config if value is None else _checkpoint_config_with_metadata(value.config, config)
        )
        _record_checkpoint_observation(
            self._observer,
            observed_config,
            operation=ControlPlaneOperation.CHECKPOINT_RESTORE,
            outcome=(
                ControlPlaneOutcome.SUCCEEDED if value is None else ControlPlaneOutcome.RESUMED
            ),
            started_ns=started_ns,
            route="MISS" if value is None else "HIT",
            result_code="NOT_FOUND" if value is None else "RESTORED",
        )
        return value

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        async for item in self._delegate.alist(
            config,
            filter=filter,
            before=before,
            limit=limit,
        ):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        started_ns = time.monotonic_ns()
        try:
            saved_config = await self._delegate.aput(
                config,
                checkpoint,
                metadata,
                new_versions,
            )
        except BaseException:
            _record_checkpoint_observation(
                self._observer,
                config,
                operation=ControlPlaneOperation.CHECKPOINT_SAVE,
                outcome=ControlPlaneOutcome.FAILED,
                started_ns=started_ns,
                route="FAILED",
                result_code="CHECKPOINT_IO_ERROR",
            )
            raise
        _record_checkpoint_observation(
            self._observer,
            _checkpoint_config_with_metadata(saved_config, config),
            operation=ControlPlaneOperation.CHECKPOINT_SAVE,
            outcome=ControlPlaneOutcome.SUCCEEDED,
            started_ns=started_ns,
            route="SAVED",
            result_code="PERSISTED",
        )
        return saved_config

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await self._delegate.aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await self._delegate.adelete_thread(thread_id)


def _checkpoint_config_with_metadata(
    checkpoint_config: RunnableConfig,
    source_config: RunnableConfig,
) -> RunnableConfig:
    """Preserve trusted scope metadata omitted from a saver return config."""
    metadata = source_config.get("metadata")
    return {
        **checkpoint_config,
        **({"metadata": metadata} if isinstance(metadata, dict) else {}),
    }


def _record_checkpoint_observation(
    observer: ControlPlaneObserver,
    config: RunnableConfig,
    *,
    operation: ControlPlaneOperation,
    outcome: ControlPlaneOutcome,
    started_ns: int,
    route: str,
    result_code: str,
) -> None:
    """Treat malformed metadata and exporter failures as telemetry loss only."""
    try:
        metadata = config.get("metadata")
        configurable = config.get("configurable")
        if not isinstance(metadata, dict) or not isinstance(configurable, dict):
            raise InvalidDomainValueError("checkpoint observation metadata is missing")
        thread_id = configurable.get("thread_id")
        checkpoint_id = configurable.get("checkpoint_id")
        if not isinstance(thread_id, str):
            raise InvalidDomainValueError("checkpoint observation thread is missing")
        operation_id = checkpoint_id if isinstance(checkpoint_id, str) else thread_id
        safely_record(
            observer,
            ControlPlaneObservation(
                component=ControlPlaneComponent.CHECKPOINT,
                operation=operation,
                outcome=outcome,
                occurred_at=utc_observation_time(),
                tenant_id=TenantId(str(metadata["tenant_id"])),
                incident_id=IncidentId(str(metadata["incident_id"])),
                correlation_id=CorrelationId(str(metadata["correlation_id"])),
                causation_id=CausationId(str(metadata["causation_id"])),
                operation_id=OpaqueIdentifier(operation_id),
                workflow_run_id=WorkflowRunId(str(metadata["workflow_run_id"])),
                duration_ms=max(0, (time.monotonic_ns() - started_ns) // 1_000_000),
                route=route,
                result_code=result_code,
                subject_name=("approval" if thread_id.startswith("approval-") else "diagnosis"),
            ),
        )
    except Exception:
        emit_structured_log(
            logger,
            StructuredLogEvent.CHECKPOINT_OBSERVATION_DROPPED,
            StructuredLogSeverity.WARN,
            {"agentops.operation": operation.value},
        )


@asynccontextmanager
async def postgres_diagnosis_checkpointer(
    connection_url: str,
    *,
    observer: ControlPlaneObserver = NOOP_CONTROL_PLANE_OBSERVER,
) -> AsyncIterator[BaseCheckpointSaver[Any]]:
    """Open, migrate, and close the production async PostgreSQL checkpointer."""
    if not isinstance(connection_url, str) or not connection_url.startswith(
        ("postgresql://", "postgres://")
    ):
        raise InvalidDomainValueError("checkpoint connection URL must use PostgreSQL")
    async with AsyncPostgresSaver.from_conn_string(
        connection_url,
        serde=diagnosis_checkpoint_serializer(),
    ) as saver:
        await saver.setup()
        yield ObservedCheckpointSaver(saver, observer)


@asynccontextmanager
async def postgres_approval_checkpointer(
    connection_url: str,
    *,
    observer: ControlPlaneObserver = NOOP_CONTROL_PLANE_OBSERVER,
) -> AsyncIterator[BaseCheckpointSaver[Any]]:
    if not isinstance(connection_url, str) or not connection_url.startswith(
        ("postgresql://", "postgres://")
    ):
        raise InvalidDomainValueError("checkpoint connection URL must use PostgreSQL")
    async with AsyncPostgresSaver.from_conn_string(
        connection_url,
        serde=diagnosis_checkpoint_serializer(),
    ) as saver:
        await saver.setup()
        yield ObservedCheckpointSaver(saver, observer)
