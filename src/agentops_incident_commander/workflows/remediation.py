"""Strict structured output for the bounded Remediation Agent."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentops_incident_commander.domain import Sha256Digest

REMEDIATION_PROPOSAL_SCHEMA_VERSION: Final[Literal["1.0.0"]] = "1.0.0"
MAX_REMEDIATION_RISK_ASSUMPTIONS = 8
MAX_REDIAGNOSIS_ATTEMPTS = 3
MIN_STABILITY_WINDOW_SECONDS = 60
MAX_STABILITY_WINDOW_SECONDS = 3_600

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"

Identifier = Annotated[str, Field(pattern=_ID_PATTERN)]
Fingerprint = Annotated[str, Field(pattern=_SHA256_PATTERN)]
RiskAssumption = Annotated[str, Field(min_length=1, max_length=512)]


class StrictRemediationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RecoveryAction(StrEnum):
    ROLLBACK_SERVICE = "rollback_service"


class RemediationFailureRoute(StrEnum):
    BOUNDED_REDIAGNOSIS_THEN_HUMAN_HANDOFF = "BOUNDED_REDIAGNOSIS_THEN_HUMAN_HANDOFF"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"


class RollbackServiceParameters(StrictRemediationModel):
    """Model-selected scope; versions remain server-owned and are deliberately absent."""

    service: Identifier
    introducing_deployment_evidence_id: Identifier


class RollbackPrerequisites(StrictRemediationModel):
    current_version_evidence_id: Identifier
    require_server_resolved_stable_predecessor: Literal[True] = True
    require_policy_authorization: Literal[True] = True
    require_human_approval: Literal[True] = True
    require_execution_lock: Literal[True] = True


class RollbackVerificationConditions(StrictRemediationModel):
    max_error_rate_basis_points: int = Field(ge=0, le=10_000)
    max_p95_latency_ms: int = Field(ge=1, le=300_000)
    require_healthy_endpoint: Literal[True] = True
    require_server_resolved_stable_version: Literal[True] = True
    maximum_new_alerts: Literal[0] = 0
    stability_window_seconds: int = Field(
        ge=MIN_STABILITY_WINDOW_SECONDS,
        le=MAX_STABILITY_WINDOW_SECONDS,
    )


class RemediationFailureHandling(StrictRemediationModel):
    route: RemediationFailureRoute
    max_rediagnosis_attempts: int = Field(ge=0, le=MAX_REDIAGNOSIS_ATTEMPTS)
    redeploy_faulty_version: Literal[False] = False

    @model_validator(mode="after")
    def validate_route_budget(self) -> RemediationFailureHandling:
        bounded = self.route is RemediationFailureRoute.BOUNDED_REDIAGNOSIS_THEN_HUMAN_HANDOFF
        if bounded != (self.max_rediagnosis_attempts > 0):
            raise ValueError("remediation failure route must match the re-diagnosis budget")
        return self


class RemediationProposal(StrictRemediationModel):
    schema_version: Literal["1.0.0"]
    proposal_id: Identifier
    proposal_version: int = Field(ge=1, le=1_000_000)
    incident_id: Identifier
    candidate_id: Identifier
    evidence_gate_input_fingerprint: Fingerprint
    evidence_gate_decision_fingerprint: Fingerprint
    action: Literal[RecoveryAction.ROLLBACK_SERVICE]
    parameters: RollbackServiceParameters
    prerequisites: RollbackPrerequisites
    verification_conditions: RollbackVerificationConditions
    failure_handling: RemediationFailureHandling
    compensation_eligible: Literal[False] = False
    risk_assumptions: tuple[RiskAssumption, ...] = Field(
        min_length=1,
        max_length=MAX_REMEDIATION_RISK_ASSUMPTIONS,
    )

    @field_validator("risk_assumptions")
    @classmethod
    def normalize_risk_assumptions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_single_line(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("remediation risk assumptions must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_evidence_references(self) -> RemediationProposal:
        if (
            self.parameters.introducing_deployment_evidence_id
            == self.prerequisites.current_version_evidence_id
        ):
            raise ValueError("remediation deployment and current-version evidence must differ")
        return self

    @property
    def fingerprint(self) -> Sha256Digest:
        document = self.model_dump(mode="json")
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(canonical).hexdigest())

    @property
    def material_fingerprint(self) -> Sha256Digest:
        """Hash every proposal field except its monotonically increasing version."""

        document = self.model_dump(mode="json", exclude={"proposal_version"})
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(canonical).hexdigest())


def _single_line(value: str) -> str:
    normalized = value.strip()
    if not normalized or any(character in normalized for character in ("\r", "\n", "\x00")):
        raise ValueError("remediation risk assumption must be bounded single-line text")
    return normalized
