"""Diagnosis Agent outputs are finite, evidence-linked, and fail closed."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from agentops_incident_commander.domain import EvidenceId, EvidenceSourceType, IncidentId
from agentops_incident_commander.workflows import (
    DIAGNOSIS_PLAN_SCHEMA_VERSION,
    DIAGNOSIS_REPORT_SCHEMA_VERSION,
    MAX_CANDIDATE_EVIDENCE,
    MAX_INVESTIGATION_STEPS,
    MAX_MISSING_EVIDENCE,
    MAX_ROOT_CAUSE_CANDIDATES,
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


def test_schema_round_trips_are_strict_frozen_and_versioned() -> None:
    plan = InvestigationPlan(
        schema_version=DIAGNOSIS_PLAN_SCHEMA_VERSION,
        plan_id="plan-1",
        summary="Correlate metrics and traces.",
        steps=(step("metrics"),),
    )
    diagnosis = report(schema_version=DIAGNOSIS_REPORT_SCHEMA_VERSION)

    assert InvestigationPlan.model_validate_json(plan.model_dump_json()) == plan
    assert DiagnosisReport.model_validate_json(diagnosis.model_dump_json()) == diagnosis
    with pytest.raises(ValidationError, match="frozen"):
        plan.summary = "mutated"
    with pytest.raises(ValidationError, match="frozen"):
        diagnosis.explanation = "mutated"
    with pytest.raises(ValidationError):
        InvestigationPlan.model_validate({**plan.model_dump(), "schema_version": "2.0.0"})
    with pytest.raises(ValidationError):
        DiagnosisReport.model_validate({**diagnosis.model_dump(), "schema_version": "2.0.0"})


def test_schema_accepts_exact_collection_bounds_and_rejects_overflow() -> None:
    steps = tuple(
        step(f"step-{index}", depends_on=((f"step-{index - 1}",) if index else ()))
        for index in range(MAX_INVESTIGATION_STEPS)
    )
    plan = InvestigationPlan(
        schema_version=DIAGNOSIS_PLAN_SCHEMA_VERSION,
        plan_id="plan-max",
        summary="Maximum bounded investigation.",
        steps=steps,
    )
    candidates = tuple(
        candidate(candidate_id=f"candidate-{index}", rank=index + 1)
        for index in range(MAX_ROOT_CAUSE_CANDIDATES)
    )
    diagnosis = report(
        candidates=candidates,
        missing_evidence=tuple(f"missing-{index}" for index in range(MAX_MISSING_EVIDENCE)),
    )
    evidence_bound = candidate(
        supporting_evidence_ids=tuple(
            f"evidence-{index}" for index in range(MAX_CANDIDATE_EVIDENCE)
        )
    )

    assert len(plan.steps) == MAX_INVESTIGATION_STEPS
    assert len(diagnosis.candidates) == MAX_ROOT_CAUSE_CANDIDATES
    assert len(diagnosis.missing_evidence) == MAX_MISSING_EVIDENCE
    assert len(evidence_bound.supporting_evidence_ids) == MAX_CANDIDATE_EVIDENCE

    with pytest.raises(ValidationError):
        InvestigationPlan(
            schema_version=DIAGNOSIS_PLAN_SCHEMA_VERSION,
            plan_id="plan-overflow",
            summary="Too many steps.",
            steps=(*steps, step("overflow")),
        )
    with pytest.raises(ValidationError):
        report(
            candidates=(
                *candidates,
                candidate(candidate_id="candidate-overflow", rank=MAX_ROOT_CAUSE_CANDIDATES),
            )
        )
    with pytest.raises(ValidationError):
        report(
            disposition=DiagnosisDisposition.NEEDS_MORE_EVIDENCE,
            candidates=(),
            missing_evidence=tuple(f"missing-{index}" for index in range(MAX_MISSING_EVIDENCE + 1)),
        )
    with pytest.raises(ValidationError):
        candidate(
            supporting_evidence_ids=tuple(
                f"evidence-{index}" for index in range(MAX_CANDIDATE_EVIDENCE + 1)
            )
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: InvestigationStep.model_validate(
                {
                    **step("metrics").model_dump(),
                    "parallel_group": "0",
                }
            ),
            "valid integer",
        ),
        (
            lambda: RootCauseCandidate.model_validate(
                {**candidate().model_dump(), "confidence_basis_points": 1.0}
            ),
            "valid integer",
        ),
        (
            lambda: RootCauseCandidate.model_validate(
                {**candidate().model_dump(), "supporting_evidence_ids": []}
            ),
            "tuple",
        ),
        (
            lambda: InvestigationStep.model_validate(
                {**step("metrics").model_dump(), "shell_command": "shutdown"}
            ),
            "Extra inputs",
        ),
        (
            lambda: RootCauseCandidate.model_validate(
                {**candidate().model_dump(), "evidence_payload": "untrusted log content"}
            ),
            "Extra inputs",
        ),
    ],
)
def test_nested_agent_outputs_reject_coercion_and_authority_bearing_fields(
    factory: Any, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        factory()


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: InvestigationPlan(
                schema_version=DIAGNOSIS_PLAN_SCHEMA_VERSION,
                plan_id="plan-empty",
                summary="No steps.",
                steps=(),
            ),
            "at least 1",
        ),
        (
            lambda: step("bad step id"),
            "string_pattern_mismatch",
        ),
        (
            lambda: InvestigationStep(
                step_id="bad-group",
                objective="Collect bounded evidence.",
                expected_source=EvidenceSourceType.METRIC,
                depends_on=(),
                parallel_group=MAX_INVESTIGATION_STEPS + 1,
            ),
            "less than or equal",
        ),
        (
            lambda: candidate(supporting_evidence_ids=()),
            "at least 1",
        ),
        (
            lambda: candidate(confidence_basis_points=-1),
            "greater than or equal",
        ),
        (
            lambda: candidate(confidence_basis_points=10_001),
            "less than or equal",
        ),
    ],
)
def test_agent_schema_lower_upper_and_identifier_bounds(factory: Any, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        factory()


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
