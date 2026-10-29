"""Conservative deterministic rules baseline for the two evaluation tracks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from evaluation.contracts import EvaluationCase, EvaluationContractError
from evaluation.fairness import CandidateExecutionConfig
from evaluation.tracks import RecoverySafetyInput

RULES_BASELINE_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class _ObservationRule:
    """One public observation pattern and its bounded human-handoff reason."""

    required_fragments: tuple[str, ...]
    reason_code: str

    def matches(self, observation_text: str) -> bool:
        return all(fragment in observation_text for fragment in self.required_fragments)


_OBSERVATION_RULES = (
    _ObservationRule(
        ("configuration-unavailable", "no service version transition"),
        "CONFIGURATION_ACTION_UNAVAILABLE",
    ),
    _ObservationRule(
        ("database acquisition duration", "before a postgresql command"),
        "POOL_CAPACITY_ACTION_UNAVAILABLE",
    ),
    _ObservationRule(
        ("payment client duration", "dominates the checkout critical path"),
        "DOWNSTREAM_LATENCY_ACTION_UNAVAILABLE",
    ),
    _ObservationRule(
        ("http 500 responses", "transitioned from version 1.0.0 to version 2.0.0"),
        "ROLLBACK_PREREQUISITES_MISSING",
    ),
    _ObservationRule(
        ("retained memory rises monotonically", "before growth began"),
        "ROLLBACK_PREREQUISITES_MISSING",
    ),
    _ObservationRule(
        ("redis timeout", "redis dependency boundary"),
        "DEPENDENCY_RECOVERY_ACTION_UNAVAILABLE",
    ),
)


def _require_rules_profile(configuration: CandidateExecutionConfig) -> None:
    profile = configuration.profile
    if (
        profile.kind != "rules"
        or profile.baseline_version != RULES_BASELINE_VERSION
        or profile.orchestration != "deterministic"
        or profile.memory_access
        or profile.model_id is not None
        or profile.model_settings_sha256 is not None
    ):
        raise EvaluationContractError("rules baseline requires its predeclared no-model profile")


class RulesDiagnosisSystem:
    """Return a label-free conservative handoff from bounded observation patterns."""

    def evaluate(
        self, case: EvaluationCase, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        _require_rules_profile(configuration)
        observation_text = " ".join(
            signal.summary.casefold() for signal in case.observation.signals
        )
        matches = tuple(rule for rule in _OBSERVATION_RULES if rule.matches(observation_text))
        reason = matches[0].reason_code if len(matches) == 1 else "EVIDENCE_INSUFFICIENT"
        return {
            "case_id": case.case_id,
            "status": "handoff",
            "diagnosis_top3": [],
            "cited_evidence_ids": [],
            "evidence_gate_outcome": "fail",
            "outcome_reason_code": reason,
            "tool_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_microusd": 0,
            "duration_ms": 0,
            "error_code": None,
        }


class DeterministicRecoverySafetySystem:
    """Apply the fixed schema/policy/approval/executor/verifier chain in order."""

    def evaluate(
        self, case: RecoverySafetyInput, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        _require_rules_profile(configuration)
        common: dict[str, Any] = {
            "case_id": case.case_id,
            "status": "handoff",
            "schema_validation_outcome": "pass",
            "policy_outcome": "denied",
            "approval_outcome": "not_requested",
            "executor_outcome": "not_run",
            "executed_actions": 0,
            "duplicate_executions": 0,
            "verification_outcome": "not_run",
            "final_route": "human_handoff",
            "tool_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_microusd": 0,
            "duration_ms": 0,
            "error_code": None,
        }
        if not case.proposal_schema_valid:
            common["schema_validation_outcome"] = "fail"
            return common
        if (
            case.proposal_action != "rollback_service"
            or case.evidence_gate_outcome != "pass"
            or not case.stable_predecessor_present
            or not case.target_allowlisted
        ):
            return common

        common["policy_outcome"] = "approval_required"
        if case.approval_input != "approved":
            return common

        common.update(
            {
                "status": "completed",
                "approval_outcome": "approved",
                "executor_outcome": "succeeded",
                "executed_actions": 1,
            }
        )
        if case.verification_profile == "stable":
            common.update({"verification_outcome": "pass", "final_route": "closed"})
        elif case.verification_profile == "unstable":
            common.update({"verification_outcome": "fail", "final_route": "rediagnose"})
        else:
            common.update(
                {
                    "status": "failed",
                    "verification_outcome": "not_run",
                    "final_route": "failed",
                    "error_code": "VERIFICATION_PROFILE_INVALID_AFTER_EXECUTION",
                }
            )
        return common
