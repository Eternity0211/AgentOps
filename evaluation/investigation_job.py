"""Bind durable job identity to server-owned registered investigation composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.domain import JobLease
from agentops_incident_commander.workflows import DiagnosisProgressRecorder
from evaluation.autonomous_diagnosis import WorkflowEvidenceStore, investigate
from evaluation.registered_model import RegisteredModelInvoker


@dataclass(frozen=True)
class InvestigationJobInput:
    payload_ref: str
    tenant_id: str
    incident_id: str
    workflow_run_id: str
    correlation_id: str
    causation_id: str
    alert: str
    start: datetime
    end: datetime
    artifact_root: Path


class RegisteredInvestigationJobHandler:
    def __init__(
        self,
        payload: InvestigationJobInput,
        invoker_factory: Callable[[], Awaitable[RegisteredModelInvoker]],
        checkpointer: BaseCheckpointSaver[Any],
        evidence: WorkflowEvidenceStore,
        progress: DiagnosisProgressRecorder,
        journal: Callable[[dict[str, Any]], None],
    ) -> None:
        self.payload, self.factory = payload, invoker_factory
        self.checkpointer, self.evidence, self.progress = checkpointer, evidence, progress
        self.journal = journal

    async def __call__(self, lease: JobLease) -> None:
        job, payload = lease.job, self.payload
        if (job.type, job.schema_version) != ("workflow.investigate", "workflow/v1"):
            raise ValueError("unsupported investigation job schema")
        actual = (
            job.payload_ref.value,
            job.tenant_id.value,
            job.incident_id.value,
            job.workflow_run_id.value,
            job.correlation_id.value,
            job.causation_id.value,
        )
        expected = (
            payload.payload_ref,
            payload.tenant_id,
            payload.incident_id,
            payload.workflow_run_id,
            payload.correlation_id,
            payload.causation_id,
        )
        if actual != expected:
            raise ValueError("investigation job binding mismatch")
        invoker = await self.factory()
        if (
            invoker.principal.tenant_id.value,
            invoker.incident.value,
            invoker.workflow.value,
            invoker.correlation.value,
            invoker.causation.value,
        ) != expected[1:]:
            raise ValueError("registered invoker job binding mismatch")
        await investigate(
            invoker.model,
            payload.incident_id,
            payload.alert,
            payload.artifact_root,
            payload.start,
            payload.end,
            self.journal,
            checkpointer=self.checkpointer,
            evidence_store=self.evidence,
            progress_recorder=self.progress,
            model_invoker=invoker,
        )
