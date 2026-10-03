"""Typed immutable Evidence records and resolvable Artifact binding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .artifacts import Artifact
from .errors import ArtifactIntegrityError, InvalidDomainValueError
from .values import (
    ArtifactId,
    EvidenceId,
    IncidentId,
    RedactionTransformId,
    Sha256Digest,
    TenantId,
    ToolCallId,
    WorkflowRunId,
    as_utc,
)

EVIDENCE_SCHEMA_VERSION = "1.0.0"
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class EvidenceSourceType(StrEnum):
    METRIC = "METRIC"
    LOG = "LOG"
    TRACE = "TRACE"
    DEPLOYMENT = "DEPLOYMENT"
    TOPOLOGY = "TOPOLOGY"


class TrustClassification(StrEnum):
    DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
    DERIVED_OBSERVATION = "DERIVED_OBSERVATION"
    HISTORICAL_REFERENCE = "HISTORICAL_REFERENCE"
    UNTRUSTED_INPUT = "UNTRUSTED_INPUT"


class PromptInjectionStatus(StrEnum):
    NONE = "NONE"
    SUSPECTED = "SUSPECTED"
    QUARANTINED = "QUARANTINED"


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    if any(ord(character) < 32 for character in value):
        raise InvalidDomainValueError(f"{field} cannot contain control characters")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise InvalidDomainValueError(f"{field} must contain 1-{maximum} characters")
    return normalized


@dataclass(frozen=True, slots=True, order=True)
class QueryParameter:
    """One canonical, bounded query field with no raw URL/path semantics."""

    name: str
    value: str

    def __post_init__(self) -> None:
        name = self.name.strip().lower()
        if _NAME.fullmatch(name) is None:
            raise InvalidDomainValueError("query parameter name is invalid")
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self, "value", _bounded_text(self.value, field="query value", maximum=512)
        )


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    """Deterministically ordered exact parameters used by a collector."""

    parameters: tuple[QueryParameter, ...]

    def __post_init__(self) -> None:
        if not self.parameters or len(self.parameters) > 32:
            raise InvalidDomainValueError("normalized query must contain 1-32 parameters")
        ordered = tuple(sorted(self.parameters))
        if len({parameter.name for parameter in ordered}) != len(ordered):
            raise InvalidDomainValueError("normalized query parameter names must be unique")
        object.__setattr__(self, "parameters", ordered)

    def as_dict(self) -> dict[str, str]:
        return {parameter.name: parameter.value for parameter in self.parameters}


@dataclass(frozen=True, slots=True)
class EvidenceQuality:
    """Deterministic quality score with explicit reason codes."""

    score_basis_points: int
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.score_basis_points, int)
            or isinstance(self.score_basis_points, bool)
            or not 0 <= self.score_basis_points <= 10_000
        ):
            raise InvalidDomainValueError("evidence quality must be 0-10000 basis points")
        if not self.reasons or len(self.reasons) > 16:
            raise InvalidDomainValueError("evidence quality must contain 1-16 reasons")
        normalized = tuple(
            _bounded_text(reason, field="quality reason", maximum=128) for reason in self.reasons
        )
        if len(set(normalized)) != len(normalized):
            raise InvalidDomainValueError("evidence quality reasons must be unique")
        object.__setattr__(self, "reasons", normalized)


@dataclass(frozen=True, slots=True)
class EvidenceLineage:
    tool_call_id: ToolCallId
    workflow_run_id: WorkflowRunId
    redaction_transform_id: RedactionTransformId | None
    parent_evidence_ids: tuple[EvidenceId, ...] = ()

    def __post_init__(self) -> None:
        if len(self.parent_evidence_ids) > 32:
            raise InvalidDomainValueError("evidence lineage cannot exceed 32 parents")
        if len(set(self.parent_evidence_ids)) != len(self.parent_evidence_ids):
            raise InvalidDomainValueError("evidence lineage parents must be unique")


@dataclass(frozen=True, slots=True)
class Evidence:
    """Immutable normalized observation that always resolves to an Artifact."""

    id: EvidenceId
    tenant_id: TenantId
    incident_id: IncidentId
    source_type: EvidenceSourceType
    source_instance: str
    tool_name: str
    tool_version: str
    tool_schema_version: str
    normalized_query: NormalizedQuery
    observed_from: datetime
    observed_to: datetime
    collected_at: datetime
    artifact_id: ArtifactId
    content_hash: Sha256Digest
    parser_version: str
    normalizer_version: str
    quality: EvidenceQuality
    lineage: EvidenceLineage
    trust: TrustClassification
    prompt_injection_status: PromptInjectionStatus
    expires_at: datetime
    schema_version: str = EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_instance",
            _bounded_text(self.source_instance, field="source instance", maximum=128),
        )
        tool_name = self.tool_name.strip().lower()
        if _NAME.fullmatch(tool_name) is None:
            raise InvalidDomainValueError("evidence tool name is invalid")
        object.__setattr__(self, "tool_name", tool_name)
        for field, value in (
            ("tool version", self.tool_version),
            ("tool schema version", self.tool_schema_version),
            ("parser version", self.parser_version),
            ("normalizer version", self.normalizer_version),
        ):
            if _VERSION.fullmatch(value) is None:
                raise InvalidDomainValueError(f"evidence {field} is invalid")
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise InvalidDomainValueError("evidence schema version is unsupported")
        observed_from = as_utc(self.observed_from)
        observed_to = as_utc(self.observed_to)
        collected_at = as_utc(self.collected_at)
        expires_at = as_utc(self.expires_at)
        if observed_to < observed_from:
            raise InvalidDomainValueError("evidence observation range is reversed")
        if collected_at < observed_to:
            raise InvalidDomainValueError("evidence collection predates its observation range")
        if expires_at <= collected_at:
            raise InvalidDomainValueError("evidence expiry must follow collection")
        object.__setattr__(self, "observed_from", observed_from)
        object.__setattr__(self, "observed_to", observed_to)
        object.__setattr__(self, "collected_at", collected_at)
        object.__setattr__(self, "expires_at", expires_at)

    def verify_artifact(self, artifact: Artifact) -> None:
        """Reject absent ownership or digest binding before persistence/use."""
        if (
            artifact.id != self.artifact_id
            or artifact.tenant_id != self.tenant_id
            or artifact.incident_id != self.incident_id
            or artifact.content_hash != self.content_hash
        ):
            raise ArtifactIntegrityError("evidence does not resolve to its owning Artifact")

    def is_expired(self, *, at: datetime) -> bool:
        return as_utc(at) >= self.expires_at
