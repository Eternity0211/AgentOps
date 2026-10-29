"""Single-pass model baseline without graph orchestration or incident memory."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agentops_incident_commander.infrastructure import (
    MOCK_MODEL_VERSION,
    DeterministicDiagnosisMockModel,
    MockDiagnosisRequest,
    MockModelResult,
    MockModelScenario,
)
from agentops_incident_commander.workflows import DiagnosisReport, InvestigationPlan
from evaluation.contracts import (
    EvaluationCase,
    EvaluationContractError,
    content_sha256,
    load_json_object,
)
from evaluation.fairness import CandidateExecutionConfig

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_SETTINGS = ROOT / "evaluation" / "models" / "v1" / "diagnosis-mock.json"
DEFAULT_PROMPT = ROOT / "evaluation" / "prompts" / "v1" / "single-agent.json"
SINGLE_AGENT_BASELINE_VERSION = "1.0.0"
SINGLE_AGENT_MODEL_ID = "diagnosis-mock"
SINGLE_AGENT_PROMPT_VERSION = "diagnosis-plan-v1.0.0"
_MODEL_SETTING_FIELDS = frozenset({"model_version", "scenario", "seed", "temperature_millidegrees"})
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


class SingleAgentDiagnosisSystem:
    """Invoke one deterministic plan/report pass and route gate failure to a human."""

    def __init__(
        self,
        *,
        model_settings_path: Path = DEFAULT_MODEL_SETTINGS,
        prompt_path: Path = DEFAULT_PROMPT,
    ) -> None:
        settings = load_json_object(model_settings_path)
        if frozenset(settings) != _MODEL_SETTING_FIELDS:
            raise EvaluationContractError("single-agent model settings use an unknown schema")
        if (
            settings["model_version"] != MOCK_MODEL_VERSION
            or settings["scenario"] != MockModelScenario.VALID.value
            or settings["seed"] != 7
            or settings["temperature_millidegrees"] != 0
        ):
            raise EvaluationContractError("single-agent model settings are not predeclared")
        prompt = load_json_object(prompt_path)
        if frozenset(prompt) != _PROMPT_FIELDS:
            raise EvaluationContractError("single-agent prompt uses an unknown schema")
        if (
            prompt["schema_version"] != "1.0"
            or prompt["prompt_version"] != SINGLE_AGENT_PROMPT_VERSION
            or prompt["purpose"] != "DIAGNOSIS"
            or prompt["interface"] != "single-pass"
            or prompt["plan_schema_version"] != "1.0.0"
            or prompt["report_schema_version"] != "1.0.0"
            or not isinstance(prompt["instructions"], list)
            or not prompt["instructions"]
            or any(not isinstance(item, str) or not item for item in prompt["instructions"])
        ):
            raise EvaluationContractError("single-agent prompt is not the approved version")
        self._settings_sha256 = content_sha256(settings)
        self._seed = 7
        self._model = DeterministicDiagnosisMockModel(MockModelScenario.VALID)

    @staticmethod
    async def _invoke(
        model: DeterministicDiagnosisMockModel, request: MockDiagnosisRequest
    ) -> tuple[MockModelResult[InvestigationPlan], MockModelResult[DiagnosisReport]]:
        plan = await model.plan(request)
        report = await model.report(request)
        return plan, report

    def evaluate(
        self, case: EvaluationCase, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        profile = configuration.profile
        if (
            profile.kind != "single-agent"
            or profile.baseline_version != SINGLE_AGENT_BASELINE_VERSION
            or profile.orchestration != "single-pass"
            or profile.memory_access
            or profile.model_id != SINGLE_AGENT_MODEL_ID
            or profile.model_settings_sha256 != self._settings_sha256
            or profile.prompt_version != SINGLE_AGENT_PROMPT_VERSION
        ):
            raise EvaluationContractError(
                "single-agent baseline requires its exact predeclared profile"
            )

        evidence_ids = tuple(
            f"observation-{case.case_id}-{index}-{signal.source}"
            for index, signal in enumerate(case.observation.signals, start=1)
        )
        context = (
            case.observation.alert_summary,
            *(signal.summary for signal in case.observation.signals),
        )
        request = MockDiagnosisRequest(case.case_id, evidence_ids, context, self._seed)
        plan, report = asyncio.run(self._invoke(self._model, request))
        candidates = tuple(candidate.candidate_id for candidate in report.output.candidates)
        cited = tuple(
            dict.fromkeys(
                evidence_id
                for candidate in report.output.candidates
                for evidence_id in candidate.supporting_evidence_ids
            )
        )

        # The mock report cites only one source. Confidence and schema validity cannot satisfy the
        # deterministic independent-source gate, so the model proposal never becomes authority.
        gate_passed = bool(report.output.candidates) and all(
            len(candidate.supporting_evidence_ids) >= 2
            and not candidate.missing_evidence
            and not candidate.counter_evidence_ids
            for candidate in report.output.candidates
        )
        return {
            "case_id": case.case_id,
            "status": "completed" if gate_passed else "handoff",
            "diagnosis_top3": list(candidates[:3]),
            "cited_evidence_ids": list(cited),
            "evidence_gate_outcome": "pass" if gate_passed else "fail",
            "outcome_reason_code": (
                None if gate_passed else "EVIDENCE_GATE_INDEPENDENT_SOURCES_MISSING"
            ),
            "tool_calls": 0,
            "input_tokens": plan.input_tokens + report.input_tokens,
            "output_tokens": plan.output_tokens + report.output_tokens,
            "cost_microusd": (plan.cost_nanounits + report.cost_nanounits) // 1_000,
            "duration_ms": 0,
            "error_code": None,
        }
