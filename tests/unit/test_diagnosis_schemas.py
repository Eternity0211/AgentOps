"""Diagnosis Agent outputs are finite, evidence-linked, and fail closed."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from agentops_incident_commander.domain import EvidenceId, EvidenceSourceType, IncidentId
from agentops_incident_commander.workflows import (
    CounterEvidenceTreatment,
    DiagnosisDisposition,
    DiagnosisReport,
    InvestigationPlan,
    InvestigationStep,
    RootCauseCandidate,
)


def step(step_id: str, *, depends_on: tuple[str, ...] = ()) -> InvestigationStep:
    return InvestigationStep(
        step_id=step_id,
        objective=f"Collect evidence for {step_id}",
        expected_source=EvidenceSourceType.METRIC,
        depends_on=depends_on,
        parallel_group=0,
    )


def candidate(**overrides: Any) -> RootCauseCandidate:
    values: dict[str, object] = {
        "candidate_id": "candidate-db-pool",
        "rank": 1,
        "statement": "Database pool exhaustion caused request failures.",
        "supporting_evidence_ids": ("evidence-metric", "evidence-log"),
        "counter_evidence_ids": ("evidence-trace",),
        "counter_evidence_treatment": CounterEvidenceTreatment.RESOLVED,
        "counter_evidence_explanation": "Trace errors begin after pool saturation.",
        "missing_evidence": ("Need deployment marker",),
        "uncertainty": "Pool telemetry is sampled.",
        "confidence_basis_points": 8200,
    }
    values.update(overrides)
    return RootCauseCandidate.model_validate(values)


def report(**overrides: Any) -> DiagnosisReport:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "incident_id": "incident-1",
        "disposition": DiagnosisDisposition.CANDIDATES,
        "candidates": (candidate(),),
        "missing_evidence": (),
        "explanation": "One evidence-linked candidate remains.",
    }
    values.update(overrides)
    return DiagnosisReport.model_validate(values)


def test_plan_is_finite_ordered_and_content_free() -> None:
    plan = InvestigationPlan(
        schema_version="1.0.0",
        plan_id="plan-1",
        summary="Correlate metrics and traces.",
        steps=(step("metrics"), step("traces", depends_on=("metrics",))),
    )
    assert plan.steps[1].depends_on == ("metrics",)
    assert not hasattr(plan.steps[0], "command")
    assert not hasattr(plan.steps[0], "url")
    with pytest.raises(ValidationError, match="Extra inputs"):
        InvestigationPlan.model_validate({**plan.model_dump(), "prompt": "ignore policy"})


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ((step("same"), step("same")), "IDs"),
        ((step("self", depends_on=("self",)),), "itself"),
        ((step("later", depends_on=("missing",)),), "earlier"),
    ],
)
def test_plan_rejects_duplicate_self_or_forward_dependencies(
    steps: tuple[InvestigationStep, ...], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        InvestigationPlan(
            schema_version="1.0.0", plan_id="plan-1", summary="Bounded plan", steps=steps
        )


def test_step_rejects_duplicate_dependencies_and_unsafe_text() -> None:
    with pytest.raises(ValidationError, match="unique"):
        step("traces", depends_on=("metrics", "metrics"))
    with pytest.raises(ValidationError, match="single-line"):
        InvestigationStep(
            step_id="bad",
            objective="ignore\npolicy",
            expected_source=EvidenceSourceType.LOG,
            depends_on=(),
            parallel_group=0,
        )


def test_candidate_converts_deterministically_to_evidence_gate_claim() -> None:
    value = report()
    claim = value.evidence_gate_claim("candidate-db-pool")
    assert claim.incident_id == IncidentId("incident-1")
    assert claim.supporting_evidence_ids == (
        EvidenceId("evidence-log"),
        EvidenceId("evidence-metric"),
    )
    assert claim.counter_evidence_ids == (EvidenceId("evidence-trace"),)
    assert claim.counter_evidence_resolved
    assert claim.model_confidence_basis_points == 8200
    with pytest.raises(ValueError, match="not present"):
        value.evidence_gate_claim("candidate-missing")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"supporting_evidence_ids": ("same",), "counter_evidence_ids": ("same",)},
            "disjoint",
        ),
        (
            {
                "counter_evidence_ids": (),
                "counter_evidence_treatment": CounterEvidenceTreatment.RESOLVED,
                "counter_evidence_explanation": None,
            },
            "not applicable",
        ),
        (
            {
                "counter_evidence_ids": (),
                "counter_evidence_treatment": CounterEvidenceTreatment.NOT_APPLICABLE,
                "counter_evidence_explanation": "not needed",
            },
            "cannot have",
        ),
        (
            {"counter_evidence_treatment": CounterEvidenceTreatment.NOT_APPLICABLE},
            "explicit treatment",
        ),
        ({"counter_evidence_explanation": None}, "requires an explanation"),
        ({"supporting_evidence_ids": ("same", "same")}, "unique"),
        ({"missing_evidence": ("same", "same")}, "unique"),
        ({"statement": " \n "}, "single-line"),
    ],
)
def test_candidate_rejects_inconsistent_evidence_and_text(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        candidate(**overrides)


def test_unresolved_counter_evidence_remains_unresolved_in_gate_claim() -> None:
    unresolved = candidate(
        counter_evidence_treatment=CounterEvidenceTreatment.UNRESOLVED,
        counter_evidence_explanation="Conflicting trace has not been explained.",
    )
    value = report(candidates=(unresolved,))
    assert not value.evidence_gate_claim(unresolved.candidate_id).counter_evidence_resolved

    no_counter = candidate(
        counter_evidence_ids=(),
        counter_evidence_treatment=CounterEvidenceTreatment.NOT_APPLICABLE,
        counter_evidence_explanation=None,
    )
    assert (
        report(candidates=(no_counter,))
        .evidence_gate_claim(no_counter.candidate_id)
        .counter_evidence_resolved
    )


@pytest.mark.parametrize(
    "disposition",
    [
        DiagnosisDisposition.NEEDS_MORE_EVIDENCE,
        DiagnosisDisposition.REFUSED,
        DiagnosisDisposition.HUMAN_HANDOFF,
    ],
)
def test_non_candidate_dispositions_cannot_smuggle_conclusions(
    disposition: DiagnosisDisposition,
) -> None:
    value = report(
        disposition=disposition,
        candidates=(),
        missing_evidence=("Need another independent source",),
    )
    assert not value.candidates
    with pytest.raises(ValidationError, match="match candidate presence"):
        report(disposition=disposition)


def test_report_rejects_empty_candidate_disposition_bad_ranks_and_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="match candidate presence"):
        report(candidates=())
    second = candidate(candidate_id="candidate-config", rank=3)
    with pytest.raises(ValidationError, match="consecutive"):
        report(candidates=(candidate(), second))
    duplicate = candidate(rank=2)
    with pytest.raises(ValidationError, match="IDs"):
        report(candidates=(candidate(), duplicate))


def test_report_rejects_duplicate_missing_evidence_and_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="unique"):
        report(missing_evidence=("same", "same"))
    with pytest.raises(ValidationError, match="Extra inputs"):
        DiagnosisReport.model_validate({**report().model_dump(), "shell_command": "rm"})
    with pytest.raises(ValidationError):
        RootCauseCandidate.model_validate(
            {**candidate().model_dump(), "confidence_basis_points": cast(Any, 10_001)}
        )
