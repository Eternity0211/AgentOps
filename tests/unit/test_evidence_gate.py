"""Versioned deterministic Evidence Gate contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.domain import (
    EVIDENCE_GATE_SCHEMA_VERSION,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceGateReason,
    EvidenceGateReasonCode,
    EvidenceGateRules,
    EvidenceId,
    IncidentId,
    InvalidDomainValueError,
    RootCauseEvidenceClaim,
    Sha256Digest,
)

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
E1 = EvidenceId("evidence-1")
E2 = EvidenceId("evidence-2")
E3 = EvidenceId("evidence-3")
DIGEST = Sha256Digest("a" * 64)


def claim(**overrides: Any) -> RootCauseEvidenceClaim:
    values: dict[str, Any] = {
        "incident_id": IncidentId("incident-gate"),
        "candidate_id": "candidate-database-pool",
        "supporting_evidence_ids": (E2, E1),
    }
    values.update(overrides)
    return RootCauseEvidenceClaim(**values)


def reason(
    code: EvidenceGateReasonCode = EvidenceGateReasonCode.EVIDENCE_STALE,
    evidence_ids: tuple[EvidenceId, ...] = (E1,),
) -> EvidenceGateReason:
    return EvidenceGateReason(code, "Evidence is older than the configured window.", evidence_ids)


def decision(**overrides: Any) -> EvidenceGateDecision:
    values: dict[str, Any] = {
        "incident_id": IncidentId("incident-gate"),
        "candidate_id": "candidate-database-pool",
        "outcome": EvidenceGateOutcome.FAIL,
        "reasons": (reason(),),
        "evaluated_evidence_ids": (E2, E1),
        "rules_version": "1.0.0",
        "input_fingerprint": DIGEST,
        "evaluated_at": NOW,
    }
    values.update(overrides)
    return EvidenceGateDecision(**values)


def test_default_rules_are_versioned_bounded_and_deterministic() -> None:
    rules = EvidenceGateRules()
    assert rules.version == "1.1.0"
    assert rules.schema_version == EVIDENCE_GATE_SCHEMA_VERSION
    assert rules.minimum_quality_basis_points == 7_000
    assert rules.maximum_evidence_age == timedelta(hours=1)
    assert rules.minimum_independent_sources == 2
    assert rules.require_counter_evidence_resolution is True
    assert rules.fail_on_declared_missing_evidence is True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"version": "v1"}, "version"),
        ({"schema_version": "2.0.0"}, "schema version"),
        ({"minimum_quality_basis_points": -1}, "quality"),
        ({"minimum_quality_basis_points": True}, "quality"),
        ({"minimum_quality_basis_points": 10_001}, "quality"),
        ({"maximum_evidence_age": timedelta(0)}, "maximum age"),
        ({"maximum_evidence_age": timedelta(days=31)}, "maximum age"),
        ({"maximum_evidence_age": cast(timedelta, 1)}, "maximum age"),
        ({"minimum_independent_sources": 0}, "independent"),
        ({"minimum_independent_sources": True}, "independent"),
        ({"minimum_independent_sources": 9}, "independent"),
        ({"require_counter_evidence_resolution": 1}, "flags"),
        ({"fail_on_declared_missing_evidence": 0}, "flags"),
    ],
)
def test_rules_reject_invalid_values(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        EvidenceGateRules(**overrides)


def test_claim_normalizes_references_and_keeps_confidence_metadata_non_authoritative() -> None:
    low = claim(
        counter_evidence_ids=(E3,),
        missing_evidence=("Need a deployment marker",),
        counter_evidence_resolved=True,
        model_confidence_basis_points=1,
    )
    high = replace(low, model_confidence_basis_points=10_000)
    assert low.supporting_evidence_ids == (E1, E2)
    assert low.all_evidence_ids == (E1, E2, E3)
    assert high.all_evidence_ids == low.all_evidence_ids
    assert high.counter_evidence_resolved == low.counter_evidence_resolved
    assert high.missing_evidence == low.missing_evidence


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"candidate_id": ""}, "candidate ID"),
        ({"candidate_id": "candidate\nforged"}, "candidate ID"),
        ({"supporting_evidence_ids": ()}, "requires supporting"),
        ({"supporting_evidence_ids": (E1, E1)}, "unique"),
        ({"supporting_evidence_ids": cast(tuple[EvidenceId, ...], [E1])}, "exceed"),
        ({"supporting_evidence_ids": (cast(EvidenceId, "bad"),)}, "invalid"),
        ({"counter_evidence_ids": (E1,)}, "disjoint"),
        ({"missing_evidence": ("same", "same")}, "missing evidence must be unique"),
        ({"missing_evidence": ("x",) * 17}, "count"),
        ({"counter_evidence_resolved": 1}, "resolution"),
        ({"model_confidence_basis_points": -1}, "confidence"),
        ({"model_confidence_basis_points": True}, "confidence"),
        ({"model_confidence_basis_points": 10_001}, "confidence"),
    ],
)
def test_claim_rejects_invalid_references_and_metadata(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        claim(**overrides)


def test_reason_is_typed_bounded_and_normalized() -> None:
    value = EvidenceGateReason(
        EvidenceGateReasonCode.QUALITY_BELOW_FLOOR,
        " Quality is below the configured floor. ",
        (E2, E1),
    )
    assert value.detail == "Quality is below the configured floor."
    assert value.evidence_ids == (E1, E2)
    with pytest.raises(InvalidDomainValueError, match="reason code"):
        replace(value, code=cast(EvidenceGateReasonCode, "STALE"))
    with pytest.raises(InvalidDomainValueError, match="reason detail"):
        replace(value, detail="")


def test_decision_enforces_outcome_reason_and_input_snapshot_invariants() -> None:
    failed = decision(model_confidence_basis_points=9_999)
    assert failed.evaluated_evidence_ids == (E1, E2)
    assert failed.evaluated_at == NOW
    passed = decision(outcome=EvidenceGateOutcome.PASS, reasons=())
    assert passed.outcome is EvidenceGateOutcome.PASS
    assert passed.reasons == ()
    assert passed.model_confidence_basis_points is None
    for overrides, message in (
        ({"outcome": cast(EvidenceGateOutcome, "ALLOW")}, "outcome"),
        ({"schema_version": "2.0.0"}, "schema version"),
        ({"rules_version": "latest"}, "rules version"),
        ({"reasons": cast(tuple[EvidenceGateReason, ...], [reason()])}, "reasons"),
        ({"outcome": EvidenceGateOutcome.PASS}, "cannot have failures"),
        ({"reasons": ()}, "require reasons"),
        ({"reasons": (reason(), reason())}, "reasons must be unique"),
        ({"evaluated_evidence_ids": (E1, E1)}, "unique"),
        ({"model_confidence_basis_points": -1}, "confidence"),
        ({"model_confidence_basis_points": True}, "confidence"),
        ({"model_confidence_basis_points": 10_001}, "confidence"),
    ):
        with pytest.raises(InvalidDomainValueError, match=message):
            decision(**overrides)
