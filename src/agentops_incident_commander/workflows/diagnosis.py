"""Strict structured outputs for the bounded Diagnosis Agent."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentops_incident_commander.domain import (
    EvidenceId,
    EvidenceSourceType,
    IncidentId,
    RootCauseEvidenceClaim,
)

DIAGNOSIS_PLAN_SCHEMA_VERSION = "1.0.0"
DIAGNOSIS_REPORT_SCHEMA_VERSION = "1.0.0"
MAX_INVESTIGATION_STEPS = 16
MAX_ROOT_CAUSE_CANDIDATES = 8
MAX_CANDIDATE_EVIDENCE = 32
MAX_MISSING_EVIDENCE = 16
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"

Identifier = Annotated[str, Field(pattern=_ID_PATTERN)]
BoundedText = Annotated[str, Field(min_length=1, max_length=512)]
ShortText = Annotated[str, Field(min_length=1, max_length=256)]


class StrictDiagnosisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CounterEvidenceTreatment(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class DiagnosisDisposition(StrEnum):
    CANDIDATES = "CANDIDATES"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    REFUSED = "REFUSED"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"


class InvestigationStep(StrictDiagnosisModel):
    step_id: Identifier
    objective: BoundedText
    expected_source: EvidenceSourceType
    depends_on: tuple[Identifier, ...] = Field(default=(), max_length=MAX_INVESTIGATION_STEPS)
    parallel_group: int = Field(ge=0, le=MAX_INVESTIGATION_STEPS)

    @field_validator("objective")
    @classmethod
    def normalize_objective(cls, value: str) -> str:
        return _bounded_text(value, field="investigation objective")

    @field_validator("depends_on")
    @classmethod
    def unique_dependencies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("investigation dependencies must be unique")
        return value


class InvestigationPlan(StrictDiagnosisModel):
    schema_version: Literal["1.0.0"]
    plan_id: Identifier
    summary: BoundedText
    steps: tuple[InvestigationStep, ...] = Field(min_length=1, max_length=MAX_INVESTIGATION_STEPS)

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        return _bounded_text(value, field="investigation summary")

    @model_validator(mode="after")
    def validate_step_graph(self) -> InvestigationPlan:
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in seen:
                raise ValueError("investigation step IDs must be unique")
            if step.step_id in step.depends_on:
                raise ValueError("investigation step cannot depend on itself")
            if any(dependency not in seen for dependency in step.depends_on):
                raise ValueError("investigation dependencies must reference earlier steps")
            seen.add(step.step_id)
        return self


class RootCauseCandidate(StrictDiagnosisModel):
    candidate_id: Identifier
    rank: int = Field(ge=1, le=MAX_ROOT_CAUSE_CANDIDATES)
    statement: BoundedText
    supporting_evidence_ids: tuple[Identifier, ...] = Field(
        min_length=1, max_length=MAX_CANDIDATE_EVIDENCE
    )
    counter_evidence_ids: tuple[Identifier, ...] = Field(
        default=(), max_length=MAX_CANDIDATE_EVIDENCE
    )
    counter_evidence_treatment: CounterEvidenceTreatment
    counter_evidence_explanation: ShortText | None = None
    missing_evidence: tuple[ShortText, ...] = Field(default=(), max_length=MAX_MISSING_EVIDENCE)
    uncertainty: ShortText
    confidence_basis_points: int = Field(ge=0, le=10_000)

    @field_validator("statement", "uncertainty", "counter_evidence_explanation")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return None if value is None else _bounded_text(value, field="diagnosis text")

    @field_validator("supporting_evidence_ids", "counter_evidence_ids", "missing_evidence")
    @classmethod
    def unique_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("diagnosis candidate references must be unique")
        return value

    @model_validator(mode="after")
    def validate_evidence_treatment(self) -> RootCauseCandidate:
        if set(self.supporting_evidence_ids) & set(self.counter_evidence_ids):
            raise ValueError("supporting and counter-evidence references must be disjoint")
        if not self.counter_evidence_ids:
            if self.counter_evidence_treatment is not CounterEvidenceTreatment.NOT_APPLICABLE:
                raise ValueError("counter-evidence treatment must be not applicable when absent")
            if self.counter_evidence_explanation is not None:
                raise ValueError("absent counter-evidence cannot have a treatment explanation")
        elif self.counter_evidence_treatment is CounterEvidenceTreatment.NOT_APPLICABLE:
            raise ValueError("present counter-evidence requires an explicit treatment")
        elif self.counter_evidence_explanation is None:
            raise ValueError("present counter-evidence requires an explanation")
        return self


class DiagnosisReport(StrictDiagnosisModel):
    schema_version: Literal["1.0.0"]
    incident_id: Identifier
    disposition: DiagnosisDisposition
    candidates: tuple[RootCauseCandidate, ...] = Field(
        default=(), max_length=MAX_ROOT_CAUSE_CANDIDATES
    )
    missing_evidence: tuple[ShortText, ...] = Field(default=(), max_length=MAX_MISSING_EVIDENCE)
    explanation: BoundedText

    @field_validator("missing_evidence")
    @classmethod
    def unique_missing_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("diagnosis report missing evidence must be unique")
        return value

    @field_validator("explanation")
    @classmethod
    def normalize_explanation(cls, value: str) -> str:
        return _bounded_text(value, field="diagnosis explanation")

    @model_validator(mode="after")
    def validate_disposition_and_ranks(self) -> DiagnosisReport:
        has_candidates = bool(self.candidates)
        if has_candidates != (self.disposition is DiagnosisDisposition.CANDIDATES):
            raise ValueError("candidate disposition must match candidate presence")
        if has_candidates:
            ranks = tuple(candidate.rank for candidate in self.candidates)
            if ranks != tuple(range(1, len(self.candidates) + 1)):
                raise ValueError("diagnosis candidate ranks must be consecutive and ordered")
            identities = {candidate.candidate_id for candidate in self.candidates}
            if len(identities) != len(self.candidates):
                raise ValueError("diagnosis candidate IDs must be unique")
        return self

    def evidence_gate_claim(self, candidate_id: str) -> RootCauseEvidenceClaim:
        candidate = next(
            (item for item in self.candidates if item.candidate_id == candidate_id), None
        )
        if candidate is None:
            raise ValueError("diagnosis candidate is not present in this report")
        return RootCauseEvidenceClaim(
            incident_id=IncidentId(self.incident_id),
            candidate_id=candidate.candidate_id,
            supporting_evidence_ids=tuple(
                EvidenceId(value) for value in candidate.supporting_evidence_ids
            ),
            counter_evidence_ids=tuple(
                EvidenceId(value) for value in candidate.counter_evidence_ids
            ),
            missing_evidence=candidate.missing_evidence,
            counter_evidence_resolved=(
                candidate.counter_evidence_treatment is not CounterEvidenceTreatment.UNRESOLVED
            ),
            model_confidence_basis_points=candidate.confidence_basis_points,
        )


def _bounded_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized or any(character in normalized for character in ("\r", "\n", "\x00")):
        raise ValueError(f"{field} must be bounded single-line text")
    return normalized
