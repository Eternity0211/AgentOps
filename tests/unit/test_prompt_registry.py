"""Immutable Prompt Registry domain contract tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import pytest

from agentops_incident_commander.domain import (
    MAX_PROMPT_CONTENT_BYTES,
    MAX_PROMPT_OUTPUT_TOKENS,
    MAX_PROMPT_SEED,
    MAX_PROMPT_TEMPERATURE_BASIS_POINTS,
    MIN_PROMPT_SEED,
    PROMPT_DEFINITION_SCHEMA_VERSION,
    ActorId,
    CausationId,
    CorrelationId,
    InvalidDomainValueError,
    PromptDefinition,
    PromptId,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptNotFoundError,
    PromptPurpose,
    PromptRegistry,
    PromptSchemaCompatibility,
    PromptTraceLink,
    PromptVersionReference,
    SemanticVersion,
    Sha256Digest,
)

NOW = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)
PROMPT_ID = PromptId("diagnosis-root-cause")
V1 = SemanticVersion("1.0.0")
V2 = SemanticVersion("1.1.0")
CONTENT = "You diagnose incidents using only resolvable Evidence IDs."


def parameters(**overrides: Any) -> PromptModelParameters:
    values: dict[str, Any] = {
        "provider": "mock",
        "model": "deterministic-v1",
        "temperature_basis_points": 0,
        "top_p_basis_points": 10_000,
        "max_output_tokens": 2_048,
        "seed": 7,
    }
    values.update(overrides)
    return PromptModelParameters(**values)


def trace(**overrides: Any) -> PromptTraceLink:
    values: dict[str, Any] = {
        "actor_id": ActorId("admin-prompt"),
        "correlation_id": CorrelationId("correlation-prompt"),
        "causation_id": CausationId("command-prompt"),
        "created_at": NOW,
    }
    values.update(overrides)
    return PromptTraceLink(**values)


def definition(
    version: SemanticVersion = V1,
    *,
    status: PromptLifecycleStatus = PromptLifecycleStatus.DRAFT,
    purpose: PromptPurpose = PromptPurpose.DIAGNOSIS,
    predecessor: PromptVersionReference | None = None,
) -> PromptDefinition:
    return PromptDefinition.create(
        prompt_id=PROMPT_ID,
        version=version,
        purpose=purpose,
        content=CONTENT,
        model_parameters=parameters(),
        schema_compatibility=PromptSchemaCompatibility(V1, V1),
        trace=trace(),
        status=status,
        rollback_predecessor=predecessor,
    )


def test_prompt_definition_is_versioned_fingerprinted_and_traceable() -> None:
    value = definition()
    assert value.schema_version == PROMPT_DEFINITION_SCHEMA_VERSION
    assert value.identity == (PROMPT_ID, V1)
    assert value.content_fingerprint == Sha256Digest(
        hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
    )
    assert value.model_parameters.max_output_tokens == 2_048
    assert value.schema_compatibility.input_version == V1
    shifted = trace(created_at=NOW.astimezone(timezone(timedelta(hours=8))))
    assert shifted.created_at == NOW


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"provider": ""}, "provider"),
        ({"provider": cast(str, 1)}, "provider"),
        ({"model": "bad model"}, "model"),
        ({"temperature_basis_points": True}, "must be an integer"),
        ({"top_p_basis_points": 1.5}, "must be an integer"),
        ({"max_output_tokens": "2048"}, "must be an integer"),
        ({"temperature_basis_points": -1}, "temperature"),
        ({"temperature_basis_points": MAX_PROMPT_TEMPERATURE_BASIS_POINTS + 1}, "temperature"),
        ({"top_p_basis_points": 0}, "top-p"),
        ({"top_p_basis_points": 10_001}, "top-p"),
        ({"max_output_tokens": 0}, "output token"),
        ({"max_output_tokens": MAX_PROMPT_OUTPUT_TOKENS + 1}, "output token"),
        ({"seed": True}, "seed"),
        ({"seed": MIN_PROMPT_SEED - 1}, "seed"),
        ({"seed": MAX_PROMPT_SEED + 1}, "seed"),
    ],
)
def test_model_parameters_reject_ambiguous_or_unbounded_values(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        parameters(**overrides)
    assert parameters(seed=None).seed is None


def test_schema_compatibility_and_trace_require_typed_reproducibility_links() -> None:
    for input_version, output_version in (("1.0.0", V1), (V1, "1.0.0")):
        with pytest.raises(InvalidDomainValueError, match="must be semantic"):
            PromptSchemaCompatibility(cast(Any, input_version), cast(Any, output_version))
    with pytest.raises(InvalidDomainValueError, match="actor"):
        trace(actor_id=cast(ActorId, "admin"))
    with pytest.raises(InvalidDomainValueError, match="correlation"):
        trace(correlation_id=cast(CorrelationId, "correlation"))
    with pytest.raises(InvalidDomainValueError, match="correlation"):
        trace(causation_id=cast(CausationId, "causation"))


@pytest.mark.parametrize("content", ["", "  ", "bad\x00prompt", "windows\r\nline"])
def test_prompt_content_must_be_bounded_normalized_and_hash_bound(content: str) -> None:
    digest = Sha256Digest(hashlib.sha256(content.encode()).hexdigest())
    with pytest.raises(InvalidDomainValueError, match="normalized text"):
        replace(definition(), content=content, content_fingerprint=digest)
    with pytest.raises(InvalidDomainValueError, match="byte limit"):
        replace(
            definition(),
            content="x" * (MAX_PROMPT_CONTENT_BYTES + 1),
            content_fingerprint=Sha256Digest(
                hashlib.sha256(("x" * (MAX_PROMPT_CONTENT_BYTES + 1)).encode()).hexdigest()
            ),
        )
    with pytest.raises(InvalidDomainValueError, match="does not match"):
        replace(definition(), content_fingerprint=Sha256Digest("0" * 64))


def test_prompt_definition_rejects_invalid_typed_metadata_and_predecessors() -> None:
    base = definition(V2)
    invalid_values = (
        ({"prompt_id": cast(PromptId, "prompt")}, "identity"),
        ({"version": cast(SemanticVersion, "1.1.0")}, "identity"),
        ({"purpose": cast(PromptPurpose, "AGENT")}, "purpose"),
        ({"model_parameters": cast(PromptModelParameters, object())}, "model parameters"),
        (
            {"schema_compatibility": cast(PromptSchemaCompatibility, object())},
            "schema compatibility",
        ),
        ({"trace": cast(PromptTraceLink, object())}, "trace link"),
        ({"status": cast(PromptLifecycleStatus, "ENABLED")}, "lifecycle"),
        ({"schema_version": "2.0.0"}, "schema version"),
        ({"rollback_predecessor": cast(PromptVersionReference, "bad")}, "earlier version"),
        (
            {"rollback_predecessor": PromptVersionReference(PromptId("another-prompt"), V1)},
            "earlier version",
        ),
        (
            {"rollback_predecessor": PromptVersionReference(PROMPT_ID, V2)},
            "earlier version",
        ),
    )
    for overrides, message in invalid_values:
        with pytest.raises(InvalidDomainValueError, match=message):
            replace(base, **overrides)
    for prompt_id, version in (("prompt", V1), (PROMPT_ID, "1.0.0")):
        with pytest.raises(InvalidDomainValueError, match="reference"):
            PromptVersionReference(cast(Any, prompt_id), cast(Any, version))


def test_registry_resolves_exact_and_single_active_versions_in_stable_order() -> None:
    first = definition(V1, status=PromptLifecycleStatus.RETIRED)
    second = definition(
        V2,
        status=PromptLifecycleStatus.ACTIVE,
        predecessor=PromptVersionReference(PROMPT_ID, V1),
    )
    postmortem = PromptDefinition.create(
        prompt_id=PromptId("postmortem-draft"),
        version=V1,
        purpose=PromptPurpose.POSTMORTEM,
        content="Draft only from confirmed facts.",
        model_parameters=parameters(),
        schema_compatibility=PromptSchemaCompatibility(V1, V1),
        trace=trace(),
        status=PromptLifecycleStatus.DRAFT,
    )
    registry = PromptRegistry((second, postmortem, first))
    assert registry.resolve(PROMPT_ID, V1) == first
    assert registry.active(PROMPT_ID) == second
    assert registry.catalog() == (first, second, postmortem)
    assert registry.catalog(purpose=PromptPurpose.POSTMORTEM) == (postmortem,)
    with pytest.raises(PromptNotFoundError, match="not registered"):
        registry.resolve(PROMPT_ID, SemanticVersion("9.0.0"))
    with pytest.raises(PromptNotFoundError, match="no active"):
        registry.active(postmortem.prompt_id)


def test_registry_rejects_duplicates_family_drift_and_broken_rollback_links() -> None:
    first = definition(V1)
    active = definition(V1, status=PromptLifecycleStatus.ACTIVE)
    cases: tuple[tuple[Any, ...] | list[PromptDefinition], ...] = (
        (),
        [first],
        (cast(PromptDefinition, "bad"),),
        (first, first),
        (first, definition(V2, purpose=PromptPurpose.REMEDIATION)),
        (active, definition(V2, status=PromptLifecycleStatus.ACTIVE)),
        (
            first,
            definition(
                V2,
                predecessor=PromptVersionReference(PROMPT_ID, SemanticVersion("0.9.0")),
            ),
        ),
    )
    messages = (
        "at least one",
        "at least one",
        "entries",
        "duplicate",
        "purpose",
        "multiple active",
        "must resolve",
    )
    for values, message in zip(cases, messages, strict=True):
        with pytest.raises(InvalidDomainValueError, match=message):
            PromptRegistry(cast(Any, values))
