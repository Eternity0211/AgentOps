"""Label-free Evidence Gate reason-code sidecars for future evaluation runs."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import Field, model_validator

from agentops_incident_commander.domain import EvidenceGateOutcome, EvidenceGateReasonCode
from evaluation.rcaeval_contract import StrictModel, TaskIndex


class GateDecisionAudit(StrictModel):
    case_id: str = Field(pattern=r"^re2-(ob|tt)-[0-9a-f]{16}$")
    status: Literal["EVALUATED", "NOT_EVALUATED"]
    outcome: EvidenceGateOutcome | None
    reason_codes: tuple[EvidenceGateReasonCode, ...]
    evaluated_evidence_count: int = Field(ge=0, le=128)
    decision_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_decision(self) -> GateDecisionAudit:
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("Gate reason codes must be unique")
        if self.status == "NOT_EVALUATED":
            if (
                self.outcome is not None
                or self.reason_codes
                or self.evaluated_evidence_count
                or self.decision_fingerprint is not None
            ):
                raise ValueError("non-evaluated Gate audit cannot contain a decision")
            return self
        if self.outcome is None or self.decision_fingerprint is None:
            raise ValueError("evaluated Gate audit requires outcome and decision fingerprint")
        if self.outcome is EvidenceGateOutcome.PASS and self.reason_codes:
            raise ValueError("passing Gate audit cannot contain failure reasons")
        if self.outcome is EvidenceGateOutcome.FAIL and not self.reason_codes:
            raise ValueError("failed Gate audit requires reason codes")
        return self


class GateAuditRun(StrictModel):
    schema_version: Literal["gate-reason-audit/1.0.0"]
    audit_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    localization_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    split_role: Literal["DEVELOPMENT", "HOLDOUT"]
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rules_version: Literal["1.1.0"]
    decisions: tuple[GateDecisionAudit, ...]

    @model_validator(mode="after")
    def unique_cases(self) -> GateAuditRun:
        identifiers = [item.case_id for item in self.decisions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Gate audit case IDs must be unique")
        return self


class ReasonCount(StrictModel):
    reason_code: EvidenceGateReasonCode
    count: int = Field(gt=0)


class GateAuditSummary(StrictModel):
    schema_version: Literal["gate-reason-summary/1.0.0"]
    audit_id: str
    localization_run_id: str
    split_role: Literal["DEVELOPMENT", "HOLDOUT"]
    total_cases: int = Field(gt=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    not_evaluated: int = Field(ge=0)
    reason_counts: tuple[ReasonCount, ...]


def summarize_gate_audit(
    audit: GateAuditRun,
    *,
    task_index: TaskIndex,
    expected_protocol_sha256: str,
    expected_task_index_sha256: str,
) -> GateAuditSummary:
    if audit.protocol_sha256 != expected_protocol_sha256:
        raise ValueError("Gate audit protocol binding mismatch")
    if audit.task_index_sha256 != expected_task_index_sha256:
        raise ValueError("Gate audit task-index binding mismatch")
    expected = {task.case_id for task in task_index.tasks if task.split_role == audit.split_role}
    observed = {item.case_id for item in audit.decisions}
    if observed != expected:
        raise ValueError("Gate audit must cover the selected task split exactly")
    counts: Counter[EvidenceGateReasonCode] = Counter(
        reason for item in audit.decisions for reason in item.reason_codes
    )
    return GateAuditSummary(
        schema_version="gate-reason-summary/1.0.0",
        audit_id=audit.audit_id,
        localization_run_id=audit.localization_run_id,
        split_role=audit.split_role,
        total_cases=len(expected),
        passed=sum(item.outcome is EvidenceGateOutcome.PASS for item in audit.decisions),
        failed=sum(item.outcome is EvidenceGateOutcome.FAIL for item in audit.decisions),
        not_evaluated=sum(item.status == "NOT_EVALUATED" for item in audit.decisions),
        reason_counts=tuple(
            ReasonCount(reason_code=code, count=count)
            for code, count in sorted(counts.items(), key=lambda item: item[0].value)
        ),
    )
