"""Evidence-bound contracts for constrained postmortem drafting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import InvalidDomainValueError
from .prompts import PromptVersionReference
from .values import (
    ActorId,
    EvidenceId,
    IncidentId,
    ModelCallId,
    PostmortemFactId,
    Sha256Digest,
    TenantId,
    as_utc,
)

POSTMORTEM_FACT_SCHEMA_VERSION = "1.0.0"
POSTMORTEM_DRAFT_SCHEMA_VERSION = "1.0.0"
MAX_POSTMORTEM_FACTS = 64
MAX_FACT_EVIDENCE_REFERENCES = 16
MAX_FACT_STATEMENT_LENGTH = 512


class PostmortemFactKind(StrEnum):
    IMPACT = "IMPACT"
    TIMELINE = "TIMELINE"
    ROOT_CAUSE = "ROOT_CAUSE"
    RECOVERY = "RECOVERY"
    VERIFICATION = "VERIFICATION"


def _statement(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidDomainValueError("postmortem fact statement must be text")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_FACT_STATEMENT_LENGTH
        or any(character in normalized for character in ("\r", "\n", "\x00"))
    ):
        raise InvalidDomainValueError("postmortem fact statement must be bounded single-line text")
    return normalized


@dataclass(frozen=True, slots=True)
class ConfirmedPostmortemFact:
    """One human or deterministic-component confirmed fact with Evidence support."""

    id: PostmortemFactId
    tenant_id: TenantId
    incident_id: IncidentId
    kind: PostmortemFactKind
    statement: str
    evidence_ids: tuple[EvidenceId, ...]
    confirmed_by: ActorId
    confirmed_at: datetime
    schema_version: str = POSTMORTEM_FACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, PostmortemFactId)
            or not isinstance(self.tenant_id, TenantId)
            or not isinstance(self.incident_id, IncidentId)
        ):
            raise InvalidDomainValueError("postmortem fact identity is invalid")
        if not isinstance(self.kind, PostmortemFactKind):
            raise InvalidDomainValueError("postmortem fact kind is invalid")
        object.__setattr__(self, "statement", _statement(self.statement))
        if (
            not isinstance(self.evidence_ids, tuple)
            or not self.evidence_ids
            or len(self.evidence_ids) > MAX_FACT_EVIDENCE_REFERENCES
            or any(not isinstance(item, EvidenceId) for item in self.evidence_ids)
            or len(set(self.evidence_ids)) != len(self.evidence_ids)
        ):
            raise InvalidDomainValueError(
                "postmortem fact Evidence references must be unique and bounded"
            )
        if not isinstance(self.confirmed_by, ActorId):
            raise InvalidDomainValueError("postmortem fact confirmer is invalid")
        object.__setattr__(self, "confirmed_at", as_utc(self.confirmed_at))
        if self.schema_version != POSTMORTEM_FACT_SCHEMA_VERSION:
            raise InvalidDomainValueError("postmortem fact schema version is unsupported")

    @property
    def fingerprint(self) -> Sha256Digest:
        payload = {
            "confirmed_at": self.confirmed_at.isoformat(),
            "confirmed_by": self.confirmed_by.value,
            "evidence_ids": [item.value for item in self.evidence_ids],
            "fact_id": self.id.value,
            "incident_id": self.incident_id.value,
            "kind": self.kind.value,
            "schema_version": self.schema_version,
            "statement": self.statement,
            "tenant_id": self.tenant_id.value,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(encoded).hexdigest())


@dataclass(frozen=True, slots=True)
class PostmortemDraftSection:
    """A model-selected ordering whose content is copied from confirmed facts."""

    kind: PostmortemFactKind
    facts: tuple[ConfirmedPostmortemFact, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PostmortemFactKind):
            raise InvalidDomainValueError("postmortem section kind is invalid")
        if (
            not isinstance(self.facts, tuple)
            or not self.facts
            or len(self.facts) > MAX_POSTMORTEM_FACTS
            or any(not isinstance(item, ConfirmedPostmortemFact) for item in self.facts)
            or any(item.kind is not self.kind for item in self.facts)
            or len({item.id for item in self.facts}) != len(self.facts)
        ):
            raise InvalidDomainValueError(
                "postmortem section facts must be unique, bounded, and kind-matched"
            )


@dataclass(frozen=True, slots=True)
class PostmortemDraft:
    """Immutable generated draft with no model-authored factual text."""

    tenant_id: TenantId
    incident_id: IncidentId
    prompt: PromptVersionReference
    prompt_fingerprint: Sha256Digest
    model_call_id: ModelCallId
    sections: tuple[PostmortemDraftSection, ...]
    generated_at: datetime
    schema_version: str = POSTMORTEM_DRAFT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, TenantId) or not isinstance(self.incident_id, IncidentId):
            raise InvalidDomainValueError("postmortem draft scope is invalid")
        if not isinstance(self.prompt, PromptVersionReference) or not isinstance(
            self.prompt_fingerprint, Sha256Digest
        ):
            raise InvalidDomainValueError("postmortem draft Prompt binding is invalid")
        if not isinstance(self.model_call_id, ModelCallId):
            raise InvalidDomainValueError("postmortem draft model call is invalid")
        if (
            not isinstance(self.sections, tuple)
            or not self.sections
            or len(self.sections) > len(PostmortemFactKind)
            or any(not isinstance(item, PostmortemDraftSection) for item in self.sections)
            or len({item.kind for item in self.sections}) != len(self.sections)
        ):
            raise InvalidDomainValueError("postmortem draft sections must be unique and bounded")
        facts = tuple(fact for section in self.sections for fact in section.facts)
        if len(facts) > MAX_POSTMORTEM_FACTS or len({item.id for item in facts}) != len(facts):
            raise InvalidDomainValueError(
                "postmortem draft facts must be globally unique and bounded"
            )
        if any(
            item.tenant_id != self.tenant_id or item.incident_id != self.incident_id
            for item in facts
        ):
            raise InvalidDomainValueError(
                "postmortem draft facts must share its tenant and Incident"
            )
        object.__setattr__(self, "generated_at", as_utc(self.generated_at))
        if self.schema_version != POSTMORTEM_DRAFT_SCHEMA_VERSION:
            raise InvalidDomainValueError("postmortem draft schema version is unsupported")

    @property
    def fact_ids(self) -> tuple[PostmortemFactId, ...]:
        return tuple(fact.id for section in self.sections for fact in section.facts)

    @property
    def evidence_ids(self) -> tuple[EvidenceId, ...]:
        return tuple(
            dict.fromkeys(
                evidence_id
                for section in self.sections
                for fact in section.facts
                for evidence_id in fact.evidence_ids
            )
        )

    @property
    def fingerprint(self) -> Sha256Digest:
        payload = {
            "generated_at": self.generated_at.isoformat(),
            "incident_id": self.incident_id.value,
            "model_call_id": self.model_call_id.value,
            "prompt_fingerprint": self.prompt_fingerprint.value,
            "prompt_id": self.prompt.prompt_id.value,
            "prompt_version": self.prompt.version.value,
            "schema_version": self.schema_version,
            "sections": [
                {
                    "kind": section.kind.value,
                    "facts": [fact.fingerprint.value for fact in section.facts],
                }
                for section in self.sections
            ],
            "tenant_id": self.tenant_id.value,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(encoded).hexdigest())

    def render_markdown(self) -> str:
        """Render only exact confirmed statements and their resolvable Evidence IDs."""
        lines = [f"# Incident {self.incident_id.value} postmortem", ""]
        for section in self.sections:
            lines.extend((f"## {section.kind.value.replace('_', ' ').title()}", ""))
            for fact in section.facts:
                references = ", ".join(item.value for item in fact.evidence_ids)
                lines.append(f"- {fact.statement} [Evidence: {references}]")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
