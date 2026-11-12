from __future__ import annotations

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
