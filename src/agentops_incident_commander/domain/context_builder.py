"""Deterministic, provenance-labelled context selection under explicit budgets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .errors import InvalidDomainValueError
from .evidence import EvidenceSourceType, TrustClassification
from .values import ArtifactId, EvidenceId, IncidentId

CONTEXT_SCHEMA_VERSION: Final = "1.0.0"
MAX_CONTEXT_CANDIDATES: Final = 256
MAX_CONTEXT_SUMMARY_CHARS: Final = 4_096
MAX_CONTEXT_TOKENS: Final = 100_000


class ContextContentKind(StrEnum):
    """Only bounded derived content may enter model context; raw telemetry is absent."""

    SUMMARY = "SUMMARY"
    QUARANTINE_METADATA = "QUARANTINE_METADATA"


class ContextOmissionReason(StrEnum):
    TOKEN_BUDGET = "TOKEN_BUDGET"
    ITEM_LIMIT = "ITEM_LIMIT"


def _text(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise InvalidDomainValueError(f"context {field} must be bounded non-null text")
    return normalized


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    key: str
    incident_id: IncidentId
    evidence_id: EvidenceId
    artifact_id: ArtifactId
    source_type: EvidenceSourceType
    trust: TrustClassification
    content_kind: ContextContentKind
    summary: str
    priority: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _text(self.key, field="key", maximum=128))
        object.__setattr__(
            self,
            "summary",
            _text(self.summary, field="summary", maximum=MAX_CONTEXT_SUMMARY_CHARS),
        )
        if (
            not isinstance(self.priority, int)
            or isinstance(self.priority, bool)
            or not 0 <= self.priority <= 100
        ):
            raise InvalidDomainValueError("context priority must be an integer from 0 to 100")

    @property
    def estimated_tokens(self) -> int:
        """Stable conservative UTF-8 byte estimate; provider accounting remains separate."""
        return max(1, (len(self.summary.encode("utf-8")) + 3) // 4)


@dataclass(frozen=True, slots=True)
class ContextOmission:
    key: str
    evidence_id: EvidenceId
    artifact_id: ArtifactId
    estimated_tokens: int
    reason: ContextOmissionReason


@dataclass(frozen=True, slots=True)
class BudgetedContext:
    incident_id: IncidentId
    items: tuple[ContextCandidate, ...]
    omissions: tuple[ContextOmission, ...]
    used_tokens: int
    token_budget: int
    item_limit: int
    schema_version: str = CONTEXT_SCHEMA_VERSION


def build_budgeted_context(
    candidates: tuple[ContextCandidate, ...],
    *,
    incident_id: IncidentId,
    token_budget: int,
    item_limit: int,
) -> BudgetedContext:
    """Select whole summaries by priority and record every deterministic omission."""
    if len(candidates) > MAX_CONTEXT_CANDIDATES:
        raise InvalidDomainValueError("context candidate limit exceeded")
    if (
        not isinstance(token_budget, int)
        or isinstance(token_budget, bool)
        or not 1 <= token_budget <= MAX_CONTEXT_TOKENS
    ):
        raise InvalidDomainValueError("context token budget is outside bounds")
    if (
        not isinstance(item_limit, int)
        or isinstance(item_limit, bool)
        or not 1 <= item_limit <= MAX_CONTEXT_CANDIDATES
    ):
        raise InvalidDomainValueError("context item limit is outside bounds")
    if any(item.incident_id != incident_id for item in candidates):
        raise InvalidDomainValueError("context candidates must belong to one Incident")
    if len({item.key for item in candidates}) != len(candidates):
        raise InvalidDomainValueError("context candidate keys must be unique")
    if len({item.evidence_id for item in candidates}) != len(candidates):
        raise InvalidDomainValueError("context Evidence references must be unique")

    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                -item.priority,
                item.source_type.value,
                item.evidence_id.value,
                item.key,
            ),
        )
    )
    selected: list[ContextCandidate] = []
    omissions: list[ContextOmission] = []
    used_tokens = 0
    for item in ordered:
        if len(selected) >= item_limit:
            reason = ContextOmissionReason.ITEM_LIMIT
        elif used_tokens + item.estimated_tokens > token_budget:
            reason = ContextOmissionReason.TOKEN_BUDGET
        else:
            selected.append(item)
            used_tokens += item.estimated_tokens
            continue
        omissions.append(
            ContextOmission(
                key=item.key,
                evidence_id=item.evidence_id,
                artifact_id=item.artifact_id,
                estimated_tokens=item.estimated_tokens,
                reason=reason,
            )
        )
    return BudgetedContext(
        incident_id=incident_id,
        items=tuple(selected),
        omissions=tuple(omissions),
        used_tokens=used_tokens,
        token_budget=token_budget,
        item_limit=item_limit,
    )
