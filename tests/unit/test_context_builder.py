"""Budgeted Context Builder provenance, truncation, and omission tests."""

from __future__ import annotations

from typing import Any

import pytest

from agentops_incident_commander.domain import (
    CONTEXT_SCHEMA_VERSION,
    MAX_CONTEXT_CANDIDATES,
    MAX_CONTEXT_SUMMARY_CHARS,
    MAX_CONTEXT_TOKENS,
    ArtifactId,
    ContextCandidate,
    ContextContentKind,
    ContextOmissionReason,
    EvidenceId,
    EvidenceSourceType,
    IncidentId,
    InvalidDomainValueError,
    TrustClassification,
    build_budgeted_context,
)

INCIDENT_ID = IncidentId("incident-context")


def candidate(
    index: int,
    summary: str,
    *,
    priority: int = 50,
    incident_id: IncidentId = INCIDENT_ID,
    source_type: EvidenceSourceType = EvidenceSourceType.LOG,
    key: str | None = None,
    evidence_id: str | None = None,
) -> ContextCandidate:
    return ContextCandidate(
        f"item-{index}" if key is None else key,
        incident_id,
        EvidenceId(evidence_id or f"evidence-{index}"),
        ArtifactId(f"artifact-{index}"),
        source_type,
        TrustClassification.DERIVED_OBSERVATION,
        ContextContentKind.SUMMARY,
        summary,
        priority,
    )


def test_builder_selects_stably_and_records_all_omissions() -> None:
    high = candidate(0, "a" * 8, priority=100, source_type=EvidenceSourceType.METRIC)
    middle = candidate(1, "b" * 8, priority=50, source_type=EvidenceSourceType.TRACE)
    same_priority = candidate(2, "c" * 8, priority=50, source_type=EvidenceSourceType.LOG)
    low = candidate(3, "d" * 8, priority=1)

    result = build_budgeted_context(
        (low, middle, high, same_priority),
        incident_id=INCIDENT_ID,
        token_budget=5,
        item_limit=2,
    )

    assert result.incident_id == INCIDENT_ID
    assert result.items == (high, same_priority)
    assert result.used_tokens == 4
    assert result.token_budget == 5
    assert result.item_limit == 2
    assert result.schema_version == CONTEXT_SCHEMA_VERSION
    assert tuple(item.key for item in result.omissions) == ("item-1", "item-3")
    assert all(item.reason is ContextOmissionReason.ITEM_LIMIT for item in result.omissions)
    assert result.omissions[0].evidence_id == middle.evidence_id
    assert result.omissions[0].artifact_id == middle.artifact_id
    assert result.omissions[0].estimated_tokens == 2


def test_token_budget_omits_whole_item_and_can_continue_with_smaller_item() -> None:
    large = candidate(0, "x" * 20, priority=100)
    small = candidate(1, "ok", priority=50)
    result = build_budgeted_context(
        (small, large), incident_id=INCIDENT_ID, token_budget=2, item_limit=2
    )
    assert result.items == (small,)
    assert result.used_tokens == 1
    assert result.omissions[0].key == large.key
    assert result.omissions[0].reason is ContextOmissionReason.TOKEN_BUDGET


def test_empty_context_is_valid_and_raw_content_kind_is_not_representable() -> None:
    result = build_budgeted_context((), incident_id=INCIDENT_ID, token_budget=1, item_limit=1)
    assert result.items == ()
    assert result.omissions == ()
    assert {item.value for item in ContextContentKind} == {"SUMMARY", "QUARANTINE_METADATA"}


def test_token_estimate_uses_utf8_bytes_with_minimum_one() -> None:
    assert candidate(0, "a").estimated_tokens == 1
    assert candidate(1, "故障").estimated_tokens == 2


@pytest.mark.parametrize("value", ["", "x" * 129, "bad\x00key"])
def test_candidate_key_is_bounded(value: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="key"):
        candidate(0, "summary", key=value)


@pytest.mark.parametrize("value", ["", "x" * (MAX_CONTEXT_SUMMARY_CHARS + 1), "bad\x00text"])
def test_candidate_summary_is_bounded(value: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="summary"):
        candidate(0, value)


@pytest.mark.parametrize("priority", [-1, 101, True, 1.5])
def test_candidate_priority_is_bounded(priority: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="priority"):
        candidate(0, "summary", priority=priority)


def test_builder_rejects_excess_candidates() -> None:
    repeated = candidate(0, "summary")
    with pytest.raises(InvalidDomainValueError, match="candidate limit"):
        build_budgeted_context(
            (repeated,) * (MAX_CONTEXT_CANDIDATES + 1),
            incident_id=INCIDENT_ID,
            token_budget=1,
            item_limit=1,
        )


@pytest.mark.parametrize("budget", [0, MAX_CONTEXT_TOKENS + 1, True, 1.5])
def test_builder_rejects_invalid_token_budget(budget: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="token budget"):
        build_budgeted_context((), incident_id=INCIDENT_ID, token_budget=budget, item_limit=1)


@pytest.mark.parametrize("limit", [0, MAX_CONTEXT_CANDIDATES + 1, True, 1.5])
def test_builder_rejects_invalid_item_limit(limit: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="item limit"):
        build_budgeted_context((), incident_id=INCIDENT_ID, token_budget=1, item_limit=limit)


def test_builder_rejects_cross_incident_candidates() -> None:
    with pytest.raises(InvalidDomainValueError, match="one Incident"):
        build_budgeted_context(
            (candidate(0, "summary", incident_id=IncidentId("other")),),
            incident_id=INCIDENT_ID,
            token_budget=10,
            item_limit=1,
        )


def test_builder_rejects_duplicate_keys_or_evidence_references() -> None:
    first = candidate(0, "one")
    with pytest.raises(InvalidDomainValueError, match="keys"):
        build_budgeted_context(
            (first, candidate(1, "two", key=first.key)),
            incident_id=INCIDENT_ID,
            token_budget=10,
            item_limit=2,
        )
    with pytest.raises(InvalidDomainValueError, match="Evidence"):
        build_budgeted_context(
            (first, candidate(1, "two", evidence_id=first.evidence_id.value)),
            incident_id=INCIDENT_ID,
            token_budget=10,
            item_limit=2,
        )
