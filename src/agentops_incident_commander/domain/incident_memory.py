"""Confirmed closed-Incident projection for historical-reference memory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import cast

from .errors import InvalidDomainValueError
from .evidence import TrustClassification
from .incidents import Incident, IncidentState
from .values import (
    AggregateVersion,
    EvidenceId,
    IncidentId,
    IncidentMemoryId,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    as_utc,
)

INCIDENT_MEMORY_SCHEMA_VERSION = "1.0.0"
MAX_INCIDENT_MEMORY_EVIDENCE = 64
MAX_INCIDENT_MEMORY_TEXT = 1_024
_SERVICE = re.compile(r"^[a-z][a-z0-9-]{0,127}$")


class IncidentMemoryOutcome(StrEnum):
    RECOVERED = "RECOVERED"
    HUMAN_RESOLVED = "HUMAN_RESOLVED"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"


class IncidentMemoryConfirmationSource(StrEnum):
    DETERMINISTIC_VERIFIER = "DETERMINISTIC_VERIFIER"
    HUMAN_REVIEW = "HUMAN_REVIEW"


@dataclass(frozen=True, slots=True)
class IncidentMemoryProjection:
    """Immutable advisory projection; never current-Incident Evidence."""

    id: IncidentMemoryId
    tenant_id: TenantId
    source_incident_id: IncidentId
    source_incident_version: AggregateVersion
    source_incident_state: IncidentState
    service: str
    root_cause_summary: str
    outcome: IncidentMemoryOutcome
    outcome_summary: str
    source_evidence_ids: tuple[EvidenceId, ...]
    diagnosis_report_fingerprint: Sha256Digest
    evidence_gate_decision_fingerprint: Sha256Digest
    confirmation_source: IncidentMemoryConfirmationSource
    confirmation_reference: OpaqueIdentifier
    recovery_action_reference: OpaqueIdentifier | None
    closed_at: datetime
    projected_at: datetime
    content_fingerprint: Sha256Digest
    trust: TrustClassification = TrustClassification.HISTORICAL_REFERENCE
    schema_version: str = INCIDENT_MEMORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_projection_types(self)
        service = self.service.strip().lower()
        if _SERVICE.fullmatch(service) is None:
            raise InvalidDomainValueError("Incident memory service is invalid")
        object.__setattr__(self, "service", service)
        object.__setattr__(
            self,
            "root_cause_summary",
            _bounded_text(self.root_cause_summary, field="root-cause summary"),
        )
        object.__setattr__(
            self,
            "outcome_summary",
            _bounded_text(self.outcome_summary, field="outcome summary"),
        )
        if (
            not isinstance(self.source_evidence_ids, tuple)
            or not 1 <= len(self.source_evidence_ids) <= MAX_INCIDENT_MEMORY_EVIDENCE
            or any(not isinstance(value, EvidenceId) for value in self.source_evidence_ids)
        ):
            raise InvalidDomainValueError(
                "Incident memory Evidence references must be a non-empty bounded tuple"
            )
        evidence_ids = tuple(sorted(self.source_evidence_ids, key=lambda value: value.value))
        if len(set(evidence_ids)) != len(evidence_ids):
            raise InvalidDomainValueError("Incident memory Evidence references must be unique")
        object.__setattr__(self, "source_evidence_ids", evidence_ids)
        if self.source_incident_state is not IncidentState.CLOSED:
            raise InvalidDomainValueError("Incident memory source must be CLOSED")
        closed_at = as_utc(self.closed_at)
        projected_at = as_utc(self.projected_at)
        if projected_at < closed_at:
            raise InvalidDomainValueError("Incident memory projection cannot predate closure")
        object.__setattr__(self, "closed_at", closed_at)
        object.__setattr__(self, "projected_at", projected_at)
        if self.outcome is IncidentMemoryOutcome.RECOVERED:
            if self.recovery_action_reference is None:
                raise InvalidDomainValueError(
                    "recovered Incident memory requires a recovery action reference"
                )
        elif self.recovery_action_reference is not None:
            raise InvalidDomainValueError(
                "non-recovered Incident memory cannot claim a recovery action"
            )
        if self.trust is not TrustClassification.HISTORICAL_REFERENCE:
            raise InvalidDomainValueError("Incident memory trust must remain HISTORICAL_REFERENCE")
        if self.schema_version != INCIDENT_MEMORY_SCHEMA_VERSION:
            raise InvalidDomainValueError("Incident memory schema version is unsupported")
        if self.content_fingerprint != _content_fingerprint(self):
            raise InvalidDomainValueError("Incident memory content fingerprint does not match")

    @classmethod
    def create(
        cls,
        *,
        memory_id: IncidentMemoryId,
        incident: Incident,
        service: str,
        root_cause_summary: str,
        outcome: IncidentMemoryOutcome,
        outcome_summary: str,
        source_evidence_ids: tuple[EvidenceId, ...],
        diagnosis_report_fingerprint: Sha256Digest,
        evidence_gate_decision_fingerprint: Sha256Digest,
        confirmation_source: IncidentMemoryConfirmationSource,
        confirmation_reference: OpaqueIdentifier,
        recovery_action_reference: OpaqueIdentifier | None,
        projected_at: datetime,
    ) -> IncidentMemoryProjection:
        if not isinstance(incident, Incident) or incident.state is not IncidentState.CLOSED:
            raise InvalidDomainValueError("only a CLOSED Incident can enter historical memory")
        closed_at = cast(datetime, incident.closed_at)
        if (
            not isinstance(memory_id, IncidentMemoryId)
            or not isinstance(outcome, IncidentMemoryOutcome)
            or not isinstance(source_evidence_ids, tuple)
            or any(not isinstance(value, EvidenceId) for value in source_evidence_ids)
            or not isinstance(diagnosis_report_fingerprint, Sha256Digest)
            or not isinstance(evidence_gate_decision_fingerprint, Sha256Digest)
            or not isinstance(confirmation_source, IncidentMemoryConfirmationSource)
            or not isinstance(confirmation_reference, OpaqueIdentifier)
            or (
                recovery_action_reference is not None
                and not isinstance(recovery_action_reference, OpaqueIdentifier)
            )
        ):
            raise InvalidDomainValueError("Incident memory creation inputs are invalid")
        normalized_service = service.strip().lower()
        normalized_root_cause = _bounded_text(root_cause_summary, field="root-cause summary")
        normalized_outcome = _bounded_text(outcome_summary, field="outcome summary")
        ordered_evidence = tuple(sorted(source_evidence_ids, key=lambda value: value.value))
        normalized_projected_at = as_utc(projected_at)
        fingerprint = _content_fingerprint_values(
            memory_id=memory_id,
            tenant_id=incident.tenant_id,
            source_incident_id=incident.id,
            source_incident_version=incident.version,
            source_incident_state=incident.state,
            service=normalized_service,
            root_cause_summary=normalized_root_cause,
            outcome=outcome,
            outcome_summary=normalized_outcome,
            source_evidence_ids=ordered_evidence,
            diagnosis_report_fingerprint=diagnosis_report_fingerprint,
            evidence_gate_decision_fingerprint=evidence_gate_decision_fingerprint,
            confirmation_source=confirmation_source,
            confirmation_reference=confirmation_reference,
            recovery_action_reference=recovery_action_reference,
            closed_at=closed_at,
            projected_at=normalized_projected_at,
        )
        return cls(
            id=memory_id,
            tenant_id=incident.tenant_id,
            source_incident_id=incident.id,
            source_incident_version=incident.version,
            source_incident_state=incident.state,
            service=normalized_service,
            root_cause_summary=normalized_root_cause,
            outcome=outcome,
            outcome_summary=normalized_outcome,
            source_evidence_ids=ordered_evidence,
            diagnosis_report_fingerprint=diagnosis_report_fingerprint,
            evidence_gate_decision_fingerprint=evidence_gate_decision_fingerprint,
            confirmation_source=confirmation_source,
            confirmation_reference=confirmation_reference,
            recovery_action_reference=recovery_action_reference,
            closed_at=closed_at,
            projected_at=normalized_projected_at,
            content_fingerprint=fingerprint,
        )


def _require_projection_types(projection: IncidentMemoryProjection) -> None:
    expected = (
        (projection.id, IncidentMemoryId),
        (projection.tenant_id, TenantId),
        (projection.source_incident_id, IncidentId),
        (projection.source_incident_version, AggregateVersion),
        (projection.source_incident_state, IncidentState),
        (projection.outcome, IncidentMemoryOutcome),
        (projection.diagnosis_report_fingerprint, Sha256Digest),
        (projection.evidence_gate_decision_fingerprint, Sha256Digest),
        (projection.confirmation_source, IncidentMemoryConfirmationSource),
        (projection.confirmation_reference, OpaqueIdentifier),
        (projection.content_fingerprint, Sha256Digest),
        (projection.trust, TrustClassification),
    )
    if any(not isinstance(value, expected_type) for value, expected_type in expected):
        raise InvalidDomainValueError("Incident memory projection types are invalid")
    if projection.recovery_action_reference is not None and not isinstance(
        projection.recovery_action_reference, OpaqueIdentifier
    ):
        raise InvalidDomainValueError("Incident memory recovery action reference is invalid")


def _bounded_text(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidDomainValueError(f"Incident memory {field} is invalid")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_INCIDENT_MEMORY_TEXT
        or any(ord(character) < 32 for character in normalized)
    ):
        raise InvalidDomainValueError(f"Incident memory {field} is invalid")
    return normalized


def _content_fingerprint(projection: IncidentMemoryProjection) -> Sha256Digest:
    return _content_fingerprint_values(
        memory_id=projection.id,
        tenant_id=projection.tenant_id,
        source_incident_id=projection.source_incident_id,
        source_incident_version=projection.source_incident_version,
        source_incident_state=projection.source_incident_state,
        service=projection.service,
        root_cause_summary=projection.root_cause_summary,
        outcome=projection.outcome,
        outcome_summary=projection.outcome_summary,
        source_evidence_ids=projection.source_evidence_ids,
        diagnosis_report_fingerprint=projection.diagnosis_report_fingerprint,
        evidence_gate_decision_fingerprint=projection.evidence_gate_decision_fingerprint,
        confirmation_source=projection.confirmation_source,
        confirmation_reference=projection.confirmation_reference,
        recovery_action_reference=projection.recovery_action_reference,
        closed_at=projection.closed_at,
        projected_at=projection.projected_at,
    )


def _content_fingerprint_values(
    *,
    memory_id: IncidentMemoryId,
    tenant_id: TenantId,
    source_incident_id: IncidentId,
    source_incident_version: AggregateVersion,
    source_incident_state: IncidentState,
    service: str,
    root_cause_summary: str,
    outcome: IncidentMemoryOutcome,
    outcome_summary: str,
    source_evidence_ids: tuple[EvidenceId, ...],
    diagnosis_report_fingerprint: Sha256Digest,
    evidence_gate_decision_fingerprint: Sha256Digest,
    confirmation_source: IncidentMemoryConfirmationSource,
    confirmation_reference: OpaqueIdentifier,
    recovery_action_reference: OpaqueIdentifier | None,
    closed_at: datetime,
    projected_at: datetime,
) -> Sha256Digest:
    payload = {
        "closed_at": closed_at.isoformat(),
        "confirmation_reference": confirmation_reference.value,
        "confirmation_source": confirmation_source.value,
        "diagnosis_report_fingerprint": diagnosis_report_fingerprint.value,
        "evidence_gate_decision_fingerprint": evidence_gate_decision_fingerprint.value,
        "id": memory_id.value,
        "outcome": outcome.value,
        "outcome_summary": outcome_summary,
        "projected_at": projected_at.isoformat(),
        "recovery_action_reference": (
            recovery_action_reference.value if recovery_action_reference is not None else None
        ),
        "root_cause_summary": root_cause_summary,
        "schema_version": INCIDENT_MEMORY_SCHEMA_VERSION,
        "service": service,
        "source_evidence_ids": [value.value for value in source_evidence_ids],
        "source_incident_id": source_incident_id.value,
        "source_incident_state": source_incident_state.value,
        "source_incident_version": source_incident_version.value,
        "tenant_id": tenant_id.value,
        "trust": TrustClassification.HISTORICAL_REFERENCE.value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return Sha256Digest(sha256(encoded).hexdigest())
