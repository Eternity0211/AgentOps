from __future__ import annotations

import hashlib

import pytest
from evaluation.gate_reason_audit import (
    GateAuditRun,
    GateDecisionAudit,
    summarize_gate_audit,
)
from evaluation.rcaeval_contract import (
    FileBinding,
    Modality,
    TaskIndex,
    TaskManifest,
    load_protocol,
    protocol_sha256,
)
from pydantic import ValidationError

from agentops_incident_commander.domain import EvidenceGateOutcome, EvidenceGateReasonCode


def _task_index() -> TaskIndex:
    protocol = load_protocol()
    files = tuple(
        FileBinding(
            modality=modality,
            file_name=f"{modality.value}.parquet",
            sha256="1" * 64,
            size_bytes=1,
            available=True,
        )
        for modality in Modality
    )
    tasks = tuple(
        TaskManifest(
            schema_version="rcaeval-task/1.0.0",
            protocol_id=protocol.protocol_id,
            protocol_sha256=protocol_sha256(protocol),
            case_id=f"re2-ob-{index:016x}",
            split_role="DEVELOPMENT",
            system="ONLINE_BOUTIQUE",
            observation_start_unix_s=1,
            injection_time_unix_s=2,
            observation_end_unix_s=3,
            candidate_services=protocol.splits[0].candidate_services,
            files=files,
        )
        for index in range(2)
    )
    return TaskIndex(
        schema_version="rcaeval-task-index/1.0.0",
        protocol_sha256=protocol_sha256(protocol),
        source_index_sha256=protocol.source.index_sha256,
        tasks=tasks,
    )


def test_gate_audit_retains_reason_codes_and_not_evaluated_cases() -> None:
    protocol = load_protocol()
    task_index = _task_index()
    task_hash = hashlib.sha256(b"tasks").hexdigest()
    audit = GateAuditRun(
        schema_version="gate-reason-audit/1.0.0",
        audit_id="audit-1",
        localization_run_id="run-1",
        split_role="DEVELOPMENT",
        protocol_sha256=protocol_sha256(protocol),
        task_index_sha256=task_hash,
        rules_version="1.1.0",
        decisions=(
            GateDecisionAudit(
                case_id=task_index.tasks[0].case_id,
                status="EVALUATED",
                outcome=EvidenceGateOutcome.FAIL,
                reason_codes=(
                    EvidenceGateReasonCode.EVIDENCE_STALE,
                    EvidenceGateReasonCode.MISSING_EVIDENCE_DECLARED,
                ),
                evaluated_evidence_count=2,
                decision_fingerprint="a" * 64,
            ),
            GateDecisionAudit(
                case_id=task_index.tasks[1].case_id,
                status="NOT_EVALUATED",
                outcome=None,
                reason_codes=(),
                evaluated_evidence_count=0,
            ),
        ),
    )

    summary = summarize_gate_audit(
        audit,
        task_index=task_index,
        expected_protocol_sha256=protocol_sha256(protocol),
        expected_task_index_sha256=task_hash,
    )

    assert (summary.passed, summary.failed, summary.not_evaluated) == (0, 1, 1)
    assert {item.reason_code: item.count for item in summary.reason_counts} == {
        EvidenceGateReasonCode.EVIDENCE_STALE: 1,
        EvidenceGateReasonCode.MISSING_EVIDENCE_DECLARED: 1,
    }


@pytest.mark.parametrize(
    "values",
    [
        {
            "status": "EVALUATED",
            "outcome": EvidenceGateOutcome.PASS,
            "reason_codes": (EvidenceGateReasonCode.EVIDENCE_STALE,),
            "evaluated_evidence_count": 1,
            "decision_fingerprint": "a" * 64,
        },
        {
            "status": "EVALUATED",
            "outcome": EvidenceGateOutcome.FAIL,
            "reason_codes": (),
            "evaluated_evidence_count": 1,
            "decision_fingerprint": "a" * 64,
        },
        {
            "status": "NOT_EVALUATED",
            "outcome": EvidenceGateOutcome.FAIL,
            "reason_codes": (EvidenceGateReasonCode.EVIDENCE_STALE,),
            "evaluated_evidence_count": 1,
            "decision_fingerprint": "a" * 64,
        },
    ],
)
def test_gate_audit_refuses_inconsistent_decisions(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GateDecisionAudit(case_id="re2-ob-0000000000000000", **values)  # type: ignore[arg-type]


def test_gate_audit_requires_exact_split_and_bindings() -> None:
    protocol = load_protocol()
    task_index = _task_index()
    audit = GateAuditRun(
        schema_version="gate-reason-audit/1.0.0",
        audit_id="audit-1",
        localization_run_id="run-1",
        split_role="DEVELOPMENT",
        protocol_sha256=protocol_sha256(protocol),
        task_index_sha256="1" * 64,
        rules_version="1.1.0",
        decisions=(),
    )
    with pytest.raises(ValueError, match="cover"):
        summarize_gate_audit(
            audit,
            task_index=task_index,
            expected_protocol_sha256=protocol_sha256(protocol),
            expected_task_index_sha256="1" * 64,
        )
    with pytest.raises(ValueError, match="protocol"):
        summarize_gate_audit(
            audit,
            task_index=task_index,
            expected_protocol_sha256="2" * 64,
            expected_task_index_sha256="1" * 64,
        )
