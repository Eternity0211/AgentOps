"""Confirmed closed-Incident historical memory projection tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.domain import (
    INCIDENT_MEMORY_SCHEMA_VERSION,
    MAX_INCIDENT_MEMORY_EVIDENCE,
    AggregateVersion,
    EvidenceId,
    Incident,
    IncidentId,
    IncidentMemoryConfirmationSource,
    IncidentMemoryId,
    IncidentMemoryOutcome,
    IncidentMemoryProjection,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    TrustClassification,
)

OPENED = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
CLOSED = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
PROJECTED = datetime(2026, 10, 5, 9, 1, tzinfo=UTC)


def closed_incident() -> Incident:
    return Incident(
        id=IncidentId("incident-memory-1"),
        tenant_id=TenantId("tenant-1"),
        severity=IncidentSeverity.SEV2,
        opened_at=OPENED,
        updated_at=CLOSED,
        state=IncidentState.CLOSED,
        version=AggregateVersion(9),
        closed_at=CLOSED,
    )


def projection(**overrides: Any) -> IncidentMemoryProjection:
    values: dict[str, object] = {
        "memory_id": IncidentMemoryId("memory-1"),
        "incident": closed_incident(),
        "service": "Order-API",
        "root_cause_summary": " Deployment version 2 exhausted the connection pool. ",
        "outcome": IncidentMemoryOutcome.RECOVERED,
        "outcome_summary": "Rollback to version 1 passed deterministic verification.",
        "source_evidence_ids": (EvidenceId("evidence-2"), EvidenceId("evidence-1")),
        "diagnosis_report_fingerprint": Sha256Digest("a" * 64),
        "evidence_gate_decision_fingerprint": Sha256Digest("b" * 64),
        "confirmation_source": IncidentMemoryConfirmationSource.DETERMINISTIC_VERIFIER,
        "confirmation_reference": OpaqueIdentifier("verification-1"),
        "recovery_action_reference": OpaqueIdentifier("action-1"),
        "projected_at": PROJECTED,
    }
    values.update(overrides)
    return IncidentMemoryProjection.create(**values)  # type: ignore[arg-type]


def test_projection_is_canonical_historical_and_fingerprint_bound() -> None:
    value = projection()
    reordered = projection(source_evidence_ids=(EvidenceId("evidence-1"), EvidenceId("evidence-2")))

    assert value == reordered
    assert value.service == "order-api"
    assert value.root_cause_summary == "Deployment version 2 exhausted the connection pool."
    assert value.source_evidence_ids == (EvidenceId("evidence-1"), EvidenceId("evidence-2"))
    assert value.source_incident_state is IncidentState.CLOSED
    assert value.source_incident_version == AggregateVersion(9)
    assert value.trust is TrustClassification.HISTORICAL_REFERENCE
    assert value.schema_version == INCIDENT_MEMORY_SCHEMA_VERSION
    assert value.content_fingerprint.value != "a" * 64
    with pytest.raises(InvalidDomainValueError, match="fingerprint"):
        replace(value, outcome_summary="Altered after projection")


@pytest.mark.parametrize(
    "incident",
    [
        cast(Incident, object()),
        Incident.open(
            IncidentId("incident-open"),
            TenantId("tenant-1"),
            IncidentSeverity.SEV3,
            opened_at=OPENED,
        ),
        Incident(
            id=IncidentId("incident-cancelled"),
            tenant_id=TenantId("tenant-1"),
            severity=IncidentSeverity.SEV3,
            opened_at=OPENED,
            updated_at=CLOSED,
            state=IncidentState.CANCELLED,
            version=AggregateVersion(2),
            cancelled_at=CLOSED,
        ),
        replace(closed_incident(), state=IncidentState.RESOLVED, closed_at=None),
    ],
)
def test_only_closed_incidents_can_enter_memory(incident: Incident) -> None:
    with pytest.raises(InvalidDomainValueError, match="only a CLOSED"):
        projection(incident=incident)


@pytest.mark.parametrize(
    ("outcome", "action", "valid"),
    [
        (IncidentMemoryOutcome.RECOVERED, OpaqueIdentifier("action-1"), True),
        (IncidentMemoryOutcome.RECOVERED, None, False),
        (IncidentMemoryOutcome.HUMAN_RESOLVED, None, True),
        (IncidentMemoryOutcome.HUMAN_RESOLVED, OpaqueIdentifier("action-1"), False),
        (IncidentMemoryOutcome.NO_ACTION_REQUIRED, None, True),
        (IncidentMemoryOutcome.NO_ACTION_REQUIRED, OpaqueIdentifier("action-1"), False),
    ],
)
def test_outcome_and_recovery_action_reference_must_agree(
    outcome: IncidentMemoryOutcome,
    action: OpaqueIdentifier | None,
    valid: bool,
) -> None:
    if valid:
        assert projection(outcome=outcome, recovery_action_reference=action).outcome is outcome
    else:
        with pytest.raises(InvalidDomainValueError, match="recovery action"):
            projection(outcome=outcome, recovery_action_reference=action)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"service": "bad service"}, "service"),
        ({"root_cause_summary": cast(str, 1)}, "root-cause"),
        ({"root_cause_summary": ""}, "root-cause"),
        ({"outcome_summary": "line\nbreak"}, "outcome summary"),
        ({"source_evidence_ids": ()}, "non-empty bounded"),
        (
            {"source_evidence_ids": (EvidenceId("same"), EvidenceId("same"))},
            "unique",
        ),
        (
            {
                "source_evidence_ids": tuple(
                    EvidenceId(f"evidence-{index}")
                    for index in range(MAX_INCIDENT_MEMORY_EVIDENCE + 1)
                )
            },
            "non-empty bounded",
        ),
        ({"projected_at": CLOSED - timedelta(seconds=1)}, "predate closure"),
    ],
)
def test_projection_rejects_unbounded_ambiguous_or_invalid_content(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        projection(**overrides)


def test_confirmation_sources_are_explicit_and_content_changes_change_hash() -> None:
    verified = projection()
    reviewed = projection(
        confirmation_source=IncidentMemoryConfirmationSource.HUMAN_REVIEW,
        confirmation_reference=OpaqueIdentifier("review-1"),
    )
    changed_gate = projection(evidence_gate_decision_fingerprint=Sha256Digest("c" * 64))

    assert reviewed.confirmation_source is IncidentMemoryConfirmationSource.HUMAN_REVIEW
    assert (
        len(
            {
                verified.content_fingerprint,
                reviewed.content_fingerprint,
                changed_gate.content_fingerprint,
            }
        )
        == 3
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_incident_state", IncidentState.RESOLVED, "must be CLOSED"),
        ("trust", TrustClassification.DIRECT_OBSERVATION, "HISTORICAL_REFERENCE"),
        ("schema_version", "2.0.0", "unsupported"),
        ("content_fingerprint", Sha256Digest("0" * 64), "fingerprint"),
        ("confirmation_source", "HUMAN_REVIEW", "types"),
        ("recovery_action_reference", "action-1", "recovery action reference"),
    ],
)
def test_direct_construction_cannot_forge_authority_or_metadata(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        replace(projection(), **cast(Any, {field: value}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"memory_id": cast(IncidentMemoryId, "memory-1")},
        {"outcome": cast(IncidentMemoryOutcome, "RECOVERED")},
        {"source_evidence_ids": cast(tuple[EvidenceId, ...], [EvidenceId("evidence-1")])},
        {"diagnosis_report_fingerprint": cast(Sha256Digest, "a" * 64)},
        {"confirmation_reference": cast(OpaqueIdentifier, "verification-1")},
    ],
)
def test_creation_rejects_untyped_inputs(overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidDomainValueError, match="creation inputs"):
        projection(**overrides)


def test_projection_is_frozen() -> None:
    value = projection()
    with pytest.raises(AttributeError):
        value.service = "other"  # type: ignore[misc]
