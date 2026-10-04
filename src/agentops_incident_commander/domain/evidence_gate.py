"""Versioned deterministic Evidence Gate rules, inputs, and decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .errors import InvalidDomainValueError
from .values import EvidenceId, IncidentId, Sha256Digest, as_utc

EVIDENCE_GATE_SCHEMA_VERSION = "1.0.0"
DEFAULT_EVIDENCE_GATE_RULES_VERSION = "1.0.0"
MAX_GATE_EVIDENCE_REFERENCES = 64
MAX_GATE_MISSING_ITEMS = 16
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or any(ord(character) < 32 for character in value):
        raise InvalidDomainValueError(f"evidence gate {field} is invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise InvalidDomainValueError(f"evidence gate {field} is invalid")
    return normalized


class EvidenceGateOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class EvidenceGateReasonCode(StrEnum):
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    ARTIFACT_UNRESOLVABLE = "ARTIFACT_UNRESOLVABLE"
    INCIDENT_OWNERSHIP_MISMATCH = "INCIDENT_OWNERSHIP_MISMATCH"
    EVIDENCE_EXPIRED = "EVIDENCE_EXPIRED"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    QUALITY_BELOW_FLOOR = "QUALITY_BELOW_FLOOR"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    INSUFFICIENT_INDEPENDENT_SOURCES = "INSUFFICIENT_INDEPENDENT_SOURCES"
    UNRESOLVED_COUNTER_EVIDENCE = "UNRESOLVED_COUNTER_EVIDENCE"
    MISSING_EVIDENCE_DECLARED = "MISSING_EVIDENCE_DECLARED"


@dataclass(frozen=True, slots=True)
class EvidenceGateRules:
    version: str = DEFAULT_EVIDENCE_GATE_RULES_VERSION
    minimum_quality_basis_points: int = 7_000
    maximum_evidence_age: timedelta = timedelta(hours=1)
    minimum_independent_sources: int = 2
    require_counter_evidence_resolution: bool = True
    fail_on_declared_missing_evidence: bool = True
    schema_version: str = EVIDENCE_GATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or _VERSION.fullmatch(self.version) is None:
            raise InvalidDomainValueError("evidence gate rules version must be semantic")
        if self.schema_version != EVIDENCE_GATE_SCHEMA_VERSION:
            raise InvalidDomainValueError("evidence gate rules schema version is unsupported")
        if (
            not isinstance(self.minimum_quality_basis_points, int)
            or isinstance(self.minimum_quality_basis_points, bool)
            or not 0 <= self.minimum_quality_basis_points <= 10_000
        ):
            raise InvalidDomainValueError("evidence gate quality floor is invalid")
        if not isinstance(self.maximum_evidence_age, timedelta) or not (
            timedelta(0) < self.maximum_evidence_age <= timedelta(days=30)
        ):
            raise InvalidDomainValueError("evidence gate maximum age is invalid")
        if (
            not isinstance(self.minimum_independent_sources, int)
            or isinstance(self.minimum_independent_sources, bool)
            or not 1 <= self.minimum_independent_sources <= 8
        ):
            raise InvalidDomainValueError("evidence gate independent source minimum is invalid")
        if not isinstance(self.require_counter_evidence_resolution, bool) or not isinstance(
            self.fail_on_declared_missing_evidence, bool
        ):
            raise InvalidDomainValueError("evidence gate rule flags must be boolean")


@dataclass(frozen=True, slots=True)
class RootCauseEvidenceClaim:
    incident_id: IncidentId
    candidate_id: str
    supporting_evidence_ids: tuple[EvidenceId, ...]
    counter_evidence_ids: tuple[EvidenceId, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    counter_evidence_resolved: bool = False
    model_confidence_basis_points: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _bounded_text(self.candidate_id, field="candidate ID", maximum=128),
        )
        supporting = _evidence_ids(self.supporting_evidence_ids, field="supporting")
        if not supporting:
            raise InvalidDomainValueError("evidence gate requires supporting evidence references")
        counter = _evidence_ids(self.counter_evidence_ids, field="counter")
        if set(supporting) & set(counter):
            raise InvalidDomainValueError("supporting and counter evidence must be disjoint")
        if len(self.missing_evidence) > MAX_GATE_MISSING_ITEMS:
            raise InvalidDomainValueError("evidence gate missing evidence count exceeds limit")
        missing = tuple(
            _bounded_text(item, field="missing evidence", maximum=256)
            for item in self.missing_evidence
        )
        if len(set(missing)) != len(missing):
            raise InvalidDomainValueError("evidence gate missing evidence must be unique")
        if not isinstance(self.counter_evidence_resolved, bool):
            raise InvalidDomainValueError("counter evidence resolution must be boolean")
        confidence = self.model_confidence_basis_points
        if confidence is not None and (
            not isinstance(confidence, int)
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 10_000
        ):
            raise InvalidDomainValueError("model confidence metadata is invalid")
        object.__setattr__(self, "supporting_evidence_ids", supporting)
        object.__setattr__(self, "counter_evidence_ids", counter)
        object.__setattr__(self, "missing_evidence", missing)

    @property
    def all_evidence_ids(self) -> tuple[EvidenceId, ...]:
        return _evidence_ids(
            (*self.supporting_evidence_ids, *self.counter_evidence_ids), field="all"
        )


def _evidence_ids(values: tuple[EvidenceId, ...], *, field: str) -> tuple[EvidenceId, ...]:
    if not isinstance(values, tuple) or len(values) > MAX_GATE_EVIDENCE_REFERENCES:
        raise InvalidDomainValueError(f"evidence gate {field} references exceed limit")
    if any(not isinstance(value, EvidenceId) for value in values):
        raise InvalidDomainValueError(f"evidence gate {field} references are invalid")
    ordered = tuple(sorted(values, key=lambda item: item.value))
    if len(set(ordered)) != len(ordered):
        raise InvalidDomainValueError(f"evidence gate {field} references must be unique")
    return ordered


@dataclass(frozen=True, slots=True)
class EvidenceGateReason:
    code: EvidenceGateReasonCode
    detail: str
    evidence_ids: tuple[EvidenceId, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, EvidenceGateReasonCode):
            raise InvalidDomainValueError("evidence gate reason code is invalid")
        object.__setattr__(
            self, "detail", _bounded_text(self.detail, field="reason detail", maximum=256)
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _evidence_ids(self.evidence_ids, field="reason"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceGateDecision:
    incident_id: IncidentId
    candidate_id: str
    outcome: EvidenceGateOutcome
    reasons: tuple[EvidenceGateReason, ...]
    evaluated_evidence_ids: tuple[EvidenceId, ...]
    rules_version: str
    input_fingerprint: Sha256Digest
    evaluated_at: datetime
    model_confidence_basis_points: int | None = None
    schema_version: str = EVIDENCE_GATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _bounded_text(self.candidate_id, field="candidate ID", maximum=128),
        )
        if not isinstance(self.outcome, EvidenceGateOutcome):
            raise InvalidDomainValueError("evidence gate outcome is invalid")
        if self.schema_version != EVIDENCE_GATE_SCHEMA_VERSION:
            raise InvalidDomainValueError("evidence gate decision schema version is unsupported")
        if _VERSION.fullmatch(self.rules_version) is None:
            raise InvalidDomainValueError("evidence gate decision rules version is invalid")
        if not isinstance(self.reasons, tuple) or any(
            not isinstance(reason, EvidenceGateReason) for reason in self.reasons
        ):
            raise InvalidDomainValueError("evidence gate decision reasons are invalid")
        if self.outcome is EvidenceGateOutcome.PASS and self.reasons:
            raise InvalidDomainValueError("passing evidence gate decisions cannot have failures")
        if self.outcome is EvidenceGateOutcome.FAIL and not self.reasons:
            raise InvalidDomainValueError("failed evidence gate decisions require reasons")
        reason_keys = tuple((reason.code, reason.evidence_ids) for reason in self.reasons)
        if len(set(reason_keys)) != len(reason_keys):
            raise InvalidDomainValueError("evidence gate decision reasons must be unique")
        object.__setattr__(
            self,
            "evaluated_evidence_ids",
            _evidence_ids(self.evaluated_evidence_ids, field="evaluated"),
        )
        confidence = self.model_confidence_basis_points
        if confidence is not None and (
            not isinstance(confidence, int)
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 10_000
        ):
            raise InvalidDomainValueError("model confidence metadata is invalid")
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))
