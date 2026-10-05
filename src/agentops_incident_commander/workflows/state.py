"""Strict versioned Pydantic state for durable Diagnosis workflows."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentops_incident_commander.domain import InvalidDomainValueError, SemanticVersion

DIAGNOSIS_GRAPH_STATE_SCHEMA_VERSION = "1.0.0"
MAX_GRAPH_STATE_REFERENCES = 512
MAX_GRAPH_MIGRATIONS = 32
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_VERSION_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"

Identifier = Annotated[str, Field(pattern=_ID_PATTERN)]
Digest = Annotated[str, Field(pattern=_HASH_PATTERN)]
Version = Annotated[str, Field(pattern=_VERSION_PATTERN)]


class StrictStateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class GraphPhase(StrEnum):
    CONTEXT_LOADING = "CONTEXT_LOADING"
    PLANNING = "PLANNING"
    INVESTIGATING = "INVESTIGATING"
    HYPOTHESIS = "HYPOTHESIS"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"
    COMPLETE = "COMPLETE"


class GraphPromptReference(StrictStateModel):
    prompt_id: Identifier
    version: Version
    content_fingerprint: Digest


class GraphBudgetState(StrictStateModel):
    max_steps: int = Field(ge=1, le=128)
    used_steps: int = Field(ge=0, le=128)
    max_replans: int = Field(ge=0, le=16)
    used_replans: int = Field(ge=0, le=16)
    max_tool_calls: int = Field(ge=0, le=512)
    used_tool_calls: int = Field(ge=0, le=512)
    max_model_calls: int = Field(ge=1, le=128)
    used_model_calls: int = Field(ge=0, le=128)
    max_tokens: int = Field(ge=1, le=100_000_000)
    used_tokens: int = Field(ge=0, le=100_000_000)
    max_cost_nanounits: int = Field(ge=0, le=10**18)
    used_cost_nanounits: int = Field(ge=0, le=10**18)

    @model_validator(mode="after")
    def validate_consumption(self) -> GraphBudgetState:
        for used, maximum in (
            (self.used_steps, self.max_steps),
            (self.used_replans, self.max_replans),
            (self.used_tool_calls, self.max_tool_calls),
            (self.used_model_calls, self.max_model_calls),
            (self.used_tokens, self.max_tokens),
            (self.used_cost_nanounits, self.max_cost_nanounits),
        ):
            if used > maximum:
                raise ValueError("graph budget consumption cannot exceed its maximum")
        return self


class DiagnosisGraphState(StrictStateModel):
    state_schema_version: Literal["1.0.0"]
    graph_version: Version
    tenant_id: Identifier
    incident_id: Identifier
    workflow_run_id: Identifier
    correlation_id: Identifier
    causation_id: Identifier
    phase: GraphPhase
    budgets: GraphBudgetState
    prompt: GraphPromptReference | None = None
    tool_call_ids: tuple[Identifier, ...] = Field(default=(), max_length=MAX_GRAPH_STATE_REFERENCES)
    model_call_ids: tuple[Identifier, ...] = Field(
        default=(), max_length=MAX_GRAPH_STATE_REFERENCES
    )
    evidence_ids: tuple[Identifier, ...] = Field(default=(), max_length=MAX_GRAPH_STATE_REFERENCES)
    gate_decision_fingerprint: Digest | None = None
    error_code: Identifier | None = None
    checkpoint_sequence: int = Field(ge=0)
    updated_at: datetime

    @field_validator("tool_call_ids", "model_call_ids", "evidence_ids")
    @classmethod
    def require_unique_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("graph state references must be unique")
        return value

    @field_validator("updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("graph state timestamp must be timezone-aware")
        return value.astimezone(UTC)


GraphStateMigration = Callable[[dict[str, Any]], dict[str, Any]]


class GraphStateMigrationRegistry:
    """Sequential, fail-closed migration registry for persisted state snapshots."""

    def __init__(self, *, current_version: str = DIAGNOSIS_GRAPH_STATE_SCHEMA_VERSION) -> None:
        self._current = SemanticVersion(current_version)
        self._migrations: dict[SemanticVersion, tuple[SemanticVersion, GraphStateMigration]] = {}

    def register(self, source: str, target: str, migration: GraphStateMigration) -> None:
        source_version = SemanticVersion(source)
        target_version = SemanticVersion(target)
        if source_version >= target_version:
            raise InvalidDomainValueError("graph state migration must advance the version")
        if source_version in self._migrations:
            raise InvalidDomainValueError("graph state migration source is already registered")
        self._migrations[source_version] = (target_version, migration)

    def load(self, snapshot: Mapping[str, Any]) -> DiagnosisGraphState:
        raw = copy.deepcopy(dict(snapshot))
        version_value = raw.get("state_schema_version")
        if not isinstance(version_value, str):
            raise InvalidDomainValueError("graph state schema version is missing")
        version = SemanticVersion(version_value)
        if version > self._current:
            raise InvalidDomainValueError("future graph state schema version is unsupported")
        for _ in range(MAX_GRAPH_MIGRATIONS):
            if version == self._current:
                return DiagnosisGraphState.model_validate_json(json.dumps(raw))
            entry = self._migrations.get(version)
            if entry is None:
                raise InvalidDomainValueError("graph state migration path is incomplete")
            target, migration = entry
            migrated = migration(copy.deepcopy(raw))
            if (
                not isinstance(migrated, dict)
                or migrated.get("state_schema_version") != target.value
            ):
                raise InvalidDomainValueError("graph state migration returned an invalid target")
            raw = migrated
            version = target
        raise InvalidDomainValueError("graph state migration limit exceeded")


def canonical_graph_state_bytes(state: DiagnosisGraphState) -> bytes:
    """Return stable checkpoint bytes without adding any content-bearing fields."""
    return json.dumps(
        state.model_dump(mode="json", exclude_none=False),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
