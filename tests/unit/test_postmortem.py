"""Constrained postmortem drafting cannot invent facts or Evidence references."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from agentops_incident_commander.application import (
    ConstrainedPostmortemGenerator,
    ModelCallTraceManager,
    PostmortemGenerationRequest,
    PostmortemModelFact,
    PostmortemModelRequest,
    PostmortemModelResult,
)
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Artifact,
    ArtifactId,
    AuditEvent,
    AuthenticationError,
    AuthorizationError,
    CausationId,
    ConfirmedPostmortemFact,
    CorrelationId,
    Evidence,
    EvidenceId,
    EvidenceLineage,
    EvidenceQuality,
    EvidenceSourceType,
    Incident,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    ModelCallId,
    ModelCallStatus,
    ModelCallTrace,
    ModelCost,
    ModelCostSource,
    ModelMetering,
    ModelTokenUsage,
    NormalizedQuery,
    PostmortemDraft,
    PostmortemDraftSection,
    PostmortemFactId,
    PostmortemFactKind,
    Principal,
    PromptDefinition,
    PromptId,
    PromptInjectionStatus,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptPurpose,
    PromptSchemaCompatibility,
    PromptTraceLink,
    PromptVersionReference,
    QueryParameter,
    RedactionStatus,
    RetentionClass,
    Role,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure import (
    DeterministicPostmortemMockModel,
    PostmortemMockScenario,
)
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage
from agentops_incident_commander.workflows import (
    POSTMORTEM_OUTLINE_SCHEMA_VERSION,
    PostmortemOutline,
    PostmortemOutlineSection,
)

NOW = datetime(2026, 10, 9, 8, tzinfo=UTC)
TENANT = TenantId("tenant-1")
INCIDENT_ID = IncidentId("incident-1")
_UNSET = object()


def principal(*, tenant: TenantId = TENANT) -> Principal:
    return Principal(ActorId("postmortem-worker"), tenant, frozenset({Role.VIEWER}))


def closed_incident(**changes: Any) -> Incident:
    values: dict[str, object] = {
        "id": INCIDENT_ID,
        "tenant_id": TENANT,
        "severity": IncidentSeverity.SEV2,
        "opened_at": NOW,
        "updated_at": NOW + timedelta(hours=1),
        "state": IncidentState.CLOSED,
        "version": AggregateVersion(5),
        "closed_at": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return Incident(**values)  # type: ignore[arg-type]


def active_prompt(**changes: Any) -> PromptDefinition:
    values: dict[str, object] = {
        "prompt_id": PromptId("postmortem-draft"),
        "version": SemanticVersion("1.0.0"),
        "purpose": PromptPurpose.POSTMORTEM,
        "content": "Arrange every confirmed fact exactly once; never create facts.",
        "model_parameters": PromptModelParameters(
            "mock", "postmortem-mock-v1", 0, 10_000, 2_048, 9
        ),
        "schema_compatibility": PromptSchemaCompatibility(
            SemanticVersion("1.0.0"), SemanticVersion("1.0.0")
        ),
        "trace": PromptTraceLink(
            ActorId("admin"), CorrelationId("prompt-create"), CausationId("prompt-source"), NOW
        ),
        "status": PromptLifecycleStatus.ACTIVE,
    }
    values.update(changes)
    return PromptDefinition.create(**values)  # type: ignore[arg-type]


def confirmed_fact(
    suffix: str = "impact",
    *,
    kind: PostmortemFactKind = PostmortemFactKind.IMPACT,
    evidence_id: str | None = None,
    **changes: Any,
) -> ConfirmedPostmortemFact:
    values: dict[str, object] = {
        "id": PostmortemFactId(f"fact-{suffix}"),
        "tenant_id": TENANT,
        "incident_id": INCIDENT_ID,
        "kind": kind,
        "statement": f"Confirmed {suffix} fact.",
        "evidence_ids": (EvidenceId(evidence_id or f"evidence-{suffix}"),),
        "confirmed_by": ActorId("incident-commander"),
        "confirmed_at": NOW + timedelta(minutes=50),
    }
    values.update(changes)
    return ConfirmedPostmortemFact(**values)  # type: ignore[arg-type]


def evidence_bundle(suffix: str, **changes: Any) -> tuple[Evidence, Artifact, bytes]:
    content = f'{{"fact":"{suffix}"}}'.encode()
    digest = Sha256Digest(hashlib.sha256(content).hexdigest())
    artifact_id = ArtifactId(f"artifact-{suffix}")
    artifact = Artifact(
        artifact_id,
        TENANT,
        INCIDENT_ID,
        LocalArtifactStorage.locator(artifact_id),
        "application/json",
        "1.0.0",
        digest,
        len(content),
        RetentionClass.INCIDENT,
        NOW + timedelta(minutes=20),
        NOW + timedelta(days=30),
        RedactionStatus.NOT_REQUIRED,
        False,
    )
    values: dict[str, object] = {
        "id": EvidenceId(f"evidence-{suffix}"),
        "tenant_id": TENANT,
        "incident_id": INCIDENT_ID,
        "source_type": EvidenceSourceType.LOG,
        "source_instance": "loki-primary",
        "tool_name": "query_logs",
        "tool_version": "1.0.0",
        "tool_schema_version": "1.0.0",
        "normalized_query": NormalizedQuery((QueryParameter("service", "order"),)),
        "observed_from": NOW + timedelta(minutes=10),
        "observed_to": NOW + timedelta(minutes=15),
        "collected_at": NOW + timedelta(minutes=20),
        "artifact_id": artifact_id,
        "content_hash": digest,
        "parser_version": "1.0.0",
        "normalizer_version": "1.0.0",
        "quality": EvidenceQuality(10_000, ("source-available",)),
        "lineage": EvidenceLineage(ToolCallId(f"tool-{suffix}"), WorkflowRunId("workflow-1"), None),
        "trust": TrustClassification.DIRECT_OBSERVATION,
        "prompt_injection_status": PromptInjectionStatus.NONE,
        "expires_at": NOW + timedelta(days=29),
    }
    values.update(changes)
    return Evidence(**values), artifact, content  # type: ignore[arg-type]


class IncidentStore:
    def __init__(self, incident: Incident | None) -> None:
        self.incident = incident

    async def get(self, tenant_id: TenantId, incident_id: IncidentId) -> Incident | None:
        assert tenant_id == TENANT and incident_id == INCIDENT_ID
        return self.incident


class FactStore:
    def __init__(self, facts: tuple[ConfirmedPostmortemFact, ...]) -> None:
        self.facts = facts

    async def list_confirmed(
        self, tenant_id: TenantId, incident_id: IncidentId
    ) -> tuple[ConfirmedPostmortemFact, ...]:
        assert tenant_id == TENANT and incident_id == INCIDENT_ID
        return self.facts


class EvidenceStore:
    def __init__(self, evidence: tuple[Evidence, ...]) -> None:
        self.by_id = {item.id: item for item in evidence}

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None:
        assert tenant_id == TENANT and incident_id == INCIDENT_ID
        return self.by_id.get(evidence_id)


class SubstitutingEvidenceStore:
    def __init__(self, evidence: Evidence) -> None:
        self.evidence = evidence

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None:
        return self.evidence


class PromptStore:
    def __init__(
        self,
        resolved: PromptDefinition | None,
        active: PromptDefinition | None = None,
    ) -> None:
        self.resolved = resolved
        self.active_prompt = resolved if active is None else active

    async def resolve(
        self, tenant_id: TenantId, prompt_id: PromptId, version: SemanticVersion
    ) -> PromptDefinition | None:
        assert tenant_id == TENANT
        return self.resolved

    async def active(self, tenant_id: TenantId, prompt_id: PromptId) -> PromptDefinition | None:
        assert tenant_id == TENANT
        return self.active_prompt


class TraceStore:
    def __init__(self) -> None:
        self.trace: ModelCallTrace | None = None
        self.audit: list[AuditEvent] = []

    async def start(self, trace: ModelCallTrace, audit_event: AuditEvent) -> None:
        self.trace = trace
        self.audit.append(audit_event)

    async def finish(
        self, expected: ModelCallTrace, completed: ModelCallTrace, audit_event: AuditEvent
    ) -> None:
        assert self.trace == expected
        self.trace = completed
        self.audit.append(audit_event)


def generation_request(**changes: Any) -> PostmortemGenerationRequest:
    values: dict[str, object] = {
        "tenant_id": TENANT,
        "incident_id": INCIDENT_ID,
        "workflow_run_id": WorkflowRunId("postmortem-workflow-1"),
        "prompt_id": PromptId("postmortem-draft"),
        "prompt_version": SemanticVersion("1.0.0"),
        "attempt": 1,
        "correlation_id": CorrelationId("postmortem-correlation"),
        "causation_id": CausationId("incident-closed"),
    }
    values.update(changes)
    return PostmortemGenerationRequest(**values)  # type: ignore[arg-type]


def generator(
    tmp_path: Path,
    *,
    incident: Incident | object | None = _UNSET,
    facts: tuple[ConfirmedPostmortemFact, ...] | None = None,
    evidence: tuple[Evidence, ...] | None = None,
    prompt: PromptDefinition | object | None = _UNSET,
    active: PromptDefinition | None = None,
    model: Any = None,
    at: datetime = NOW + timedelta(hours=2),
    timeout_seconds: int = 30,
) -> tuple[ConstrainedPostmortemGenerator, TraceStore, LocalArtifactStorage]:
    selected_facts = (
        facts
        if facts is not None
        else (
            confirmed_fact(),
            confirmed_fact("root", kind=PostmortemFactKind.ROOT_CAUSE),
        )
    )
    selected_evidence = evidence
    if selected_evidence is None:
        bundles = tuple(
            evidence_bundle(item.id.value.removeprefix("fact-")) for item in selected_facts
        )
        selected_evidence = tuple(item[0] for item in bundles)
    else:
        bundles = ()
    storage = LocalArtifactStorage(tmp_path / "postmortem-artifacts")
    for item in bundles:
        storage.store(item[1], item[2])
    traces = TraceStore()
    moments = count(1)
    trace_manager = ModelCallTraceManager(
        traces,
        clock=lambda: at + timedelta(seconds=next(moments)),
        id_factory=lambda: f"postmortem-trace-{next(moments)}",
    )
    selected_prompt = active_prompt() if prompt is _UNSET else cast(PromptDefinition | None, prompt)
    selected_incident = closed_incident() if incident is _UNSET else cast(Incident | None, incident)
    service = ConstrainedPostmortemGenerator(
        IncidentStore(selected_incident),
        FactStore(selected_facts),
        EvidenceStore(selected_evidence),
        storage,
        PromptStore(selected_prompt, active),
        model or DeterministicPostmortemMockModel(),
        trace_manager,
        clock=lambda: at,
        timeout_seconds=timeout_seconds,
    )
    return service, traces, storage


@pytest.mark.anyio
async def test_generator_uses_only_exact_confirmed_facts_and_resolvable_evidence(
    tmp_path: Path,
) -> None:
    service, traces, _ = generator(tmp_path)
    draft = await service.generate(generation_request(), principal=principal())

    assert draft.fact_ids == (PostmortemFactId("fact-impact"), PostmortemFactId("fact-root"))
    assert draft.evidence_ids == (EvidenceId("evidence-impact"), EvidenceId("evidence-root"))
    assert draft.prompt == PromptVersionReference(
        PromptId("postmortem-draft"), SemanticVersion("1.0.0")
    )
    assert draft.model_call_id == traces.trace.id if traces.trace else False
    assert traces.trace is not None and traces.trace.status is ModelCallStatus.SUCCEEDED
    assert [item.type for item in traces.audit] == ["model.call_started", "model.call_finished"]
    rendered = draft.render_markdown()
    assert "Confirmed impact fact. [Evidence: evidence-impact]" in rendered
    assert "Confirmed root fact. [Evidence: evidence-root]" in rendered
    assert "postmortem-workflow-1" not in rendered
    assert len(draft.fingerprint.value) == 64


@pytest.mark.parametrize(
    "scenario",
    (
        PostmortemMockScenario.FABRICATED_REFERENCE,
        PostmortemMockScenario.OMITTED_FACT,
        PostmortemMockScenario.WRONG_SECTION,
        PostmortemMockScenario.MALFORMED,
    ),
)
@pytest.mark.anyio
async def test_false_fact_reference_omission_wrong_section_and_malformed_output_fail_closed(
    tmp_path: Path, scenario: PostmortemMockScenario
) -> None:
    service, traces, _ = generator(tmp_path, model=DeterministicPostmortemMockModel(scenario))
    with pytest.raises(InvalidDomainValueError):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is not None and traces.trace.status is ModelCallStatus.FAILED


@pytest.mark.parametrize(
    ("scenario", "status", "error"),
    (
        (PostmortemMockScenario.TIMEOUT, ModelCallStatus.TIMED_OUT, TimeoutError),
        (PostmortemMockScenario.REFUSAL, ModelCallStatus.REFUSED, InvalidDomainValueError),
    ),
)
@pytest.mark.anyio
async def test_timeout_and_refusal_are_traced_with_distinct_terminal_status(
    tmp_path: Path,
    scenario: PostmortemMockScenario,
    status: ModelCallStatus,
    error: type[Exception],
) -> None:
    service, traces, _ = generator(tmp_path, model=DeterministicPostmortemMockModel(scenario))
    with pytest.raises(error):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is not None and traces.trace.status is status
    assert traces.trace.metering is not None
    assert traces.trace.metering.unavailable_reason is not None


@pytest.mark.parametrize(
    ("principal_value", "error"),
    (
        (None, AuthenticationError),
        (principal(tenant=TenantId("tenant-2")), AuthorizationError),
    ),
)
@pytest.mark.anyio
async def test_generation_requires_authenticated_same_tenant_read_access(
    tmp_path: Path, principal_value: Principal | None, error: type[Exception]
) -> None:
    service, traces, _ = generator(tmp_path)
    with pytest.raises(error):
        await service.generate(generation_request(), principal=principal_value)
    assert traces.trace is None


@pytest.mark.parametrize(
    ("incident", "at", "message"),
    (
        (None, NOW + timedelta(hours=2), "unavailable"),
        (
            closed_incident(
                state=IncidentState.RESOLVED,
                closed_at=None,
            ),
            NOW + timedelta(hours=2),
            "CLOSED",
        ),
        (closed_incident(), NOW + timedelta(minutes=59), "predate"),
    ),
)
@pytest.mark.anyio
async def test_generation_requires_closed_incident_and_monotonic_time(
    tmp_path: Path, incident: Incident | None, at: datetime, message: str
) -> None:
    service, traces, _ = generator(tmp_path, incident=incident, at=at)
    with pytest.raises(InvalidDomainValueError, match=message):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is None


@pytest.mark.parametrize(
    ("prompt", "active", "message"),
    (
        (None, None, "active registration"),
        (
            active_prompt(),
            active_prompt(content="Different active content."),
            "active registration",
        ),
        (
            active_prompt(status=PromptLifecycleStatus.EVALUATED),
            None,
            "active registration|not active",
        ),
        (active_prompt(purpose=PromptPurpose.DIAGNOSIS), None, "POSTMORTEM"),
        (
            active_prompt(
                schema_compatibility=PromptSchemaCompatibility(
                    SemanticVersion("2.0.0"), SemanticVersion("1.0.0")
                )
            ),
            None,
            "schema compatibility",
        ),
        (
            active_prompt(
                schema_compatibility=PromptSchemaCompatibility(
                    SemanticVersion("1.0.0"),
                    SemanticVersion("1.0.0"),
                    SemanticVersion("1.0.0"),
                )
            ),
            None,
            "schema compatibility",
        ),
    ),
)
@pytest.mark.anyio
async def test_generation_requires_exact_active_postmortem_prompt(
    tmp_path: Path,
    prompt: PromptDefinition | None,
    active: PromptDefinition | None,
    message: str,
) -> None:
    service, traces, _ = generator(tmp_path, prompt=prompt, active=active)
    with pytest.raises(InvalidDomainValueError, match=message):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is None


@pytest.mark.parametrize(
    ("facts", "message"),
    (
        ((), "unique and bounded"),
        ((cast(ConfirmedPostmortemFact, object()),), "unique and bounded"),
        ((confirmed_fact(), confirmed_fact()), "unique and bounded"),
        (
            (
                confirmed_fact(
                    tenant_id=TenantId("tenant-2"),
                ),
            ),
            "scope",
        ),
        (
            (
                confirmed_fact(
                    confirmed_at=NOW + timedelta(hours=3),
                ),
            ),
            "future",
        ),
    ),
)
@pytest.mark.anyio
async def test_generation_rejects_invalid_confirmed_fact_sets(
    tmp_path: Path,
    facts: tuple[ConfirmedPostmortemFact, ...],
    message: str,
) -> None:
    service, traces, _ = generator(tmp_path, facts=facts, evidence=())
    with pytest.raises(InvalidDomainValueError, match=message):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is None


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"trust": TrustClassification.HISTORICAL_REFERENCE}, "current-Incident"),
        ({"prompt_injection_status": PromptInjectionStatus.QUARANTINED}, "prompt-injection"),
        ({"collected_at": NOW + timedelta(minutes=55)}, "predate"),
        ({"expires_at": NOW + timedelta(minutes=59)}, "expired"),
    ),
)
@pytest.mark.anyio
async def test_generation_rejects_untrusted_injected_future_or_expired_evidence(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    fact = confirmed_fact()
    evidence, artifact, content = evidence_bundle("impact", **changes)
    storage = LocalArtifactStorage(tmp_path / "postmortem-artifacts")
    storage.store(artifact, content)
    traces = TraceStore()
    ids = count(1)
    service = ConstrainedPostmortemGenerator(
        IncidentStore(closed_incident()),
        FactStore((fact,)),
        EvidenceStore((evidence,)),
        storage,
        PromptStore(active_prompt()),
        DeterministicPostmortemMockModel(),
        ModelCallTraceManager(
            traces,
            clock=lambda: NOW + timedelta(hours=2, seconds=next(ids)),
            id_factory=lambda: f"trace-{next(ids)}",
        ),
        clock=lambda: NOW + timedelta(hours=2),
    )
    with pytest.raises(Exception, match=message):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is None


@pytest.mark.anyio
async def test_generation_rejects_missing_and_tampered_evidence(tmp_path: Path) -> None:
    fact = confirmed_fact()
    service, traces, _ = generator(tmp_path, facts=(fact,), evidence=())
    with pytest.raises(InvalidDomainValueError, match="unresolved"):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is None


@pytest.mark.parametrize(
    "substitution",
    (
        replace(evidence_bundle("impact")[0], id=EvidenceId("evidence-substituted")),
        replace(evidence_bundle("impact")[0], tenant_id=TenantId("tenant-2")),
        replace(evidence_bundle("impact")[0], incident_id=IncidentId("incident-2")),
    ),
)
@pytest.mark.anyio
async def test_generation_rejects_evidence_scope_substitution(
    tmp_path: Path, substitution: Evidence
) -> None:
    fact = confirmed_fact()
    traces = TraceStore()
    ids = count(1)
    service = ConstrainedPostmortemGenerator(
        IncidentStore(closed_incident()),
        FactStore((fact,)),
        SubstitutingEvidenceStore(substitution),
        LocalArtifactStorage(tmp_path / "scope-artifacts"),
        PromptStore(active_prompt()),
        DeterministicPostmortemMockModel(),
        ModelCallTraceManager(
            traces,
            clock=lambda: NOW + timedelta(hours=2, seconds=next(ids)),
            id_factory=lambda: f"scope-{next(ids)}",
        ),
        clock=lambda: NOW + timedelta(hours=2),
    )
    with pytest.raises(InvalidDomainValueError, match="scope"):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is None


@pytest.mark.anyio
async def test_generation_rejects_tampered_evidence_artifact(tmp_path: Path) -> None:
    fact = confirmed_fact()
    evidence, artifact, content = evidence_bundle("impact")
    storage = LocalArtifactStorage(tmp_path / "tampered-artifacts")
    storage.store(artifact, content)
    blob = next((tmp_path / "tampered-artifacts" / "blobs").rglob(artifact.content_hash.value))
    blob.write_bytes(b"tampered")
    traces = TraceStore()
    ids = count(1)
    service = ConstrainedPostmortemGenerator(
        IncidentStore(closed_incident()),
        FactStore((fact,)),
        EvidenceStore((evidence,)),
        storage,
        PromptStore(active_prompt()),
        DeterministicPostmortemMockModel(),
        ModelCallTraceManager(
            traces,
            clock=lambda: NOW + timedelta(hours=2, seconds=next(ids)),
            id_factory=lambda: f"tampered-{next(ids)}",
        ),
        clock=lambda: NOW + timedelta(hours=2),
    )
    with pytest.raises(Exception, match="integrity"):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is None


class UntypedModel:
    async def draft(self, request: PostmortemModelRequest, prompt: PromptDefinition) -> object:
        return object()


class WrongIncidentModel:
    async def draft(
        self, request: PostmortemModelRequest, prompt: PromptDefinition
    ) -> PostmortemModelResult:
        outline = PostmortemOutline(
            schema_version=POSTMORTEM_OUTLINE_SCHEMA_VERSION,
            incident_id="incident-other",
            sections=(
                PostmortemOutlineSection(
                    kind=PostmortemFactKind.IMPACT,
                    fact_ids=(request.facts[0].fact_id.value,),
                ),
                PostmortemOutlineSection(
                    kind=PostmortemFactKind.ROOT_CAUSE,
                    fact_ids=(request.facts[1].fact_id.value,),
                ),
            ),
        )
        encoded = outline.model_dump_json().encode()
        return PostmortemModelResult(
            outline,
            ModelMetering(
                ModelTokenUsage(1, 1, 0, 0, 2),
                ModelCost(
                    0,
                    "USD",
                    ModelCostSource.RATE_CARD_CALCULATED,
                    SemanticVersion("1.0.0"),
                ),
            ),
            Sha256Digest(hashlib.sha256(encoded).hexdigest()),
        )


@pytest.mark.parametrize("model", (UntypedModel(), WrongIncidentModel()))
@pytest.mark.anyio
async def test_untyped_or_cross_incident_model_results_fail_closed(
    tmp_path: Path, model: object
) -> None:
    service, traces, _ = generator(tmp_path, model=model)
    with pytest.raises(InvalidDomainValueError):
        await service.generate(generation_request(), principal=principal())
    assert traces.trace is not None and traces.trace.status is ModelCallStatus.FAILED


def test_postmortem_contracts_are_immutable_hash_bound_and_exactly_rendered() -> None:
    fact = confirmed_fact(statement="  Confirmed customer impact.  ")
    assert fact.statement == "Confirmed customer impact."
    section = PostmortemDraftSection(PostmortemFactKind.IMPACT, (fact,))
    draft = PostmortemDraft(
        TENANT,
        INCIDENT_ID,
        PromptVersionReference(PromptId("postmortem-draft"), SemanticVersion("1.0.0")),
        Sha256Digest("a" * 64),
        ModelCallId("model-call-1"),
        (section,),
        NOW + timedelta(hours=2),
    )
    assert draft.fact_ids == (fact.id,)
    assert draft.evidence_ids == fact.evidence_ids
    assert draft.render_markdown().endswith("[Evidence: evidence-impact]\n")
    assert len(fact.fingerprint.value) == len(draft.fingerprint.value) == 64


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"kind": cast(PostmortemFactKind, "BAD")}, "kind"),
        ({"statement": ""}, "statement"),
        ({"statement": "bad\nline"}, "statement"),
        ({"statement": "x" * 513}, "statement"),
        ({"evidence_ids": ()}, "Evidence references"),
        ({"evidence_ids": (EvidenceId("e"), EvidenceId("e"))}, "Evidence references"),
        ({"confirmed_by": cast(ActorId, object())}, "confirmer"),
        ({"schema_version": "2.0.0"}, "schema version"),
    ),
)
def test_confirmed_fact_rejects_invalid_content(changes: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        confirmed_fact(**cast(Any, changes))


def test_sections_and_drafts_reject_substitution_and_duplicates() -> None:
    impact = confirmed_fact()
    root = confirmed_fact("root", kind=PostmortemFactKind.ROOT_CAUSE)
    with pytest.raises(InvalidDomainValueError, match="kind"):
        PostmortemDraftSection(cast(PostmortemFactKind, "BAD"), (impact,))
    for facts in ((), (impact, root), (impact, impact), (cast(ConfirmedPostmortemFact, object()),)):
        with pytest.raises(InvalidDomainValueError, match="section facts"):
            PostmortemDraftSection(PostmortemFactKind.IMPACT, facts)

    with pytest.raises(InvalidDomainValueError, match="sections"):
        PostmortemDraft(
            TENANT,
            INCIDENT_ID,
            PromptVersionReference(PromptId("p"), SemanticVersion("1.0.0")),
            Sha256Digest("a" * 64),
            ModelCallId("call"),
            (),
            NOW,
        )


def test_outline_schema_rejects_extra_duplicate_and_unbounded_references() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        PostmortemOutline.model_validate(
            {
                "schema_version": "1.0.0",
                "incident_id": "incident-1",
                "sections": [{"kind": "IMPACT", "fact_ids": ["f1"]}],
                "narrative": "invented",
            }
        )
    with pytest.raises(ValidationError, match="unique"):
        PostmortemOutline(
            schema_version="1.0.0",
            incident_id="incident-1",
            sections=(
                PostmortemOutlineSection(kind=PostmortemFactKind.IMPACT, fact_ids=("f1",)),
                PostmortemOutlineSection(kind=PostmortemFactKind.IMPACT, fact_ids=("f2",)),
            ),
        )
    with pytest.raises(ValidationError, match="unique"):
        PostmortemOutlineSection(kind=PostmortemFactKind.IMPACT, fact_ids=("f1", "f1"))
    with pytest.raises(ValidationError):
        PostmortemOutlineSection(
            kind=PostmortemFactKind.IMPACT,
            fact_ids=tuple(f"f{i}" for i in range(65)),
        )


def test_request_and_generator_reject_invalid_attempt_and_timeout(tmp_path: Path) -> None:
    with pytest.raises(InvalidDomainValueError, match="attempt"):
        generation_request(attempt=0)
    for timeout in (0, 301, True):
        with pytest.raises(InvalidDomainValueError, match="timeout"):
            generator(tmp_path / str(timeout), timeout_seconds=timeout)


def model_fact(**changes: Any) -> PostmortemModelFact:
    values: dict[str, object] = {
        "fact_id": PostmortemFactId("fact-impact"),
        "kind": PostmortemFactKind.IMPACT.value,
        "statement": "Confirmed impact.",
        "evidence_ids": (EvidenceId("evidence-impact"),),
        "fingerprint": Sha256Digest("a" * 64),
    }
    values.update(changes)
    return PostmortemModelFact(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    (
        {"fact_id": cast(PostmortemFactId, object())},
        {"kind": ""},
        {"kind": cast(str, object())},
        {"statement": ""},
        {"statement": cast(str, object())},
        {"evidence_ids": ()},
        {"evidence_ids": cast(tuple[EvidenceId, ...], object())},
        {"evidence_ids": (cast(EvidenceId, object()),)},
        {"fingerprint": cast(Sha256Digest, object())},
    ),
)
def test_model_fact_rejects_invalid_typed_content(changes: dict[str, object]) -> None:
    with pytest.raises(InvalidDomainValueError, match="model fact"):
        model_fact(**cast(Any, changes))


@pytest.mark.parametrize(
    ("facts", "schema_version", "message"),
    (
        ((), "1.0.0", "unique and bounded"),
        ((cast(PostmortemModelFact, object()),), "1.0.0", "unique and bounded"),
        ((model_fact(), model_fact()), "1.0.0", "unique and bounded"),
        ((model_fact(),), "2.0.0", "schema version"),
    ),
)
def test_model_request_rejects_invalid_fact_sets_and_schema(
    facts: tuple[PostmortemModelFact, ...], schema_version: str, message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        PostmortemModelRequest(INCIDENT_ID, facts, schema_version)
    with pytest.raises(InvalidDomainValueError, match="Incident identity"):
        PostmortemModelRequest(cast(IncidentId, object()), (model_fact(),))


def test_model_result_rejects_untyped_output_and_metadata() -> None:
    outline = PostmortemOutline(
        schema_version="1.0.0",
        incident_id=INCIDENT_ID.value,
        sections=(
            PostmortemOutlineSection(kind=PostmortemFactKind.IMPACT, fact_ids=("fact-impact",)),
        ),
    )
    metering = ModelMetering(
        ModelTokenUsage(1, 1, 0, 0, 2),
        ModelCost(
            0,
            "USD",
            ModelCostSource.RATE_CARD_CALCULATED,
            SemanticVersion("1.0.0"),
        ),
    )
    with pytest.raises(InvalidDomainValueError, match="typed outline"):
        PostmortemModelResult(cast(PostmortemOutline, object()), metering, Sha256Digest("a" * 64))
    for invalid_metering, invalid_hash in (
        (cast(ModelMetering, object()), Sha256Digest("a" * 64)),
        (metering, cast(Sha256Digest, object())),
    ):
        with pytest.raises(InvalidDomainValueError, match="metadata"):
            PostmortemModelResult(outline, invalid_metering, invalid_hash)


@pytest.mark.anyio
async def test_generator_and_mock_reject_untyped_calls(tmp_path: Path) -> None:
    service, traces, _ = generator(tmp_path)
    with pytest.raises(InvalidDomainValueError, match="typed request"):
        await service.generate(cast(PostmortemGenerationRequest, object()), principal=principal())
    assert traces.trace is None

    model = DeterministicPostmortemMockModel()
    with pytest.raises(InvalidDomainValueError, match="typed inputs"):
        await model.draft(cast(PostmortemModelRequest, object()), active_prompt())
    with pytest.raises(InvalidDomainValueError, match="typed inputs"):
        await model.draft(PostmortemModelRequest(INCIDENT_ID, (model_fact(),)), cast(Any, object()))
    with pytest.raises(InvalidDomainValueError, match="scenario"):
        DeterministicPostmortemMockModel(cast(PostmortemMockScenario, "BAD"))


@pytest.mark.anyio
async def test_mock_omits_one_of_multiple_same_kind_facts(tmp_path: Path) -> None:
    facts = (confirmed_fact("impact-a"), confirmed_fact("impact-b"))
    bundles = (evidence_bundle("impact-a"), evidence_bundle("impact-b"))
    storage = LocalArtifactStorage(tmp_path / "postmortem-artifacts")
    for _, artifact, content in bundles:
        storage.store(artifact, content)
    traces = TraceStore()
    ids = count(1)
    service = ConstrainedPostmortemGenerator(
        IncidentStore(closed_incident()),
        FactStore(facts),
        EvidenceStore(tuple(item[0] for item in bundles)),
        storage,
        PromptStore(active_prompt()),
        DeterministicPostmortemMockModel(PostmortemMockScenario.OMITTED_FACT),
        ModelCallTraceManager(
            traces,
            clock=lambda: NOW + timedelta(hours=2, seconds=next(ids)),
            id_factory=lambda: f"omit-{next(ids)}",
        ),
        clock=lambda: NOW + timedelta(hours=2),
    )
    with pytest.raises(InvalidDomainValueError, match="every confirmed fact"):
        await service.generate(generation_request(), principal=principal())


def test_outline_rejects_globally_duplicate_fact_reference() -> None:
    with pytest.raises(ValidationError, match="globally unique"):
        PostmortemOutline(
            schema_version="1.0.0",
            incident_id=INCIDENT_ID.value,
            sections=(
                PostmortemOutlineSection(kind=PostmortemFactKind.IMPACT, fact_ids=("fact-shared",)),
                PostmortemOutlineSection(
                    kind=PostmortemFactKind.ROOT_CAUSE, fact_ids=("fact-shared",)
                ),
            ),
        )


def test_domain_draft_rejects_invalid_bindings_global_duplicates_scope_and_schema() -> None:
    impact = confirmed_fact()
    section = PostmortemDraftSection(PostmortemFactKind.IMPACT, (impact,))
    base = {
        "tenant_id": TENANT,
        "incident_id": INCIDENT_ID,
        "prompt": PromptVersionReference(PromptId("p"), SemanticVersion("1.0.0")),
        "prompt_fingerprint": Sha256Digest("a" * 64),
        "model_call_id": ModelCallId("call"),
        "sections": (section,),
        "generated_at": NOW,
    }
    cases = (
        ({"tenant_id": cast(TenantId, object())}, "scope"),
        ({"prompt": cast(PromptVersionReference, object())}, "Prompt binding"),
        ({"prompt_fingerprint": cast(Sha256Digest, object())}, "Prompt binding"),
        ({"model_call_id": cast(ModelCallId, object())}, "model call"),
        ({"sections": (section, section)}, "sections"),
        ({"schema_version": "2.0.0"}, "schema version"),
    )
    for changes, message in cases:
        with pytest.raises(InvalidDomainValueError, match=message):
            PostmortemDraft(**{**base, **changes})  # type: ignore[arg-type]

    root = confirmed_fact("root", kind=PostmortemFactKind.ROOT_CAUSE)
    root_section = PostmortemDraftSection(PostmortemFactKind.ROOT_CAUSE, (root,))
    object.__setattr__(root_section, "facts", (impact,))
    with pytest.raises(InvalidDomainValueError, match="globally unique"):
        PostmortemDraft(**{**base, "sections": (section, root_section)})  # type: ignore[arg-type]

    other = confirmed_fact(tenant_id=TenantId("tenant-2"))
    other_section = PostmortemDraftSection(PostmortemFactKind.IMPACT, (other,))
    with pytest.raises(InvalidDomainValueError, match="share"):
        PostmortemDraft(**{**base, "sections": (other_section,)})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    (
        {"id": cast(PostmortemFactId, object())},
        {"tenant_id": cast(TenantId, object())},
        {"incident_id": cast(IncidentId, object())},
        {"statement": cast(str, object())},
        {"evidence_ids": tuple(EvidenceId(f"e{i}") for i in range(17))},
        {"evidence_ids": (cast(EvidenceId, object()),)},
    ),
)
def test_confirmed_fact_rejects_invalid_identity_and_reference_types(
    changes: dict[str, object],
) -> None:
    with pytest.raises(InvalidDomainValueError):
        confirmed_fact(**cast(Any, changes))


@pytest.mark.parametrize(
    "changes",
    (
        {"tenant_id": cast(TenantId, object())},
        {"incident_id": cast(IncidentId, object())},
        {"workflow_run_id": cast(WorkflowRunId, object())},
        {"prompt_id": cast(PromptId, object())},
        {"prompt_version": cast(SemanticVersion, object())},
        {"correlation_id": cast(CorrelationId, object())},
        {"causation_id": cast(CausationId, object())},
    ),
)
def test_generation_request_rejects_invalid_identity_types(changes: dict[str, object]) -> None:
    with pytest.raises(InvalidDomainValueError, match="identity"):
        generation_request(**cast(Any, changes))
