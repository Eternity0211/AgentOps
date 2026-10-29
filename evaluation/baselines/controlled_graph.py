"""Controlled LangGraph baseline using the production Diagnosis graph topology."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from agentops_incident_commander.domain import EvidenceSourceType
from agentops_incident_commander.infrastructure import (
    MOCK_MODEL_VERSION,
    DeterministicDiagnosisMockModel,
    MockDiagnosisRequest,
    MockModelResult,
    MockModelScenario,
    diagnosis_checkpoint_serializer,
)
from agentops_incident_commander.workflows import (
    DIAGNOSIS_NODE_NAMES,
    ContextLoadResult,
    DiagnosisGraphState,
    DiagnosisRuntimeContext,
    EvidencePersistenceResult,
    GateNodeResult,
    GateRoute,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
    HypothesisNodeResult,
    InvestigationPlan,
    PlanNodeResult,
    PlanToolCallReference,
    ToolProgressStatus,
    build_diagnosis_graph,
)
from agentops_incident_commander.workflows.diagnosis import DiagnosisReport
from evaluation.contracts import (
    EvaluationCase,
    EvaluationContractError,
    canonical_json,
    content_sha256,
    load_json_object,
)
from evaluation.fairness import CandidateExecutionConfig

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_SETTINGS = ROOT / "evaluation" / "models" / "v1" / "diagnosis-mock.json"
DEFAULT_PROMPT = ROOT / "evaluation" / "prompts" / "v1" / "controlled-graph.json"
CONTROLLED_GRAPH_BASELINE_VERSION = "1.0.0"
CONTROLLED_GRAPH_PROMPT_VERSION = "diagnosis-graph-v1.0.0"
_MODEL_FIELDS = frozenset({"model_version", "scenario", "seed", "temperature_millidegrees"})
_PROMPT_FIELDS = frozenset(
    {
        "schema_version",
        "prompt_version",
        "purpose",
        "interface",
        "instructions",
        "plan_schema_version",
        "report_schema_version",
    }
)
_SOURCE_TO_TOOL = {
    EvidenceSourceType.DEPLOYMENT: "query_deployments",
    EvidenceSourceType.LOG: "query_logs",
    EvidenceSourceType.METRIC: "query_metrics",
    EvidenceSourceType.TRACE: "query_traces",
    EvidenceSourceType.TOPOLOGY: "get_service_topology",
}


@dataclass(frozen=True, slots=True)
class ControlledGraphTrace:
    node_authorizations: tuple[str, ...]
    tool_calls: tuple[str, ...]
    maximum_parallel_tools: int
    checkpoint_count: int
    final_phase: GraphPhase
    memory_reference_ids: tuple[str, ...]


class _Clock:
    def __init__(self) -> None:
        self._calls = 0

    def __call__(self) -> datetime:
        self._calls += 1
        return datetime(2026, 10, 29, tzinfo=UTC) + timedelta(microseconds=self._calls)


class _PromptAuthorization:
    def __init__(self, fingerprint: str) -> None:
        self._fingerprint = fingerprint
        self.nodes: list[str] = []

    async def require_approved(
        self, state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> None:
        del operation_id
        if (
            node_name not in DIAGNOSIS_NODE_NAMES
            or state.prompt.prompt_id != "diagnosis-evaluation-graph"
            or state.prompt.version != "1.0.0"
            or state.prompt.content_fingerprint != self._fingerprint
        ):
            raise EvaluationContractError("controlled graph prompt authorization failed")
        self.nodes.append(node_name)


class _Progress:
    async def record_plan(
        self,
        state: DiagnosisGraphState,
        *,
        plan: InvestigationPlan,
        calls: tuple[PlanToolCallReference, ...],
        model_call_id: str,
        next_state: DiagnosisGraphState,
        operation_id: str,
    ) -> None:
        del state, plan, calls, model_call_id, next_state, operation_id

    async def record_tool_status(
        self,
        state: DiagnosisGraphState,
        *,
        tool_call_id: str,
        status: ToolProgressStatus,
        failure_code: str | None,
        occurred_at: datetime,
        operation_id: str,
    ) -> None:
        del state, tool_call_id, status, failure_code, occurred_at, operation_id

    async def record_replan(
        self,
        state: DiagnosisGraphState,
        *,
        decision_fingerprint: str,
        reason_code: str,
        next_state: DiagnosisGraphState,
        operation_id: str,
    ) -> None:
        del state, decision_fingerprint, reason_code, next_state, operation_id

    async def record_state(self, state: DiagnosisGraphState, *, operation_id: str) -> None:
        del state, operation_id


class _Services:
    def __init__(
        self,
        case: EvaluationCase,
        configuration: CandidateExecutionConfig,
        model: DeterministicDiagnosisMockModel,
        seed: int,
        historical_context: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._case = case
        self._configuration = configuration
        self._model = model
        self._seed = seed
        self._context = (
            case.observation.alert_summary,
            *(signal.summary for signal in case.observation.signals),
            *(content for _, content in historical_context),
        )
        self.memory_reference_ids = tuple(reference_id for reference_id, _ in historical_context)
        self._observation_ids = tuple(
            f"observation-{case.case_id}-{index}-{signal.source}"
            for index, signal in enumerate(case.observation.signals, start=1)
        )
        self._calls: tuple[PlanToolCallReference, ...] = ()
        self._report: MockModelResult[DiagnosisReport] | None = None
        self.executed_tools: list[str] = []
        self.active_tools = 0
        self.maximum_parallel_tools = 0
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def report(self) -> MockModelResult[DiagnosisReport]:
        if self._report is None:
            raise EvaluationContractError("controlled graph did not produce a report")
        return self._report

    def _request(self, evidence_ids: tuple[str, ...]) -> MockDiagnosisRequest:
        return MockDiagnosisRequest(self._case.case_id, evidence_ids, self._context, self._seed)

    async def load_context(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> ContextLoadResult:
        del state, operation_id
        return ContextLoadResult(self._observation_ids)

    async def plan(self, state: DiagnosisGraphState, *, operation_id: str) -> PlanNodeResult:
        del operation_id
        model_result = await self._model.plan(self._request(state.evidence_ids))
        self.input_tokens += model_result.input_tokens
        self.output_tokens += model_result.output_tokens
        tools = dict(self._configuration.tool_schema_versions)
        calls = tuple(
            PlanToolCallReference(
                call_id=f"call-{self._case.case_id}-{step.step_id}",
                step_id=step.step_id,
                tool_name=_SOURCE_TO_TOOL[step.expected_source],
                tool_version=tools[_SOURCE_TO_TOOL[step.expected_source]],
            )
            for step in model_result.output.steps
        )
        fingerprints = tuple(
            hashlib.sha256(
                canonical_json(
                    {
                        "case_id": self._case.case_id,
                        "step_id": call.step_id,
                        "tool_name": call.tool_name,
                    }
                ).encode("utf-8")
            ).hexdigest()
            for call in calls
        )
        self._calls = calls
        return PlanNodeResult(
            f"model-plan-{self._case.case_id}",
            model_result.output,
            calls,
            fingerprints,
            len(calls),
            model_result.input_tokens + model_result.output_tokens,
            model_result.cost_nanounits,
        )

    async def load_tool_batches(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> tuple[tuple[str, ...], ...]:
        del operation_id
        pending = state.tool_call_ids[state.budgets.used_tool_calls :]
        return (pending,)

    async def execute_read_tool(
        self, state: DiagnosisGraphState, tool_call_id: str, *, operation_id: str
    ) -> None:
        del state, operation_id
        if tool_call_id not in {call.call_id for call in self._calls}:
            raise EvaluationContractError("controlled graph requested an unknown read tool")
        self.active_tools += 1
        self.maximum_parallel_tools = max(self.maximum_parallel_tools, self.active_tools)
        await asyncio.sleep(0)
        self.executed_tools.append(tool_call_id)
        self.active_tools -= 1

    async def persist_evidence(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> EvidencePersistenceResult:
        del operation_id
        completed = state.tool_call_ids[: state.budgets.used_tool_calls]
        return EvidencePersistenceResult(
            tuple(f"collected-{self._case.case_id}-{index}" for index, _ in enumerate(completed, 1))
        )

    async def hypothesize(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> HypothesisNodeResult:
        del operation_id
        self._report = await self._model.report(self._request(state.evidence_ids))
        self.input_tokens += self._report.input_tokens
        self.output_tokens += self._report.output_tokens
        return HypothesisNodeResult(
            f"model-hypothesis-{self._case.case_id}",
            self._report.input_tokens + self._report.output_tokens,
            self._report.cost_nanounits,
        )

    async def evaluate_evidence_gate(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> GateNodeResult:
        del state, operation_id
        candidate = self.report.output.candidates[0]
        document = {
            "case_id": self._case.case_id,
            "supporting_evidence_ids": list(candidate.supporting_evidence_ids),
            "route": "HANDOFF",
        }
        return GateNodeResult(
            hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest(),
            GateRoute.HUMAN_HANDOFF,
            "EVIDENCE_GATE_INDEPENDENT_SOURCES_MISSING",
        )

    async def record_handoff(self, state: DiagnosisGraphState, *, operation_id: str) -> None:
        del state, operation_id


class ControlledGraphDiagnosisSystem:
    """Evaluate a case through the real bounded Diagnosis LangGraph."""

    def __init__(
        self,
        *,
        model_settings_path: Path = DEFAULT_MODEL_SETTINGS,
        prompt_path: Path = DEFAULT_PROMPT,
        _profile_kind: str = "controlled-langgraph",
        _prompt_version: str = CONTROLLED_GRAPH_PROMPT_VERSION,
        _prompt_interface: str = "langgraph",
        _memory_access: bool = False,
    ) -> None:
        settings = load_json_object(model_settings_path)
        prompt = load_json_object(prompt_path)
        if frozenset(settings) != _MODEL_FIELDS or (
            settings["model_version"] != MOCK_MODEL_VERSION
            or settings["scenario"] != MockModelScenario.VALID.value
            or settings["seed"] != 7
            or settings["temperature_millidegrees"] != 0
        ):
            raise EvaluationContractError("controlled graph model settings are not predeclared")
        if frozenset(prompt) != _PROMPT_FIELDS or (
            prompt["schema_version"] != "1.0"
            or prompt["prompt_version"] != _prompt_version
            or prompt["purpose"] != "DIAGNOSIS"
            or prompt["interface"] != _prompt_interface
            or prompt["plan_schema_version"] != "1.0.0"
            or prompt["report_schema_version"] != "1.0.0"
            or not isinstance(prompt["instructions"], list)
            or not prompt["instructions"]
            or any(not isinstance(item, str) or not item for item in prompt["instructions"])
        ):
            raise EvaluationContractError("controlled graph prompt is not the approved version")
        self._settings_sha256 = content_sha256(settings)
        self._prompt_fingerprint = content_sha256(prompt)
        self._model = DeterministicDiagnosisMockModel(MockModelScenario.VALID)
        self._profile_kind = _profile_kind
        self._prompt_version = _prompt_version
        self._memory_access = _memory_access
        self.traces: dict[str, ControlledGraphTrace] = {}

    def _historical_context(self, case: EvaluationCase) -> tuple[tuple[str, str], ...]:
        del case
        return ()

    async def _evaluate(
        self, case: EvaluationCase, configuration: CandidateExecutionConfig
    ) -> tuple[DiagnosisGraphState, _Services, _PromptAuthorization, int]:
        services = _Services(
            case,
            configuration,
            self._model,
            7,
            historical_context=self._historical_context(case),
        )
        prompts = _PromptAuthorization(self._prompt_fingerprint)
        saver = InMemorySaver(serde=diagnosis_checkpoint_serializer())
        graph = build_diagnosis_graph(checkpointer=saver)
        state = DiagnosisGraphState(
            state_schema_version="1.3.0",
            graph_version="1.0.0",
            tenant_id="evaluation-tenant",
            incident_id=case.case_id,
            workflow_run_id=f"graph-{case.case_id}",
            correlation_id=f"correlation-{case.case_id}",
            causation_id=f"causation-{case.case_id}",
            phase=GraphPhase.CONTEXT_LOADING,
            budgets=GraphBudgetState(
                max_steps=8,
                used_steps=0,
                max_replans=1,
                used_replans=0,
                max_tool_calls=configuration.profile.budget.max_tool_calls,
                used_tool_calls=0,
                max_model_calls=4,
                used_model_calls=0,
                max_tokens=configuration.profile.budget.max_model_tokens,
                used_tokens=0,
                max_cost_nanounits=configuration.profile.budget.max_cost_microusd * 1_000,
                used_cost_nanounits=0,
            ),
            prompt=GraphPromptReference(
                prompt_id="diagnosis-evaluation-graph",
                version="1.0.0",
                content_fingerprint=self._prompt_fingerprint,
            ),
            checkpoint_sequence=0,
            updated_at=datetime(2026, 10, 29, tzinfo=UTC),
        )
        config = cast(
            RunnableConfig,
            {"configurable": {"thread_id": f"evaluation:{case.case_id}"}},
        )
        raw = await graph.ainvoke(
            state,
            config=config,
            context=DiagnosisRuntimeContext(services, prompts, _Progress(), _Clock()),
        )
        result = DiagnosisGraphState.model_validate(raw)
        checkpoints = [item async for item in saver.alist(config)]
        return result, services, prompts, len(checkpoints)

    def evaluate(
        self, case: EvaluationCase, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        profile = configuration.profile
        if (
            profile.kind != self._profile_kind
            or profile.baseline_version != CONTROLLED_GRAPH_BASELINE_VERSION
            or profile.orchestration != "langgraph"
            or profile.memory_access is not self._memory_access
            or profile.model_id != "diagnosis-mock"
            or profile.model_settings_sha256 != self._settings_sha256
            or profile.prompt_version != self._prompt_version
        ):
            raise EvaluationContractError(
                "controlled graph baseline requires its exact predeclared profile"
            )
        result, services, prompts, checkpoint_count = asyncio.run(
            self._evaluate(case, configuration)
        )
        report = services.report
        candidates = tuple(candidate.candidate_id for candidate in report.output.candidates)
        cited = tuple(
            dict.fromkeys(
                evidence_id
                for candidate in report.output.candidates
                for evidence_id in candidate.supporting_evidence_ids
            )
        )
        self.traces[case.case_id] = ControlledGraphTrace(
            tuple(prompts.nodes),
            tuple(services.executed_tools),
            services.maximum_parallel_tools,
            checkpoint_count,
            result.phase,
            services.memory_reference_ids,
        )
        if services.input_tokens + services.output_tokens != result.budgets.used_tokens:
            raise EvaluationContractError("controlled graph model usage does not match its budget")
        return {
            "case_id": case.case_id,
            "status": "handoff" if result.phase is GraphPhase.HUMAN_HANDOFF else "completed",
            "diagnosis_top3": list(candidates[:3]),
            "cited_evidence_ids": list(cited),
            "evidence_gate_outcome": "fail",
            "outcome_reason_code": result.error_code,
            "tool_calls": result.budgets.used_tool_calls,
            "input_tokens": services.input_tokens,
            "output_tokens": services.output_tokens,
            "cost_microusd": result.budgets.used_cost_nanounits // 1_000,
            "duration_ms": 0,
            "error_code": None,
        }
