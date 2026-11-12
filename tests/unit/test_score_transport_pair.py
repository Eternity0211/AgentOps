from __future__ import annotations

from typing import Any

from evaluation.audit_transport_followthrough import _case_audit
from evaluation.real_scoring import Outcome
from evaluation.score_transport_pair import _safe_control


def outcome(**changes: object) -> Outcome:
    values: dict[str, object] = {
        "instance_id": "instance-0000000000000001",
        "mode": "single-agent",
        "protocol_hash": "a" * 64,
        "input_hash": "b" * 64,
        "status": "SUCCEEDED",
        "candidates": (),
        "disposition": "HUMAN_HANDOFF",
        "missing_evidence_count": 1,
        "gate_pass": False,
        "proposal_created": False,
        "counter_evidence_addressed": False,
    }
    values.update(changes)
    return Outcome.model_validate(values)


def test_safe_control_failure_policy_and_counter_evidence() -> None:
    assert _safe_control("normal", outcome())
    assert _safe_control("insufficient-evidence", outcome())
    assert not _safe_control("insufficient-evidence", outcome(missing_evidence_count=0))
    assert _safe_control("counter-evidence", outcome(counter_evidence_addressed=True))
    assert not _safe_control("normal", outcome(status="FAILED", disposition=None))
    assert not _safe_control("http-500", outcome())


def test_repair_followthrough_audit_counts_failure_and_budget_decisions() -> None:
    events: list[dict[str, Any]] = [
        {"repair_attempt": 1, "status": "SUCCEEDED"},
        {"kind": "model-budget-decision", "decision": "HUMAN_HANDOFF"},
    ]
    assert _case_audit(events, failed=True) == {
        "successful_repair_outcomes": 1,
        "failed_after_successful_repair": 1,
        "budget_allow_decisions": 0,
        "budget_handoff_decisions": 1,
    }
    assert _case_audit([], failed=True)["failed_after_successful_repair"] == 0
