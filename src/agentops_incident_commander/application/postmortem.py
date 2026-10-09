"""Constrained postmortem generation from confirmed, resolvable facts only."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    MAX_POSTMORTEM_FACTS,
    ArtifactStorage,
    CausationId,
    ConfirmedPostmortemFact,
    CorrelationId,
    Evidence,
    EvidenceId,
    EvidenceValidationStatus,
    Incident,
    IncidentId,
    IncidentState,
    InvalidDomainValueError,
    ModelCallStatus,
    ModelMetering,
    ModelMeteringUnavailableReason,
    Permission,
    PostmortemDraft,
    PostmortemDraftSection,
    PostmortemFactId,
    Principal,
    PromptDefinition,
    PromptId,
    PromptInjectionStatus,
    PromptLifecycleStatus,
    PromptPurpose,
    PromptVersionReference,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    TrustClassification,
    WorkflowRunId,
    as_utc,
    require_permission,
    resolve_and_validate_evidence,
)
from agentops_incident_commander.workflows import (
    POSTMORTEM_OUTLINE_SCHEMA_VERSION,
    PostmortemOutline,
)

from .model_tracing import ModelCallTraceManager

POSTMORTEM_MODEL_INPUT_SCHEMA_VERSION = "1.0.0"
POSTMORTEM_NODE_NAME = "postmortem.draft"


class PostmortemIncidentReader(Protocol):
    async def get(self, tenant_id: TenantId, incident_id: IncidentId) -> Incident | None: ...


class PostmortemFactReader(Protocol):
    async def list_confirmed(
        self, tenant_id: TenantId, incident_id: IncidentId
    ) -> tuple[ConfirmedPostmortemFact, ...]: ...


class PostmortemEvidenceReader(Protocol):
    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None: ...


class PostmortemPromptReader(Protocol):
    async def resolve(
        self, tenant_id: TenantId, prompt_id: PromptId, version: SemanticVersion
    ) -> PromptDefinition | None: ...

    async def active(self, tenant_id: TenantId, prompt_id: PromptId) -> PromptDefinition | None: ...


@dataclass(frozen=True, slots=True)
class PostmortemGenerationRequest:
    tenant_id: TenantId
    incident_id: IncidentId
    workflow_run_id: WorkflowRunId
    prompt_id: PromptId
    prompt_version: SemanticVersion
    attempt: int
    correlation_id: CorrelationId
    causation_id: CausationId

    def __post_init__(self) -> None:
        identities = (
            self.tenant_id,
            self.incident_id,
            self.workflow_run_id,
            self.prompt_id,
            self.prompt_version,
            self.correlation_id,
            self.causation_id,
        )
        expected = (
            TenantId,
            IncidentId,
            WorkflowRunId,
            PromptId,
            SemanticVersion,
            CorrelationId,
            CausationId,
        )
        if any(
            not isinstance(value, kind) for value, kind in zip(identities, expected, strict=True)
        ):
            raise InvalidDomainValueError("postmortem generation identity is invalid")
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool) or self.attempt < 1:
            raise InvalidDomainValueError("postmortem generation attempt must be positive")


@dataclass(frozen=True, slots=True)
class PostmortemModelFact:
    fact_id: PostmortemFactId
    kind: str
    statement: str
    evidence_ids: tuple[EvidenceId, ...]
    fingerprint: Sha256Digest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fact_id, PostmortemFactId)
            or not isinstance(self.kind, str)
            or not self.kind
            or not isinstance(self.statement, str)
            or not self.statement
            or not isinstance(self.evidence_ids, tuple)
            or not self.evidence_ids
            or any(not isinstance(item, EvidenceId) for item in self.evidence_ids)
            or not isinstance(self.fingerprint, Sha256Digest)
        ):
            raise InvalidDomainValueError("postmortem model fact is invalid")


@dataclass(frozen=True, slots=True)
class PostmortemModelRequest:
    incident_id: IncidentId
    facts: tuple[PostmortemModelFact, ...]
    schema_version: str = POSTMORTEM_MODEL_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.incident_id, IncidentId):
            raise InvalidDomainValueError("postmortem model Incident identity is invalid")
        if (
            not isinstance(self.facts, tuple)
            or not self.facts
            or len(self.facts) > MAX_POSTMORTEM_FACTS
            or any(not isinstance(item, PostmortemModelFact) for item in self.facts)
            or len({item.fact_id for item in self.facts}) != len(self.facts)
        ):
            raise InvalidDomainValueError("postmortem model facts must be unique and bounded")
        if self.schema_version != POSTMORTEM_MODEL_INPUT_SCHEMA_VERSION:
            raise InvalidDomainValueError("postmortem model input schema version is unsupported")

    @property
    def fingerprint(self) -> Sha256Digest:
        payload = {
            "facts": [
                {
                    "evidence_ids": [item.value for item in fact.evidence_ids],
                    "fact_fingerprint": fact.fingerprint.value,
                    "fact_id": fact.fact_id.value,
                    "kind": fact.kind,
                    "statement": fact.statement,
                }
                for fact in self.facts
            ],
            "incident_id": self.incident_id.value,
            "schema_version": self.schema_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(encoded).hexdigest())


@dataclass(frozen=True, slots=True)
class PostmortemModelResult:
    outline: PostmortemOutline
    metering: ModelMetering
    response_hash: Sha256Digest

    def __post_init__(self) -> None:
        if not isinstance(self.outline, PostmortemOutline):
            raise InvalidDomainValueError("postmortem model result must contain a typed outline")
        if not isinstance(self.metering, ModelMetering) or not isinstance(
            self.response_hash, Sha256Digest
        ):
            raise InvalidDomainValueError("postmortem model result metadata is invalid")


class PostmortemModel(Protocol):
    async def draft(
        self, request: PostmortemModelRequest, prompt: PromptDefinition
    ) -> PostmortemModelResult: ...


class PostmortemModelRefusal(InvalidDomainValueError):
    """Typed provider refusal that remains distinct in model-call telemetry."""


class ConstrainedPostmortemGenerator:
    """Authorize, resolve, trace, and deterministically assemble a postmortem draft."""

    def __init__(
        self,
        incidents: PostmortemIncidentReader,
        facts: PostmortemFactReader,
        evidence: PostmortemEvidenceReader,
        artifacts: ArtifactStorage,
        prompts: PostmortemPromptReader,
        model: PostmortemModel,
        traces: ModelCallTraceManager,
        *,
        clock: Callable[[], datetime],
        timeout_seconds: int = 30,
    ) -> None:
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or not 1 <= timeout_seconds <= 300
        ):
            raise InvalidDomainValueError("postmortem model timeout must be 1-300 seconds")
        self._incidents = incidents
        self._facts = facts
        self._evidence = evidence
        self._artifacts = artifacts
        self._prompts = prompts
        self._model = model
        self._traces = traces
        self._clock = clock
        self._timeout_seconds = timeout_seconds

    async def generate(
        self, request: PostmortemGenerationRequest, *, principal: Principal | None
    ) -> PostmortemDraft:
        if not isinstance(request, PostmortemGenerationRequest):
            raise InvalidDomainValueError("postmortem generation requires a typed request")
        actor = require_permission(principal, Permission.INCIDENT_READ, tenant_id=request.tenant_id)
        require_permission(actor, Permission.EVIDENCE_READ, tenant_id=request.tenant_id)
        incident = await self._incidents.get(request.tenant_id, request.incident_id)
        if incident is None or incident.tenant_id != request.tenant_id:
            raise InvalidDomainValueError("postmortem Incident is unavailable")
        if incident.state is not IncidentState.CLOSED or incident.closed_at is None:
            raise InvalidDomainValueError("postmortem generation requires a CLOSED Incident")
        generated_at = as_utc(self._clock())
        if generated_at < incident.closed_at:
            raise InvalidDomainValueError("postmortem generation cannot predate Incident closure")

        prompt = await self._require_prompt(request)
        confirmed = await self._facts.list_confirmed(request.tenant_id, request.incident_id)
        await self._validate_facts(confirmed, request, principal=actor, at=generated_at)
        model_request = PostmortemModelRequest(
            request.incident_id,
            tuple(
                PostmortemModelFact(
                    fact.id,
                    fact.kind.value,
                    fact.statement,
                    fact.evidence_ids,
                    fact.fingerprint,
                )
                for fact in confirmed
            ),
        )
        started = await self._traces.start(
            tenant_id=request.tenant_id,
            incident_id=request.incident_id,
            workflow_run_id=request.workflow_run_id,
            node=POSTMORTEM_NODE_NAME,
            attempt=request.attempt,
            prompt=prompt,
            request_hash=model_request.fingerprint,
            actor_id=actor.actor_id,
            correlation_id=request.correlation_id,
            causation_id=request.causation_id,
        )
        unavailable = ModelMetering(
            None, None, ModelMeteringUnavailableReason.CALL_FAILED_BEFORE_METERING
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._model.draft(model_request, prompt)
            if not isinstance(result, PostmortemModelResult):
                raise InvalidDomainValueError("postmortem provider returned an untyped result")
            sections = self._assemble(result.outline, confirmed, request.incident_id)
        except PostmortemModelRefusal:
            await self._traces.finish(
                started,
                status=ModelCallStatus.REFUSED,
                metering=unavailable,
                actor_id=actor.actor_id,
                failure_code="postmortem_model_refused",
            )
            raise
        except TimeoutError:
            await self._traces.finish(
                started,
                status=ModelCallStatus.TIMED_OUT,
                metering=unavailable,
                actor_id=actor.actor_id,
                failure_code="postmortem_model_timeout",
            )
            raise
        except Exception:
            await self._traces.finish(
                started,
                status=ModelCallStatus.FAILED,
                metering=unavailable,
                actor_id=actor.actor_id,
                failure_code="postmortem_output_invalid",
            )
            raise
        completed = await self._traces.finish(
            started,
            status=ModelCallStatus.SUCCEEDED,
            metering=result.metering,
            actor_id=actor.actor_id,
            response_hash=result.response_hash,
        )
        return PostmortemDraft(
            request.tenant_id,
            request.incident_id,
            PromptVersionReference(prompt.prompt_id, prompt.version),
            prompt.content_fingerprint,
            completed.id,
            sections,
            generated_at,
        )

    async def _require_prompt(self, request: PostmortemGenerationRequest) -> PromptDefinition:
        prompt = await self._prompts.resolve(
            request.tenant_id, request.prompt_id, request.prompt_version
        )
        active = await self._prompts.active(request.tenant_id, request.prompt_id)
        expected_schema = SemanticVersion(POSTMORTEM_OUTLINE_SCHEMA_VERSION)
        if prompt is None or active is None or prompt != active:
            raise InvalidDomainValueError(
                "postmortem Prompt version is not the active registration"
            )
        if prompt.status is not PromptLifecycleStatus.ACTIVE:
            raise InvalidDomainValueError("postmortem Prompt version is not active")
        if prompt.purpose is not PromptPurpose.POSTMORTEM:
            raise InvalidDomainValueError("postmortem Prompt purpose is not POSTMORTEM")
        compatibility = prompt.schema_compatibility
        if (
            compatibility.input_version != SemanticVersion(POSTMORTEM_MODEL_INPUT_SCHEMA_VERSION)
            or compatibility.output_version != expected_schema
            or compatibility.memory_context_version is not None
        ):
            raise InvalidDomainValueError("postmortem Prompt schema compatibility is invalid")
        return prompt

    async def _validate_facts(
        self,
        facts: tuple[ConfirmedPostmortemFact, ...],
        request: PostmortemGenerationRequest,
        *,
        principal: Principal,
        at: datetime,
    ) -> None:
        if (
            not isinstance(facts, tuple)
            or not facts
            or len(facts) > MAX_POSTMORTEM_FACTS
            or any(not isinstance(item, ConfirmedPostmortemFact) for item in facts)
            or len({item.id for item in facts}) != len(facts)
        ):
            raise InvalidDomainValueError("confirmed postmortem facts must be unique and bounded")
        for fact in facts:
            if fact.tenant_id != request.tenant_id or fact.incident_id != request.incident_id:
                raise InvalidDomainValueError("postmortem fact scope does not match the request")
            if fact.confirmed_at > at:
                raise InvalidDomainValueError("postmortem fact confirmation is in the future")
            for evidence_id in fact.evidence_ids:
                evidence = await self._evidence.get(
                    evidence_id,
                    tenant_id=request.tenant_id,
                    incident_id=request.incident_id,
                )
                if evidence is None:
                    raise InvalidDomainValueError("postmortem Evidence reference is unresolved")
                if (
                    evidence.id != evidence_id
                    or evidence.tenant_id != request.tenant_id
                    or evidence.incident_id != request.incident_id
                ):
                    raise InvalidDomainValueError("postmortem Evidence scope does not match")
                if evidence.trust not in {
                    TrustClassification.DIRECT_OBSERVATION,
                    TrustClassification.DERIVED_OBSERVATION,
                }:
                    raise InvalidDomainValueError(
                        "postmortem facts require current-Incident observation Evidence"
                    )
                if evidence.prompt_injection_status is not PromptInjectionStatus.NONE:
                    raise InvalidDomainValueError(
                        "postmortem facts cannot use prompt-injection Evidence"
                    )
                if evidence.collected_at > fact.confirmed_at:
                    raise InvalidDomainValueError(
                        "postmortem fact cannot predate its supporting Evidence"
                    )
                validation = resolve_and_validate_evidence(
                    evidence, self._artifacts, principal=principal, at=at
                )
                if validation.status is not EvidenceValidationStatus.VALID:
                    raise InvalidDomainValueError("postmortem Evidence reference is expired")

    @staticmethod
    def _assemble(
        outline: PostmortemOutline,
        facts: tuple[ConfirmedPostmortemFact, ...],
        incident_id: IncidentId,
    ) -> tuple[PostmortemDraftSection, ...]:
        if outline.incident_id != incident_id.value:
            raise InvalidDomainValueError("postmortem outline Incident does not match")
        by_id = {fact.id.value: fact for fact in facts}
        referenced = tuple(fact_id for section in outline.sections for fact_id in section.fact_ids)
        if set(referenced) != set(by_id) or len(referenced) != len(by_id):
            raise InvalidDomainValueError(
                "postmortem outline must reference every confirmed fact exactly once"
            )
        sections: list[PostmortemDraftSection] = []
        for section in outline.sections:
            section_facts = tuple(by_id[fact_id] for fact_id in section.fact_ids)
            if any(fact.kind is not section.kind for fact in section_facts):
                raise InvalidDomainValueError(
                    "postmortem outline moved a fact to the wrong section"
                )
            sections.append(PostmortemDraftSection(section.kind, section_facts))
        return tuple(sections)
