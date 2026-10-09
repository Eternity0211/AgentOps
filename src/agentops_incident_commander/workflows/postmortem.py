"""Strict model output for the constrained postmortem node."""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentops_incident_commander.domain import PostmortemFactKind

POSTMORTEM_OUTLINE_SCHEMA_VERSION: Final[Literal["1.0.0"]] = "1.0.0"
MAX_POSTMORTEM_SECTIONS = len(PostmortemFactKind)
MAX_POSTMORTEM_FACT_REFERENCES = 64
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"

Identifier = Annotated[str, Field(pattern=_ID_PATTERN)]


class StrictPostmortemModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PostmortemOutlineSection(StrictPostmortemModel):
    kind: PostmortemFactKind
    fact_ids: tuple[Identifier, ...] = Field(
        min_length=1, max_length=MAX_POSTMORTEM_FACT_REFERENCES
    )

    @field_validator("fact_ids")
    @classmethod
    def require_unique_fact_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("postmortem section fact references must be unique")
        return value


class PostmortemOutline(StrictPostmortemModel):
    """The model may only arrange server-supplied fact IDs; it cannot author facts."""

    schema_version: Literal["1.0.0"]
    incident_id: Identifier
    sections: tuple[PostmortemOutlineSection, ...] = Field(
        min_length=1, max_length=MAX_POSTMORTEM_SECTIONS
    )

    @model_validator(mode="after")
    def require_unique_sections_and_facts(self) -> PostmortemOutline:
        if len({section.kind for section in self.sections}) != len(self.sections):
            raise ValueError("postmortem outline section kinds must be unique")
        fact_ids = tuple(fact_id for section in self.sections for fact_id in section.fact_ids)
        if len(fact_ids) > MAX_POSTMORTEM_FACT_REFERENCES or len(set(fact_ids)) != len(fact_ids):
            raise ValueError(
                "postmortem outline fact references must be globally unique and bounded"
            )
        return self
