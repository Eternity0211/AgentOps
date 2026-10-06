"""Immutable versioned Prompt Registry contracts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from .errors import InvalidDomainValueError, PromptNotFoundError
from .tools import SemanticVersion
from .values import (
    ActorId,
    CausationId,
    CorrelationId,
    PromptId,
    Sha256Digest,
    as_utc,
)

PROMPT_DEFINITION_SCHEMA_VERSION = "1.0.0"
MAX_PROMPT_CONTENT_BYTES = 64 * 1024
MAX_PROMPT_OUTPUT_TOKENS = 32_768
MAX_PROMPT_TEMPERATURE_BASIS_POINTS = 20_000
MAX_PROMPT_SEED = 2**31 - 1
MIN_PROMPT_SEED = -(2**31)
MAX_PROMPT_REGRESSION_FIXTURES = 128

_MODEL_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def _model_component(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _MODEL_COMPONENT.fullmatch(value) is None:
        raise InvalidDomainValueError(f"Prompt {field} is invalid")
    return value


class PromptPurpose(StrEnum):
    DIAGNOSIS = "DIAGNOSIS"
    REMEDIATION = "REMEDIATION"
    POSTMORTEM = "POSTMORTEM"


class PromptLifecycleStatus(StrEnum):
    DRAFT = "DRAFT"
    EVALUATED = "EVALUATED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class PromptModelParameters:
    """Exact bounded generation parameters retained for reproducibility."""

    provider: str
    model: str
    temperature_basis_points: int
    top_p_basis_points: int
    max_output_tokens: int
    seed: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _model_component(self.provider, field="provider"))
        object.__setattr__(self, "model", _model_component(self.model, field="model"))
        for name, value in (
            ("temperature", self.temperature_basis_points),
            ("top-p", self.top_p_basis_points),
            ("output token limit", self.max_output_tokens),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise InvalidDomainValueError(f"Prompt {name} must be an integer")
        if not 0 <= self.temperature_basis_points <= MAX_PROMPT_TEMPERATURE_BASIS_POINTS:
            raise InvalidDomainValueError("Prompt temperature is outside the bounded range")
        if not 1 <= self.top_p_basis_points <= 10_000:
            raise InvalidDomainValueError("Prompt top-p is outside the bounded range")
        if not 1 <= self.max_output_tokens <= MAX_PROMPT_OUTPUT_TOKENS:
            raise InvalidDomainValueError("Prompt output token limit is outside the bounded range")
        if self.seed is not None and (
            not isinstance(self.seed, int)
            or isinstance(self.seed, bool)
            or not MIN_PROMPT_SEED <= self.seed <= MAX_PROMPT_SEED
        ):
            raise InvalidDomainValueError("Prompt seed is outside the bounded integer range")


@dataclass(frozen=True, slots=True)
class PromptSchemaCompatibility:
    """Exact input/output schema versions expected by a Prompt version."""

    input_version: SemanticVersion
    output_version: SemanticVersion
    memory_context_version: SemanticVersion | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.input_version, SemanticVersion) or not isinstance(
            self.output_version, SemanticVersion
        ):
            raise InvalidDomainValueError("Prompt schema compatibility versions must be semantic")
        if self.memory_context_version is not None and not isinstance(
            self.memory_context_version, SemanticVersion
        ):
            raise InvalidDomainValueError("Prompt memory context version must be semantic")


@dataclass(frozen=True, slots=True)
class PromptTraceLink:
    """Creation trace retained without embedding request or response content."""

    actor_id: ActorId
    correlation_id: CorrelationId
    causation_id: CausationId
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, ActorId):
            raise InvalidDomainValueError("Prompt trace actor is invalid")
        if not isinstance(self.correlation_id, CorrelationId) or not isinstance(
            self.causation_id, CausationId
        ):
            raise InvalidDomainValueError("Prompt trace correlation is invalid")
        object.__setattr__(self, "created_at", as_utc(self.created_at))


@dataclass(frozen=True, slots=True)
class PromptVersionReference:
    prompt_id: PromptId
    version: SemanticVersion

    def __post_init__(self) -> None:
        if not isinstance(self.prompt_id, PromptId) or not isinstance(
            self.version, SemanticVersion
        ):
            raise InvalidDomainValueError("Prompt version reference is invalid")


class PromptRegressionContext(StrEnum):
    WITHOUT_MEMORY = "WITHOUT_MEMORY"
    WITH_MEMORY = "WITH_MEMORY"


@dataclass(frozen=True, slots=True)
class PromptRegressionFixtureResult:
    fixture_id: str
    passed: bool
    context: PromptRegressionContext = PromptRegressionContext.WITHOUT_MEMORY
    unsupported_conclusions: int = 0
    fabricated_references: int = 0
    authorization_violations: int = 0
    ground_truth_visible: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fixture_id, str)
            or _MODEL_COMPONENT.fullmatch(self.fixture_id) is None
        ):
            raise InvalidDomainValueError("Prompt regression fixture ID is invalid")
        if not isinstance(self.passed, bool):
            raise InvalidDomainValueError("Prompt regression fixture result must be boolean")
        if not isinstance(self.context, PromptRegressionContext):
            raise InvalidDomainValueError("Prompt regression fixture context is invalid")
        for name, value in (
            ("unsupported conclusion", self.unsupported_conclusions),
            ("fabricated reference", self.fabricated_references),
            ("authorization violation", self.authorization_violations),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10_000:
                raise InvalidDomainValueError(f"Prompt regression {name} count is invalid")
        if not isinstance(self.ground_truth_visible, bool):
            raise InvalidDomainValueError("Prompt regression Ground Truth flag is invalid")

    @property
    def safe(self) -> bool:
        return (
            self.passed
            and self.unsupported_conclusions == 0
            and self.fabricated_references == 0
            and self.authorization_violations == 0
            and not self.ground_truth_visible
        )


@dataclass(frozen=True, slots=True)
class PromptRegressionEvaluation:
    prompt: PromptVersionReference
    suite_version: SemanticVersion
    results: tuple[PromptRegressionFixtureResult, ...]
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, PromptVersionReference) or not isinstance(
            self.suite_version, SemanticVersion
        ):
            raise InvalidDomainValueError("Prompt regression evaluation identity is invalid")
        if (
            not isinstance(self.results, tuple)
            or not self.results
            or len(self.results) > MAX_PROMPT_REGRESSION_FIXTURES
            or any(not isinstance(item, PromptRegressionFixtureResult) for item in self.results)
            or len({(item.fixture_id, item.context) for item in self.results}) != len(self.results)
        ):
            raise InvalidDomainValueError("Prompt regression results must be unique and bounded")
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))

    @property
    def passed(self) -> bool:
        return all(item.safe for item in self.results)

    @property
    def memory_comparison_passed(self) -> bool:
        by_fixture: dict[str, dict[PromptRegressionContext, PromptRegressionFixtureResult]] = {}
        for item in self.results:
            by_fixture.setdefault(item.fixture_id, {})[item.context] = item
        expected = {PromptRegressionContext.WITHOUT_MEMORY, PromptRegressionContext.WITH_MEMORY}
        if any(set(values) != expected for values in by_fixture.values()):
            return False
        return self.passed and all(
            with_memory.unsupported_conclusions <= without.unsupported_conclusions
            and with_memory.fabricated_references <= without.fabricated_references
            and with_memory.authorization_violations <= without.authorization_violations
            and not with_memory.ground_truth_visible
            for values in by_fixture.values()
            for without, with_memory in (
                (
                    values[PromptRegressionContext.WITHOUT_MEMORY],
                    values[PromptRegressionContext.WITH_MEMORY],
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    """One immutable Prompt version and all metadata required to reproduce it."""

    prompt_id: PromptId
    version: SemanticVersion
    purpose: PromptPurpose
    content: str
    content_fingerprint: Sha256Digest
    model_parameters: PromptModelParameters
    schema_compatibility: PromptSchemaCompatibility
    trace: PromptTraceLink
    status: PromptLifecycleStatus = PromptLifecycleStatus.DRAFT
    rollback_predecessor: PromptVersionReference | None = None
    schema_version: str = PROMPT_DEFINITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.prompt_id, PromptId) or not isinstance(
            self.version, SemanticVersion
        ):
            raise InvalidDomainValueError("Prompt identity and version are invalid")
        if not isinstance(self.purpose, PromptPurpose):
            raise InvalidDomainValueError("Prompt purpose is invalid")
        if (
            not isinstance(self.content, str)
            or not self.content.strip()
            or "\x00" in self.content
            or "\r" in self.content
        ):
            raise InvalidDomainValueError("Prompt content must be non-empty normalized text")
        if len(self.content.encode("utf-8")) > MAX_PROMPT_CONTENT_BYTES:
            raise InvalidDomainValueError("Prompt content exceeds the byte limit")
        expected = Sha256Digest(hashlib.sha256(self.content.encode("utf-8")).hexdigest())
        if self.content_fingerprint != expected:
            raise InvalidDomainValueError("Prompt content fingerprint does not match content")
        if not isinstance(self.model_parameters, PromptModelParameters):
            raise InvalidDomainValueError("Prompt model parameters are invalid")
        if not isinstance(self.schema_compatibility, PromptSchemaCompatibility):
            raise InvalidDomainValueError("Prompt schema compatibility is invalid")
        if not isinstance(self.trace, PromptTraceLink):
            raise InvalidDomainValueError("Prompt trace link is invalid")
        if not isinstance(self.status, PromptLifecycleStatus):
            raise InvalidDomainValueError("Prompt lifecycle status is invalid")
        if self.schema_version != PROMPT_DEFINITION_SCHEMA_VERSION:
            raise InvalidDomainValueError("Prompt definition schema version is unsupported")
        predecessor = self.rollback_predecessor
        if predecessor is not None and (
            not isinstance(predecessor, PromptVersionReference)
            or predecessor.prompt_id != self.prompt_id
            or predecessor.version >= self.version
        ):
            raise InvalidDomainValueError("Prompt rollback predecessor must be an earlier version")

    @classmethod
    def create(
        cls,
        *,
        prompt_id: PromptId,
        version: SemanticVersion,
        purpose: PromptPurpose,
        content: str,
        model_parameters: PromptModelParameters,
        schema_compatibility: PromptSchemaCompatibility,
        trace: PromptTraceLink,
        status: PromptLifecycleStatus = PromptLifecycleStatus.DRAFT,
        rollback_predecessor: PromptVersionReference | None = None,
    ) -> PromptDefinition:
        fingerprint = Sha256Digest(hashlib.sha256(content.encode("utf-8")).hexdigest())
        return cls(
            prompt_id,
            version,
            purpose,
            content,
            fingerprint,
            model_parameters,
            schema_compatibility,
            trace,
            status,
            rollback_predecessor,
        )

    @property
    def identity(self) -> tuple[PromptId, SemanticVersion]:
        return (self.prompt_id, self.version)

    @property
    def memory_aware(self) -> bool:
        return self.schema_compatibility.memory_context_version is not None


class PromptRegistry:
    """Read-only registry for exact and active Prompt version resolution."""

    def __init__(self, definitions: tuple[PromptDefinition, ...]) -> None:
        if not isinstance(definitions, tuple) or not definitions:
            raise InvalidDomainValueError("Prompt Registry requires at least one definition")
        by_identity: dict[tuple[PromptId, SemanticVersion], PromptDefinition] = {}
        active: dict[PromptId, PromptDefinition] = {}
        family_purpose: dict[PromptId, PromptPurpose] = {}
        for definition in definitions:
            if not isinstance(definition, PromptDefinition):
                raise InvalidDomainValueError("Prompt Registry entries must be definitions")
            if definition.identity in by_identity:
                raise InvalidDomainValueError("Prompt Registry contains a duplicate version")
            expected_purpose = family_purpose.setdefault(definition.prompt_id, definition.purpose)
            if definition.purpose is not expected_purpose:
                raise InvalidDomainValueError(
                    "Prompt family purpose cannot change between versions"
                )
            if definition.status is PromptLifecycleStatus.ACTIVE:
                if definition.prompt_id in active:
                    raise InvalidDomainValueError("Prompt Registry has multiple active versions")
                active[definition.prompt_id] = definition
            by_identity[definition.identity] = definition
        for definition in definitions:
            predecessor = definition.rollback_predecessor
            if (
                predecessor is not None
                and (
                    predecessor.prompt_id,
                    predecessor.version,
                )
                not in by_identity
            ):
                raise InvalidDomainValueError(
                    "Prompt rollback predecessor must resolve inside the Registry"
                )
        self._definitions = MappingProxyType(by_identity)
        self._active = MappingProxyType(active)

    def resolve(self, prompt_id: PromptId, version: SemanticVersion) -> PromptDefinition:
        definition = self._definitions.get((prompt_id, version))
        if definition is None:
            raise PromptNotFoundError("requested Prompt identity and version are not registered")
        return definition

    def active(self, prompt_id: PromptId) -> PromptDefinition:
        definition = self._active.get(prompt_id)
        if definition is None:
            raise PromptNotFoundError("requested Prompt family has no active version")
        return definition

    def catalog(self, *, purpose: PromptPurpose | None = None) -> tuple[PromptDefinition, ...]:
        return tuple(
            sorted(
                (
                    definition
                    for definition in self._definitions.values()
                    if purpose is None or definition.purpose is purpose
                ),
                key=lambda definition: (
                    definition.prompt_id.value,
                    definition.version.parts,
                ),
            )
        )
