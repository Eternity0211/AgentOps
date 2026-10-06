"""Prompt draft, regression evaluation, promotion, and rollback orchestration tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    PromptLifecycleChange,
    PromptLifecycleManager,
)
from agentops_incident_commander.domain import (
    ActorId,
    AuditEvent,
    AuthenticationError,
    AuthorizationError,
    CausationId,
    CorrelationId,
    InvalidDomainValueError,
    Permission,
    Principal,
    PromptDefinition,
    PromptId,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptPurpose,
    PromptRegressionContext,
    PromptRegressionEvaluation,
    PromptRegressionFixtureResult,
    PromptSchemaCompatibility,
    PromptTraceLink,
    PromptVersionReference,
    Role,
    SemanticVersion,
    TenantId,
)

NOW = datetime(2026, 10, 4, 22, 0, tzinfo=UTC)
TENANT = TenantId("tenant-prompts")
PROMPT_ID = PromptId("diagnosis-root-cause")
V1 = SemanticVersion("1.0.0")
V2 = SemanticVersion("1.1.0")
V3 = SemanticVersion("1.2.0")


def prompt(
    version: SemanticVersion,
    content: str,
    *,
    predecessor: PromptVersionReference | None = None,
    status: PromptLifecycleStatus = PromptLifecycleStatus.DRAFT,
    memory_context_version: SemanticVersion | None = None,
) -> PromptDefinition:
    return PromptDefinition.create(
        prompt_id=PROMPT_ID,
        version=version,
        purpose=PromptPurpose.DIAGNOSIS,
        content=content,
        model_parameters=PromptModelParameters("mock", "model-v1", 0, 10_000, 2_048, 7),
        schema_compatibility=PromptSchemaCompatibility(V1, V1, memory_context_version),
        trace=PromptTraceLink(
            ActorId("admin-prompts"),
            CorrelationId("correlation-prompts"),
            CausationId(f"create-{version.value}"),
            NOW,
        ),
        status=status,
        rollback_predecessor=predecessor,
    )


def evaluation(version: SemanticVersion, *, passed: bool = True) -> PromptRegressionEvaluation:
    return PromptRegressionEvaluation(
        PromptVersionReference(PROMPT_ID, version),
        SemanticVersion("1.0.0"),
        (
            PromptRegressionFixtureResult("valid-output", passed),
            PromptRegressionFixtureResult("no-fabricated-evidence", passed),
        ),
        NOW,
    )


def memory_evaluation(
    version: SemanticVersion,
    *,
    include_with_memory: bool = True,
    fabricated_references: int = 0,
) -> PromptRegressionEvaluation:
    results = [
        PromptRegressionFixtureResult(
            "historical-context",
            True,
            PromptRegressionContext.WITHOUT_MEMORY,
        )
    ]
    if include_with_memory:
        results.append(
            PromptRegressionFixtureResult(
                "historical-context",
                True,
                PromptRegressionContext.WITH_MEMORY,
                fabricated_references=fabricated_references,
            )
        )
    return PromptRegressionEvaluation(
        PromptVersionReference(PROMPT_ID, version),
        SemanticVersion("1.1.0"),
        tuple(results),
        NOW,
    )


class Store:
    def __init__(self) -> None:
        self.values: dict[tuple[TenantId, PromptId, SemanticVersion], PromptDefinition] = {}
        self.audits: list[AuditEvent] = []

    async def resolve(
        self, tenant_id: TenantId, prompt_id: PromptId, version: SemanticVersion
    ) -> PromptDefinition | None:
        return self.values.get((tenant_id, prompt_id, version))

    async def active(self, tenant_id: TenantId, prompt_id: PromptId) -> PromptDefinition | None:
        matches = [
            value
            for (owner, family, _), value in self.values.items()
            if owner == tenant_id
            and family == prompt_id
            and value.status is PromptLifecycleStatus.ACTIVE
        ]
        assert len(matches) <= 1
        return matches[0] if matches else None

    async def apply(self, change: PromptLifecycleChange, audit_event: AuditEvent) -> None:
        for before in change.before:
            key = (audit_event.tenant_id, before.prompt_id, before.version)
            if self.values.get(key) != before:
                raise InvalidDomainValueError("stale Prompt lifecycle state")
        for after in change.after:
            key = (audit_event.tenant_id, after.prompt_id, after.version)
            if not change.before and key in self.values:
                raise InvalidDomainValueError("duplicate Prompt version")
            self.values[key] = after
        self.audits.append(audit_event)


def admin() -> Principal:
    return Principal(ActorId("admin-prompts"), TENANT, frozenset({Role.ADMIN}))


def manager(store: Store) -> PromptLifecycleManager:
    ids = iter(f"audit-prompt-{index}" for index in range(20))
    return PromptLifecycleManager(store, clock=lambda: NOW, id_factory=lambda: next(ids))


@pytest.mark.anyio
async def test_complete_prompt_lifecycle_is_rbac_gated_regression_gated_and_audited() -> None:
    store = Store()
    service = manager(store)
    correlation = CorrelationId("correlation-lifecycle")
    cause = CausationId("command-lifecycle")
    first = prompt(V1, "Diagnose only from resolvable evidence.")
    assert (
        await service.draft(
            first, principal=admin(), correlation_id=correlation, causation_id=cause
        )
        == first
    )
    evaluated_first = await service.evaluate(
        evaluation(V1), principal=admin(), correlation_id=correlation, causation_id=cause
    )
    assert evaluated_first.status is PromptLifecycleStatus.EVALUATED
    active_first = await service.promote(
        PromptVersionReference(PROMPT_ID, V1),
        principal=admin(),
        correlation_id=correlation,
        causation_id=cause,
    )
    assert active_first.status is PromptLifecycleStatus.ACTIVE

    second = prompt(V2, "Diagnose with explicit supporting and counter evidence.")
    await service.draft(second, principal=admin(), correlation_id=correlation, causation_id=cause)
    await service.evaluate(
        evaluation(V2), principal=admin(), correlation_id=correlation, causation_id=cause
    )
    active_second = await service.promote(
        PromptVersionReference(PROMPT_ID, V2),
        principal=admin(),
        correlation_id=correlation,
        causation_id=cause,
    )
    assert active_second.status is PromptLifecycleStatus.ACTIVE
    assert store.values[(TENANT, PROMPT_ID, V1)].status is PromptLifecycleStatus.RETIRED

    with pytest.raises(InvalidDomainValueError, match="newer copy"):
        await service.rollback(
            PromptVersionReference(PROMPT_ID, V1),
            prompt(
                V3,
                "Not a copy of the retired Prompt.",
                predecessor=PromptVersionReference(PROMPT_ID, V2),
            ),
            principal=admin(),
            correlation_id=correlation,
            causation_id=cause,
        )
    replacement = prompt(
        V3,
        first.content,
        predecessor=PromptVersionReference(PROMPT_ID, V2),
    )
    rolled_back = await service.rollback(
        PromptVersionReference(PROMPT_ID, V1),
        replacement,
        principal=admin(),
        correlation_id=correlation,
        causation_id=cause,
    )
    assert rolled_back.status is PromptLifecycleStatus.ACTIVE
    assert rolled_back.content_fingerprint == first.content_fingerprint
    assert store.values[(TENANT, PROMPT_ID, V2)].status is PromptLifecycleStatus.RETIRED
    assert [event.type for event in store.audits] == [
        "prompt.drafted",
        "prompt.evaluated",
        "prompt.promoted",
        "prompt.drafted",
        "prompt.evaluated",
        "prompt.promoted",
        "prompt.rolled_back",
    ]
    assert all(event.request_hash and event.result_hash for event in store.audits)
    assert all(event.actor_id == admin().actor_id for event in store.audits)


@pytest.mark.anyio
async def test_lifecycle_refuses_unauthorized_failed_and_illegal_transitions() -> None:
    store = Store()
    service = manager(store)
    correlation = CorrelationId("correlation-refusal")
    cause = CausationId("command-refusal")
    first = prompt(V1, "Diagnose safely.")
    with pytest.raises(AuthenticationError):
        await service.draft(first, principal=None, correlation_id=correlation, causation_id=cause)
    with pytest.raises(AuthorizationError):
        await service.draft(
            first,
            principal=Principal(ActorId("viewer"), TENANT, frozenset({Role.VIEWER})),
            correlation_id=correlation,
            causation_id=cause,
        )
    with pytest.raises(InvalidDomainValueError, match="begin as DRAFT"):
        await service.draft(
            replace(first, status=PromptLifecycleStatus.ACTIVE),
            principal=admin(),
            correlation_id=correlation,
            causation_id=cause,
        )
    await service.draft(first, principal=admin(), correlation_id=correlation, causation_id=cause)
    with pytest.raises(InvalidDomainValueError, match="did not pass"):
        await service.evaluate(
            evaluation(V1, passed=False),
            principal=admin(),
            correlation_id=correlation,
            causation_id=cause,
        )
    with pytest.raises(InvalidDomainValueError, match="EVALUATED"):
        await service.promote(
            PromptVersionReference(PROMPT_ID, V1),
            principal=admin(),
            correlation_id=correlation,
            causation_id=cause,
        )
    await service.evaluate(
        evaluation(V1), principal=admin(), correlation_id=correlation, causation_id=cause
    )
    with pytest.raises(InvalidDomainValueError, match="only DRAFT"):
        await service.evaluate(
            evaluation(V1), principal=admin(), correlation_id=correlation, causation_id=cause
        )
    await service.promote(
        PromptVersionReference(PROMPT_ID, V1),
        principal=admin(),
        correlation_id=correlation,
        causation_id=cause,
    )
    with pytest.raises(InvalidDomainValueError, match="active and a retired"):
        await service.rollback(
            PromptVersionReference(PROMPT_ID, V1),
            prompt(V2, first.content, predecessor=PromptVersionReference(PROMPT_ID, V1)),
            principal=admin(),
            correlation_id=correlation,
            causation_id=cause,
        )
    with pytest.raises(InvalidDomainValueError, match="not registered"):
        await service.evaluate(
            evaluation(V2), principal=admin(), correlation_id=correlation, causation_id=cause
        )
    assert len(store.audits) == 3
    assert Permission.ADMIN_MANAGE in admin().permissions


@pytest.mark.anyio
async def test_memory_aware_prompt_requires_complete_safe_paired_regression() -> None:
    store = Store()
    service = manager(store)
    correlation = CorrelationId("correlation-memory-prompt")
    cause = CausationId("command-memory-prompt")
    candidate = prompt(
        V1,
        "Use historical context only as a reference.",
        memory_context_version=SemanticVersion("1.0.0"),
    )
    await service.draft(
        candidate,
        principal=admin(),
        correlation_id=correlation,
        causation_id=cause,
    )

    with pytest.raises(InvalidDomainValueError, match="paired memory regression"):
        await service.evaluate(
            memory_evaluation(V1, include_with_memory=False),
            principal=admin(),
            correlation_id=correlation,
            causation_id=cause,
        )
    with pytest.raises(InvalidDomainValueError, match="paired memory regression"):
        await service.evaluate(
            memory_evaluation(V1, fabricated_references=1),
            principal=admin(),
            correlation_id=correlation,
            causation_id=cause,
        )

    evaluated = await service.evaluate(
        memory_evaluation(V1),
        principal=admin(),
        correlation_id=correlation,
        causation_id=cause,
    )
    assert evaluated.status is PromptLifecycleStatus.EVALUATED
    promoted = await service.promote(
        PromptVersionReference(PROMPT_ID, V1),
        principal=admin(),
        correlation_id=correlation,
        causation_id=cause,
    )
    assert promoted.status is PromptLifecycleStatus.ACTIVE


def test_regression_evaluation_requires_unique_bounded_typed_results() -> None:
    reference = PromptVersionReference(PROMPT_ID, V1)
    valid = PromptRegressionFixtureResult("fixture-1", True)
    assert PromptRegressionEvaluation(reference, V1, (valid,), NOW).passed
    assert not PromptRegressionEvaluation(
        reference, V1, (PromptRegressionFixtureResult("fixture-1", False),), NOW
    ).passed
    for fixture_id, passed in (("bad fixture", True), ("fixture", 1)):
        with pytest.raises(InvalidDomainValueError, match="fixture"):
            PromptRegressionFixtureResult(fixture_id, passed)  # type: ignore[arg-type]
    for results in ((), (valid, valid), tuple(valid for _ in range(129)), ("bad",)):
        with pytest.raises(InvalidDomainValueError, match="unique and bounded"):
            PromptRegressionEvaluation(reference, V1, results, NOW)  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="identity"):
        PromptRegressionEvaluation(reference, "1.0.0", (valid,), NOW)  # type: ignore[arg-type]


def test_memory_regression_results_are_typed_safe_and_paired_by_fixture() -> None:
    reference = PromptVersionReference(PROMPT_ID, V1)
    without = PromptRegressionFixtureResult(
        "fixture-1", True, PromptRegressionContext.WITHOUT_MEMORY
    )
    with_memory = PromptRegressionFixtureResult(
        "fixture-1", True, PromptRegressionContext.WITH_MEMORY
    )
    paired = PromptRegressionEvaluation(reference, V1, (without, with_memory), NOW)
    assert paired.passed
    assert paired.memory_comparison_passed
    assert not PromptRegressionEvaluation(reference, V1, (without,), NOW).memory_comparison_passed

    unsafe_values: tuple[dict[str, object], ...] = (
        {"unsupported_conclusions": 1},
        {"fabricated_references": 1},
        {"authorization_violations": 1},
        {"ground_truth_visible": True},
        {"passed": False},
    )
    for overrides in unsafe_values:
        unsafe = replace(with_memory, **cast(Any, overrides))
        result = PromptRegressionEvaluation(reference, V1, (without, unsafe), NOW)
        assert not unsafe.safe
        assert not result.passed
        assert not result.memory_comparison_passed

    invalid_values: tuple[dict[str, object], ...] = (
        {"context": "WITH_MEMORY"},
        {"unsupported_conclusions": -1},
        {"fabricated_references": True},
        {"authorization_violations": 10_001},
        {"ground_truth_visible": 1},
    )
    for overrides in invalid_values:
        with pytest.raises(InvalidDomainValueError, match="Prompt regression"):
            replace(with_memory, **cast(Any, overrides))

    duplicate = (without, replace(without, passed=False))
    with pytest.raises(InvalidDomainValueError, match="unique and bounded"):
        PromptRegressionEvaluation(reference, V1, duplicate, NOW)
