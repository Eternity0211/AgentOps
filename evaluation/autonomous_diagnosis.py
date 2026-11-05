"""Real-model investigation through existing plan compiler, Gateway and LangGraph."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.application import (
    PlanningBudgets,
    ToolCallRequest,
    ToolGateway,
    evaluate_evidence_gate,
    resolve_gate_evidence_references,
)
from agentops_incident_commander.domain import (
    ActorId,
    CausationId,
    CorrelationId,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceGateRules,
    IncidentId,
    Principal,
    Role,
    TenantId,
    ToolCallId,
    ToolRegistry,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure import diagnosis_checkpoint_serializer
from agentops_incident_commander.infrastructure.diagnosis_runtime import DiagnosisWorkflowRunner
from agentops_incident_commander.workflows import (
    ContextLoadResult,
    DiagnosisGraphState,
    DiagnosisReport,
    DiagnosisRuntimeContext,
    EvidencePersistenceResult,
    GateNodeResult,
    GateRoute,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
    HypothesisNodeResult,
    PlanNodeResult,
    PlanToolCallReference,
    build_diagnosis_graph,
)
from evaluation.baselines.controlled_graph import _Progress
from evaluation.live_evidence import ExperimentEvidence
from evaluation.live_gateway import SOURCES, LocalReadAdapter, local_definitions
from evaluation.structured_model import (
    INSTRUCTIONS,
    ModelPurpose,
    StructuredEvaluationModel,
    compile_real_plan,
    fingerprint,
)


class JournalAudit:
    def __init__(self, journal: Callable[[dict[str, Any]], None]) -> None:
        self.journal = journal

    async def append(self, event: Any) -> None:
        self.journal(
            {
                "kind": "tool-audit",
                "event_type": event.type,
                "fingerprint": fingerprint(str(event)),
            }
        )


class FixedPromptReference:
    async def require_approved(
        self, state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> None:
        if state.prompt.content_fingerprint != fingerprint(INSTRUCTIONS):
            raise ValueError("evaluation prompt fingerprint mismatch")


class AutonomousServices:
    def __init__(
        self,
        model: StructuredEvaluationModel,
        gateway: ToolGateway,
        registry: ToolRegistry,
        incident: str,
        alert: str,
        root: Path,
        start: datetime,
    ) -> None:
        self.model, self.gateway, self.registry = model, gateway, registry
        self.incident, self.alert, self.root, self.start = incident, alert, root, start
        self.compiled: Any = None
        self.results: dict[str, dict[str, Any]] = {}
        self.evidence: ExperimentEvidence | None = None
        self.report: DiagnosisReport | None = None
        self.gates: list[EvidenceGateDecision] = []
        self.principal = Principal(
            ActorId("evaluation-operator"), TenantId("local-evaluation"), frozenset({Role.OPERATOR})
        )
        self.usage: list[dict[str, int]] = []
        self.resumed = False

    async def load_context(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> ContextLoadResult:
        return ContextLoadResult()

    async def plan(self, state: DiagnosisGraphState, *, operation_id: str) -> PlanNodeResult:
        context = {
            "incident_id": self.incident,
            "alert": self.alert,
            "environment": "local",
            "read_only": True,
            "budgets": {"steps": 8, "parallelism": 4, "calls": 8},
            "catalog": [
                {
                    "name": d.name,
                    "version": d.semantic_version.value,
                    "input_schema": d.input_schema.as_dict(),
                    "source": {
                        "metrics": "METRIC",
                        "logs": "LOG",
                        "traces": "TRACE",
                        "deployments": "DEPLOYMENT",
                        "topology": "TOPOLOGY",
                    }[SOURCES[d.name]],
                }
                for d in self.gateway.diagnosis_catalog()
            ],
        }
        result = await asyncio.to_thread(self.model.invoke, ModelPurpose.PLAN, context)
        self.compiled = compile_real_plan(
            result, self.registry, PlanningBudgets(8, 4, 160000, 32000, 1000000000)
        )
        self.usage.append({"input": result.input_tokens, "output": result.output_tokens})
        references = tuple(
            PlanToolCallReference(
                call_id=f"call-{call.step_id}",
                step_id=call.step_id,
                tool_name=call.tool_name,
                tool_version=call.tool_version.value,
            )
            for call in self.compiled.calls
        )
        return PlanNodeResult(
            "real-plan",
            self.compiled.plan,
            references,
            tuple(call.query_fingerprint for call in self.compiled.calls),
            len(references),
            result.input_tokens + result.output_tokens,
            result.cost_upper_bound_nanousd,
        )

    async def load_tool_batches(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> tuple[tuple[str, ...], ...]:
        groups = sorted({call.parallel_group for call in self.compiled.calls})
        return tuple(
            tuple(
                f"call-{call.step_id}"
                for call in self.compiled.calls
                if call.parallel_group == group
            )
            for group in groups
        )

    async def execute_read_tool(
        self, state: DiagnosisGraphState, tool_call_id: str, *, operation_id: str
    ) -> None:
        selected = next(
            call for call in self.compiled.calls if f"call-{call.step_id}" == tool_call_id
        )
        request = ToolCallRequest(
            call_id=ToolCallId(tool_call_id),
            tool_name=selected.tool_name,
            tool_version=selected.tool_version,
            incident_id=IncidentId(self.incident),
            workflow_run_id=WorkflowRunId(f"workflow-{self.incident}"),
            principal=self.principal,
            correlation_id=CorrelationId(f"correlation-{self.incident}"),
            causation_id=CausationId(f"causation-{self.incident}"),
            arguments_json=selected.arguments_json,
        )
        result = await self.gateway.invoke_diagnosis(request)
        self.results[tool_call_id] = result.result()

    async def persist_evidence(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> EvidencePersistenceResult:
        observations, provenance = [], {}
        for call in self.compiled.calls:
            record = self.results[f"call-{call.step_id}"]
            identifier = f"evidence-{call.step_id}"
            observations.append(
                {"id": identifier, "source": record["source"], "summary": record["summary"]}
            )
            provenance[identifier] = {
                **json.loads(record["provenance"]),
                "records_seen": record["records_seen"],
            }
        self.evidence = ExperimentEvidence(
            self.root,
            self.incident,
            observations,
            observed_from=self.start,
            provenance_by_id=provenance,
        )
        if not self.evidence.records:
            raise ValueError("all telemetry quarantined")
        return EvidencePersistenceResult(tuple(item.value for item in self.evidence.records))

    async def hypothesize(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> HypothesisNodeResult:
        assert self.evidence is not None
        # Preserve whole records under an aggregate budget; never slice JSON mid-record.
        observations = []
        used = 0
        for item in self.evidence.observations:
            size = len(json.dumps(item).encode())
            if used + size > 24000:
                continue
            observations.append(item)
            used += size
        result = await asyncio.to_thread(
            self.model.invoke,
            ModelPurpose.DIAGNOSE,
            {
                "incident_id": self.incident,
                "alert": self.alert,
                "evidence_ids": [item["id"] for item in observations],
                "observations": observations,
            },
        )
        self.report = cast(DiagnosisReport, result.output)
        self.usage.append({"input": result.input_tokens, "output": result.output_tokens})
        return HypothesisNodeResult(
            "real-diagnosis",
            result.input_tokens + result.output_tokens,
            result.cost_upper_bound_nanousd,
        )

    async def evaluate_evidence_gate(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> GateNodeResult:
        assert self.evidence is not None and self.report is not None
        for candidate in self.report.candidates:
            claim = self.report.evidence_gate_claim(candidate.candidate_id)
            now = datetime.now(UTC)
            resolution = await resolve_gate_evidence_references(
                claim,
                tenant_id=self.evidence.tenant,
                principal=self.principal,
                reader=self.evidence,
                artifact_storage=self.evidence.storage,
                at=now,
            )
            self.gates.append(
                evaluate_evidence_gate(claim, resolution, rules=EvidenceGateRules(), at=now)
            )
        passed = any(item.outcome is EvidenceGateOutcome.PASS for item in self.gates)
        return GateNodeResult(
            fingerprint([str(item) for item in self.gates]),
            GateRoute.PASS if passed else GateRoute.HUMAN_HANDOFF,
            None if passed else "EVIDENCE_GATE_NOT_PASSED",
        )

    async def record_handoff(self, state: DiagnosisGraphState, *, operation_id: str) -> None:
        return None


async def investigate(
    model: StructuredEvaluationModel,
    incident: str,
    alert: str,
    root: Path,
    start: datetime,
    end: datetime,
    journal: Callable[[dict[str, Any]], None],
    *,
    adapters: dict[Any, Any] | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> tuple[DiagnosisGraphState, AutonomousServices]:
    definitions = local_definitions()
    registry = ToolRegistry(definitions)
    counter = iter(range(1000))
    gateway = ToolGateway(
        registry,
        adapters or {d.identity: LocalReadAdapter(d.name, start, end) for d in definitions},
        JournalAudit(journal),
        audit_id_factory=lambda: f"audit-{next(counter)}",
    )
    services = AutonomousServices(model, gateway, registry, incident, alert, root, start)
    state = DiagnosisGraphState(
        state_schema_version="1.3.0",
        graph_version="1.0.0",
        tenant_id="local-evaluation",
        incident_id=incident,
        workflow_run_id=f"workflow-{incident}",
        correlation_id=f"correlation-{incident}",
        causation_id=f"causation-{incident}",
        phase=GraphPhase.CONTEXT_LOADING,
        budgets=GraphBudgetState(
            max_steps=8,
            used_steps=0,
            max_replans=0,
            used_replans=0,
            max_tool_calls=8,
            used_tool_calls=0,
            max_model_calls=4,
            used_model_calls=0,
            max_tokens=64000,
            used_tokens=0,
            max_cost_nanounits=1000000000,
            used_cost_nanounits=0,
        ),
        prompt=GraphPromptReference(
            prompt_id="real-investigation-evaluation",
            version="1.0.0",
            content_fingerprint=fingerprint(INSTRUCTIONS),
        ),
        checkpoint_sequence=0,
        updated_at=datetime.now(UTC),
    )
    saver = checkpointer or InMemorySaver(serde=diagnosis_checkpoint_serializer())
    graph = build_diagnosis_graph(checkpointer=saver)
    outcome = await DiagnosisWorkflowRunner(graph).run_or_resume(
        state,
        DiagnosisRuntimeContext(services, FixedPromptReference(), _Progress()),
    )
    services.resumed = outcome.resumed
    return outcome.state, services
