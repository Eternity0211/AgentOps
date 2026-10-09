"""Credential-free deterministic adapter for constrained postmortem drafting."""

from __future__ import annotations

import hashlib
from enum import StrEnum

from agentops_incident_commander.application.postmortem import (
    PostmortemModelRefusal,
    PostmortemModelRequest,
    PostmortemModelResult,
)
from agentops_incident_commander.domain import (
    InvalidDomainValueError,
    ModelCost,
    ModelCostSource,
    ModelMetering,
    ModelTokenUsage,
    PostmortemFactKind,
    PromptDefinition,
    SemanticVersion,
    Sha256Digest,
)
from agentops_incident_commander.workflows import (
    POSTMORTEM_OUTLINE_SCHEMA_VERSION,
    PostmortemOutline,
    PostmortemOutlineSection,
)

POSTMORTEM_MOCK_MODEL_VERSION = "postmortem-mock/1.0.0"


class PostmortemMockScenario(StrEnum):
    VALID = "VALID"
    FABRICATED_REFERENCE = "FABRICATED_REFERENCE"
    OMITTED_FACT = "OMITTED_FACT"
    WRONG_SECTION = "WRONG_SECTION"
    MALFORMED = "MALFORMED"
    TIMEOUT = "TIMEOUT"
    REFUSAL = "REFUSAL"


class DeterministicPostmortemMockModel:
    """Arrange supplied IDs deterministically without interpreting factual text."""

    def __init__(self, scenario: PostmortemMockScenario = PostmortemMockScenario.VALID) -> None:
        if not isinstance(scenario, PostmortemMockScenario):
            raise InvalidDomainValueError("postmortem mock scenario is invalid")
        self._scenario = scenario

    async def draft(
        self, request: PostmortemModelRequest, prompt: PromptDefinition
    ) -> PostmortemModelResult:
        if not isinstance(request, PostmortemModelRequest) or not isinstance(
            prompt, PromptDefinition
        ):
            raise InvalidDomainValueError("postmortem mock requires typed inputs")
        if self._scenario is PostmortemMockScenario.TIMEOUT:
            raise TimeoutError("deterministic postmortem mock timeout")
        if self._scenario is PostmortemMockScenario.REFUSAL:
            raise PostmortemModelRefusal("deterministic postmortem mock refusal")
        if self._scenario is PostmortemMockScenario.MALFORMED:
            raise InvalidDomainValueError("deterministic postmortem mock malformed output")

        grouped: dict[PostmortemFactKind, list[str]] = {}
        for fact in request.facts:
            grouped.setdefault(PostmortemFactKind(fact.kind), []).append(fact.fact_id.value)
        sections = [
            PostmortemOutlineSection(kind=kind, fact_ids=tuple(fact_ids))
            for kind, fact_ids in grouped.items()
        ]
        if self._scenario is PostmortemMockScenario.FABRICATED_REFERENCE:
            sections[0] = sections[0].model_copy(
                update={"fact_ids": (*sections[0].fact_ids, "fact-fabricated")}
            )
        elif self._scenario is PostmortemMockScenario.OMITTED_FACT:
            first = sections[0]
            if len(first.fact_ids) == 1:
                sections.pop(0)
            else:
                sections[0] = first.model_copy(update={"fact_ids": first.fact_ids[1:]})
        elif self._scenario is PostmortemMockScenario.WRONG_SECTION:
            first = sections[0]
            wrong = next(kind for kind in PostmortemFactKind if kind is not first.kind)
            sections[0] = first.model_copy(update={"kind": wrong})
        outline = PostmortemOutline(
            schema_version=POSTMORTEM_OUTLINE_SCHEMA_VERSION,
            incident_id=request.incident_id.value,
            sections=tuple(sections),
        )
        encoded = outline.model_dump_json().encode()
        input_tokens = max(1, len(request.fingerprint.value) // 4 + len(request.facts) * 8)
        output_tokens = max(1, len(encoded) // 4)
        metering = ModelMetering(
            ModelTokenUsage(input_tokens, output_tokens, 0, 0, input_tokens + output_tokens),
            ModelCost(
                0,
                "USD",
                ModelCostSource.RATE_CARD_CALCULATED,
                SemanticVersion("1.0.0"),
            ),
        )
        return PostmortemModelResult(
            outline,
            metering,
            Sha256Digest(hashlib.sha256(encoded).hexdigest()),
        )
