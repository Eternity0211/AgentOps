"""Shared deterministic recovery-safety chain for every evaluation baseline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evaluation.fairness import CandidateExecutionConfig
from evaluation.tracks import RecoverySafetyInput


class DeterministicRecoverySafetySystem:
    """Apply the fixed schema/policy/approval/executor/verifier chain in order."""

    def evaluate(
        self, case: RecoverySafetyInput, configuration: CandidateExecutionConfig
    ) -> Mapping[str, Any]:
        del configuration
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
