"""Content-free, reproducible model-call trace contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .errors import InvalidDomainValueError
from .prompts import PromptDefinition, PromptLifecycleStatus, PromptVersionReference
from .tools import SemanticVersion
from .values import (
    CausationId,
    CorrelationId,
    IncidentId,
    ModelCallId,
    Sha256Digest,
    TenantId,
    WorkflowRunId,
    as_utc,
)

MODEL_CALL_TRACE_SCHEMA_VERSION = "1.0.0"
MAX_MODEL_TOKENS = 100_000_000
MAX_MODEL_COST_NANOUNITS = 10**18
_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class ModelCallStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    REFUSED = "REFUSED"


class ModelCostSource(StrEnum):
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    RATE_CARD_CALCULATED = "RATE_CARD_CALCULATED"


class ModelMeteringUnavailableReason(StrEnum):
    PROVIDER_DID_NOT_RETURN = "PROVIDER_DID_NOT_RETURN"
    CALL_FAILED_BEFORE_METERING = "CALL_FAILED_BEFORE_METERING"


@dataclass(frozen=True, slots=True)
class ModelTokenUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        values = (
            self.input_tokens,
            self.output_tokens,
            self.cached_input_tokens,
            self.reasoning_tokens,
            self.total_tokens,
        )
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= MAX_MODEL_TOKENS
            for value in values
        ):
            raise InvalidDomainValueError("model token usage must contain bounded integers")
        if self.cached_input_tokens > self.input_tokens:
            raise InvalidDomainValueError("cached input tokens cannot exceed input tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise InvalidDomainValueError("reasoning tokens cannot exceed output tokens")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise InvalidDomainValueError("model total tokens must equal input plus output")


@dataclass(frozen=True, slots=True)
class ModelCost:
    amount_nanounits: int
    currency: str
    source: ModelCostSource
    rate_card_version: SemanticVersion

    def __post_init__(self) -> None:
        if (
            not isinstance(self.amount_nanounits, int)
            or isinstance(self.amount_nanounits, bool)
            or not 0 <= self.amount_nanounits <= MAX_MODEL_COST_NANOUNITS
        ):
            raise InvalidDomainValueError("model cost must be bounded integer nanounits")
        if not isinstance(self.currency, str) or _CURRENCY.fullmatch(self.currency) is None:
            raise InvalidDomainValueError("model cost currency must be an uppercase ISO code")
        if not isinstance(self.source, ModelCostSource) or not isinstance(
            self.rate_card_version, SemanticVersion
        ):
            raise InvalidDomainValueError("model cost provenance is invalid")


@dataclass(frozen=True, slots=True)
class ModelMetering:
    token_usage: ModelTokenUsage | None
    cost: ModelCost | None
    unavailable_reason: ModelMeteringUnavailableReason | None = None

    def __post_init__(self) -> None:
        available = self.token_usage is not None and self.cost is not None
        unavailable = (
            self.token_usage is None
            and self.cost is None
            and isinstance(self.unavailable_reason, ModelMeteringUnavailableReason)
        )
        if not (available or unavailable):
            raise InvalidDomainValueError(
                "model token and cost metering must be complete or explicitly unavailable"
            )
        if available and self.unavailable_reason is not None:
            raise InvalidDomainValueError(
                "available model metering cannot have an unavailable reason"
            )


@dataclass(frozen=True, slots=True)
class ModelCallTrace:
    """Metadata-only model call trace; payload bodies have no representable field."""

    id: ModelCallId
    tenant_id: TenantId
    incident_id: IncidentId
    workflow_run_id: WorkflowRunId
    node: str
    attempt: int
    prompt: PromptVersionReference
    prompt_fingerprint: Sha256Digest
    provider: str
    model: str
    temperature_basis_points: int
    top_p_basis_points: int
    max_output_tokens: int
    seed: int | None
    input_schema_version: SemanticVersion
    output_schema_version: SemanticVersion
    request_hash: Sha256Digest
    correlation_id: CorrelationId
    causation_id: CausationId
    status: ModelCallStatus
    started_at: datetime
    completed_at: datetime | None = None
    response_hash: Sha256Digest | None = None
    metering: ModelMetering | None = None
    failure_code: str | None = None
    schema_version: str = MODEL_CALL_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        identifiers = (
            self.id,
            self.tenant_id,
            self.incident_id,
            self.workflow_run_id,
            self.correlation_id,
            self.causation_id,
        )
        if not all(hasattr(value, "value") for value in identifiers):
            raise InvalidDomainValueError("model call trace identity is invalid")
        if not isinstance(self.node, str) or _COMPONENT.fullmatch(self.node) is None:
            raise InvalidDomainValueError("model call node is invalid")
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool) or self.attempt < 1:
            raise InvalidDomainValueError("model call attempt must be positive")
        if not isinstance(self.prompt, PromptVersionReference):
            raise InvalidDomainValueError("model call Prompt reference is invalid")
        if not isinstance(self.prompt_fingerprint, Sha256Digest):
            raise InvalidDomainValueError("model call Prompt fingerprint is invalid")
        for component, field in ((self.provider, "provider"), (self.model, "model")):
            if not isinstance(component, str) or _COMPONENT.fullmatch(component) is None:
                raise InvalidDomainValueError(f"model call {field} is invalid")
        for integer_value, field in (
            (self.temperature_basis_points, "temperature"),
            (self.top_p_basis_points, "top-p"),
            (self.max_output_tokens, "output token limit"),
        ):
            if not isinstance(integer_value, int) or isinstance(integer_value, bool):
                raise InvalidDomainValueError(f"model call {field} must be an integer")
        if not 0 <= self.temperature_basis_points <= 20_000:
            raise InvalidDomainValueError("model call temperature is outside bounds")
        if not 1 <= self.top_p_basis_points <= 10_000:
            raise InvalidDomainValueError("model call top-p is outside bounds")
        if not 1 <= self.max_output_tokens <= 32_768:
            raise InvalidDomainValueError("model call output token limit is outside bounds")
        if not isinstance(self.input_schema_version, SemanticVersion) or not isinstance(
            self.output_schema_version, SemanticVersion
        ):
            raise InvalidDomainValueError("model call schema versions are invalid")
        if not isinstance(self.request_hash, Sha256Digest):
            raise InvalidDomainValueError("model call request hash is invalid")
        if not isinstance(self.status, ModelCallStatus):
            raise InvalidDomainValueError("model call status is invalid")
        object.__setattr__(self, "started_at", as_utc(self.started_at))
        if self.completed_at is not None:
            object.__setattr__(self, "completed_at", as_utc(self.completed_at))
        if self.schema_version != MODEL_CALL_TRACE_SCHEMA_VERSION:
            raise InvalidDomainValueError("model call trace schema version is unsupported")
        if self.status is ModelCallStatus.STARTED:
            if any(
                value is not None
                for value in (
                    self.completed_at,
                    self.response_hash,
                    self.metering,
                    self.failure_code,
                )
            ):
                raise InvalidDomainValueError("started model call cannot contain terminal metadata")
            return
        if self.completed_at is None or self.completed_at < self.started_at:
            raise InvalidDomainValueError("terminal model call requires ordered completion time")
        if not isinstance(self.metering, ModelMetering):
            raise InvalidDomainValueError("terminal model call requires metering metadata")
        if self.status is ModelCallStatus.SUCCEEDED:
            if self.response_hash is None or self.failure_code is not None:
                raise InvalidDomainValueError("successful model call requires only a response hash")
        elif (
            not isinstance(self.failure_code, str)
            or _COMPONENT.fullmatch(self.failure_code) is None
        ):
            raise InvalidDomainValueError("unsuccessful model call requires a bounded failure code")

    @classmethod
    def start(
        cls,
        *,
        call_id: ModelCallId,
        tenant_id: TenantId,
        incident_id: IncidentId,
        workflow_run_id: WorkflowRunId,
        node: str,
        attempt: int,
        prompt: PromptDefinition,
        request_hash: Sha256Digest,
        correlation_id: CorrelationId,
        causation_id: CausationId,
        started_at: datetime,
    ) -> ModelCallTrace:
        if not isinstance(prompt, PromptDefinition):
            raise InvalidDomainValueError("model call Prompt reference is invalid")
        if prompt.status is not PromptLifecycleStatus.ACTIVE:
            raise InvalidDomainValueError("model calls require an ACTIVE registered Prompt")
        params = prompt.model_parameters
        schemas = prompt.schema_compatibility
        return cls(
            call_id,
            tenant_id,
            incident_id,
            workflow_run_id,
            node,
            attempt,
            PromptVersionReference(prompt.prompt_id, prompt.version),
            prompt.content_fingerprint,
            params.provider,
            params.model,
            params.temperature_basis_points,
            params.top_p_basis_points,
            params.max_output_tokens,
            params.seed,
            schemas.input_version,
            schemas.output_version,
            request_hash,
            correlation_id,
            causation_id,
            ModelCallStatus.STARTED,
            started_at,
        )

    def finish(
        self,
        *,
        status: ModelCallStatus,
        completed_at: datetime,
        metering: ModelMetering,
        response_hash: Sha256Digest | None = None,
        failure_code: str | None = None,
    ) -> ModelCallTrace:
        if self.status is not ModelCallStatus.STARTED or status is ModelCallStatus.STARTED:
            raise InvalidDomainValueError("model call can only finish once with a terminal status")
        return replace(
            self,
            status=status,
            completed_at=completed_at,
            response_hash=response_hash,
            metering=metering,
            failure_code=failure_code,
        )
