"""Strict PostgreSQL checkpoint composition for Diagnosis LangGraph runs."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agentops_incident_commander.domain import InvalidDomainValueError
from agentops_incident_commander.workflows import DiagnosisGraphState

# LangGraph reserves non-empty namespaces for compiled subgraphs; Diagnosis is the root graph.
DIAGNOSIS_CHECKPOINT_NAMESPACE = ""
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ALLOWED_CHECKPOINT_TYPES = (
    ("agentops_incident_commander.workflows.state", "DiagnosisGraphState"),
    ("agentops_incident_commander.workflows.state", "GraphBudgetState"),
    ("agentops_incident_commander.workflows.state", "GraphPhase"),
    ("agentops_incident_commander.workflows.state", "GraphPromptReference"),
)


@dataclass(frozen=True, slots=True)
class DiagnosisCheckpointIdentity:
    tenant_id: str
    incident_id: str
    workflow_run_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None
            for value in (
                self.tenant_id,
                self.incident_id,
                self.workflow_run_id,
                self.correlation_id,
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
            },
        }

    def require_matches(self, state: DiagnosisGraphState) -> None:
        if self != DiagnosisCheckpointIdentity.from_state(state):
            raise InvalidDomainValueError("checkpoint identity does not match graph state")


def diagnosis_checkpoint_config(state: DiagnosisGraphState) -> RunnableConfig:
    """Create the only supported thread/run correlation config for Diagnosis state."""
    return DiagnosisCheckpointIdentity.from_state(state).config()


def diagnosis_checkpoint_serializer() -> JsonPlusSerializer:
    """Allow only project state types required by checkpoint reconstruction."""
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_json_modules=_ALLOWED_CHECKPOINT_TYPES,
        allowed_msgpack_modules=_ALLOWED_CHECKPOINT_TYPES,
    )


@asynccontextmanager
async def postgres_diagnosis_checkpointer(
    connection_url: str,
) -> AsyncIterator[AsyncPostgresSaver]:
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
        yield saver
