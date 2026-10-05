"""Credential-free deterministic model adapter for Diagnosis workflow verification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import TypeVar

from pydantic import ValidationError

from agentops_incident_commander.domain import EvidenceSourceType, InvalidDomainValueError
from agentops_incident_commander.workflows import (
    CounterEvidenceTreatment,
    DiagnosisDisposition,
    DiagnosisReport,
    InvestigationPlan,
)

MOCK_MODEL_VERSION = "diagnosis-mock/1.0.0"
_MAX_CONTEXT_FRAGMENTS = 32
_MAX_FRAGMENT_LENGTH = 2_048
_IDENTIFIER_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")


class MockModelScenario(StrEnum):
    VALID = "VALID"
    MALFORMED = "MALFORMED"
    TIMEOUT = "TIMEOUT"
    REFUSAL = "REFUSAL"
    FABRICATED_REFERENCE = "FABRICATED_REFERENCE"
    INJECTION_RESISTANT = "INJECTION_RESISTANT"


class MockModelTimeout(TimeoutError):
    """Deterministic provider-timeout simulation without waiting."""


class MockModelRefusal(InvalidDomainValueError):
    """Typed refusal when a node has no schema-valid refusal output."""


class MockModelMalformedOutput(InvalidDomainValueError):
    """Strict-schema rejection of a deterministic malformed response."""


@dataclass(frozen=True, slots=True)
class MockDiagnosisRequest:
    incident_id: str
    evidence_ids: tuple[str, ...]
    context_fragments: tuple[str, ...] = ()
    seed: int = 0

    def __post_init__(self) -> None:
        identifiers = (self.incident_id, *self.evidence_ids)
        if any(
            not isinstance(value, str)
            or not 1 <= len(value) <= 128
            or value[0] not in _IDENTIFIER_CHARS
            or any(character not in _IDENTIFIER_CHARS for character in value)
            for value in identifiers
        ):
            raise InvalidDomainValueError("mock model identifiers are invalid")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise InvalidDomainValueError("mock model evidence references must be unique")
        if (
            not isinstance(self.context_fragments, tuple)
            or len(self.context_fragments) > _MAX_CONTEXT_FRAGMENTS
            or any(
                not isinstance(fragment, str)
                or not fragment
                or len(fragment) > _MAX_FRAGMENT_LENGTH
                for fragment in self.context_fragments
            )
        ):
            raise InvalidDomainValueError("mock model context fragments are invalid")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise InvalidDomainValueError("mock model seed must be a non-negative integer")


OutputT = TypeVar("OutputT", InvestigationPlan, DiagnosisReport)


@dataclass(frozen=True, slots=True)
class MockModelResult[OutputT]:
    output: OutputT
    model_version: str
    input_tokens: int
    output_tokens: int
    cost_nanounits: int
    response_fingerprint: str

    def __post_init__(self) -> None:
        if self.model_version != MOCK_MODEL_VERSION:
            raise InvalidDomainValueError("mock model version is invalid")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (self.input_tokens, self.output_tokens, self.cost_nanounits)
        ):
            raise InvalidDomainValueError("mock model usage is invalid")
        if (
            not isinstance(self.response_fingerprint, str)
            or len(self.response_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in self.response_fingerprint)
        ):
            raise InvalidDomainValueError("mock model response fingerprint is invalid")


class DeterministicDiagnosisMockModel:
    """Return fixed schema-bound outcomes; context text never controls behavior."""

    def __init__(self, scenario: MockModelScenario = MockModelScenario.VALID) -> None:
        if not isinstance(scenario, MockModelScenario):
            raise InvalidDomainValueError("mock model scenario is invalid")
        self._scenario = scenario

    async def plan(self, request: MockDiagnosisRequest) -> MockModelResult[InvestigationPlan]:
        self._require_request(request)
        self._raise_transport_outcome()
        if self._scenario is MockModelScenario.REFUSAL:
            raise MockModelRefusal("mock model refused diagnosis planning")
        payload: object = {
            "schema_version": "1.0.0",
            "plan_id": f"mock-plan-{request.seed}",
            "summary": "Collect bounded deployment and log evidence",
            "steps": [
                {
                    "step_id": "deployment",
                    "objective": "Check recent deployment changes",
                    "expected_source": EvidenceSourceType.DEPLOYMENT.value,
                    "depends_on": [],
                    "parallel_group": 0,
                },
                {
                    "step_id": "logs",
                    "objective": "Check correlated service errors",
                    "expected_source": EvidenceSourceType.LOG.value,
                    "depends_on": [],
                    "parallel_group": 0,
                },
            ],
        }
        if self._scenario is MockModelScenario.MALFORMED:
            payload = {"schema_version": "1.0.0", "plan_id": "malformed", "steps": []}
        return self._parse(payload, InvestigationPlan, request)

    async def report(self, request: MockDiagnosisRequest) -> MockModelResult[DiagnosisReport]:
        self._require_request(request)
        self._raise_transport_outcome()
        if self._scenario is MockModelScenario.REFUSAL:
            payload: object = {
                "schema_version": "1.0.0",
                "incident_id": request.incident_id,
                "disposition": DiagnosisDisposition.REFUSED.value,
                "candidates": [],
                "missing_evidence": [],
                "explanation": "Mock model refused to form a diagnosis",
            }
            return self._parse(payload, DiagnosisReport, request)
        if not request.evidence_ids:
            raise InvalidDomainValueError("mock diagnosis report requires evidence references")
        evidence_id = (
            "evidence-fabricated"
            if self._scenario is MockModelScenario.FABRICATED_REFERENCE
            else request.evidence_ids[0]
        )
        payload = {
            "schema_version": "1.0.0",
            "incident_id": request.incident_id,
            "disposition": DiagnosisDisposition.CANDIDATES.value,
            "candidates": [
                {
                    "candidate_id": "deployment-regression",
                    "rank": 1,
                    "statement": "A recent deployment is the leading bounded hypothesis",
                    "supporting_evidence_ids": [evidence_id],
                    "counter_evidence_ids": [],
                    "counter_evidence_treatment": CounterEvidenceTreatment.NOT_APPLICABLE.value,
                    "counter_evidence_explanation": None,
                    "missing_evidence": [],
                    "uncertainty": "The deterministic Evidence Gate remains authoritative",
                    "confidence_basis_points": 7000,
                }
            ],
            "missing_evidence": [],
            "explanation": "Candidate generated from bounded evidence references",
        }
        if self._scenario is MockModelScenario.MALFORMED:
            payload["candidates"] = [{"rank": 0}]
        return self._parse(payload, DiagnosisReport, request)

    @staticmethod
    def _require_request(request: MockDiagnosisRequest) -> None:
        if not isinstance(request, MockDiagnosisRequest):
            raise InvalidDomainValueError("mock model requires a typed request")

    def _raise_transport_outcome(self) -> None:
        if self._scenario is MockModelScenario.TIMEOUT:
            raise MockModelTimeout("deterministic mock timeout")

    @staticmethod
    def _parse(
        payload: object,
        schema: type[OutputT],
        request: MockDiagnosisRequest,
    ) -> MockModelResult[OutputT]:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        try:
            output = schema.model_validate_json(encoded)
        except ValidationError as error:
            raise MockModelMalformedOutput(
                "mock model response failed strict schema validation"
            ) from error
        input_tokens = 16 + len(request.evidence_ids) * 4 + len(request.context_fragments) * 8
        output_tokens = max(1, len(encoded.encode("utf-8")) // 4)
        return MockModelResult(
            output=output,
            model_version=MOCK_MODEL_VERSION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_nanounits=0,
            response_fingerprint=sha256(encoded.encode("utf-8")).hexdigest(),
        )
