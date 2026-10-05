"""Fail-closed Diagnosis Prompt Registry authorization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from agentops_incident_commander.application import ApprovedDiagnosisPromptResolver
from agentops_incident_commander.domain import (
    ActorId,
    CausationId,
    CorrelationId,
    InvalidDomainValueError,
    PromptDefinition,
    PromptId,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptPurpose,
    PromptSchemaCompatibility,
    PromptTraceLink,
    SemanticVersion,
    TenantId,
)
from agentops_incident_commander.workflows import (
    DIAGNOSIS_NODE_NAMES,
    DiagnosisGraphState,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
)

NOW = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
PROMPT_ID = PromptId("diagnosis")
VERSION = SemanticVersion("1.0.0")
OPERATION_ID = "f" * 64


def definition(
    *,
    content: str = "Diagnose only from registered, resolvable evidence.",
    purpose: PromptPurpose = PromptPurpose.DIAGNOSIS,
    status: PromptLifecycleStatus = PromptLifecycleStatus.ACTIVE,
    version: SemanticVersion = VERSION,
) -> PromptDefinition:
    return PromptDefinition.create(
        prompt_id=PROMPT_ID,
        version=version,
        purpose=purpose,
        content=content,
        model_parameters=PromptModelParameters("mock", "model-v1", 0, 10_000, 2_048, 7),
        schema_compatibility=PromptSchemaCompatibility(VERSION, VERSION),
        trace=PromptTraceLink(
            ActorId("admin-prompts"),
            CorrelationId("correlation-prompts"),
            CausationId("create-prompt"),
            NOW,
        ),
        status=status,
    )


def state(prompt: PromptDefinition | None = None) -> DiagnosisGraphState:
    selected = prompt or definition()
    return DiagnosisGraphState(
        state_schema_version="1.3.0",
        graph_version="1.0.0",
        tenant_id="tenant-1",
        incident_id="incident-1",
        workflow_run_id="run-1",
        correlation_id="correlation-1",
        causation_id="cause-1",
        phase=GraphPhase.CONTEXT_LOADING,
        budgets=GraphBudgetState(
            max_steps=1,
            used_steps=0,
            max_replans=0,
            used_replans=0,
            max_tool_calls=1,
            used_tool_calls=0,
            max_model_calls=1,
            used_model_calls=0,
            max_tokens=10,
            used_tokens=0,
            max_cost_nanounits=10,
            used_cost_nanounits=0,
        ),
        prompt=GraphPromptReference(
            prompt_id=selected.prompt_id.value,
            version=selected.version.value,
            content_fingerprint=selected.content_fingerprint.value,
        ),
        checkpoint_sequence=0,
        updated_at=NOW,
    )


class Store:
    def __init__(
        self,
        resolved: PromptDefinition | None,
        active: PromptDefinition | None,
    ) -> None:
        self.resolved = resolved
        self.active_definition = active
        self.calls: list[tuple[str, TenantId, PromptId, SemanticVersion | None]] = []

    async def resolve(
        self, tenant_id: TenantId, prompt_id: PromptId, version: SemanticVersion
    ) -> PromptDefinition | None:
        self.calls.append(("resolve", tenant_id, prompt_id, version))
        return self.resolved

    async def active(self, tenant_id: TenantId, prompt_id: PromptId) -> PromptDefinition | None:
        self.calls.append(("active", tenant_id, prompt_id, None))
        return self.active_definition


@pytest.mark.anyio
@pytest.mark.parametrize("node_name", sorted(DIAGNOSIS_NODE_NAMES))
async def test_every_diagnosis_node_requires_exact_active_registered_prompt(
    node_name: str,
) -> None:
    approved = definition()
    store = Store(approved, approved)

    await ApprovedDiagnosisPromptResolver(store).require_approved(
        state(approved), node_name=node_name, operation_id=OPERATION_ID
    )

    assert store.calls == [
        ("resolve", TenantId("tenant-1"), PROMPT_ID, VERSION),
        ("active", TenantId("tenant-1"), PROMPT_ID, None),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("resolved", "active", "message"),
    [
        (None, definition(), "active registration"),
        (definition(), None, "active registration"),
        (
            definition(),
            definition(content="A different active registration."),
            "active registration",
        ),
    ],
)
async def test_prompt_resolution_fails_closed_when_registration_is_missing_or_not_active(
    resolved: PromptDefinition | None,
    active: PromptDefinition | None,
    message: str,
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        await ApprovedDiagnosisPromptResolver(Store(resolved, active)).require_approved(
            state(), node_name="plan", operation_id=OPERATION_ID
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status",
    [
        PromptLifecycleStatus.DRAFT,
        PromptLifecycleStatus.EVALUATED,
        PromptLifecycleStatus.RETIRED,
    ],
)
async def test_non_active_prompt_lifecycle_status_is_rejected(
    status: PromptLifecycleStatus,
) -> None:
    candidate = definition(status=status)
    with pytest.raises(InvalidDomainValueError, match="not active"):
        await ApprovedDiagnosisPromptResolver(Store(candidate, candidate)).require_approved(
            state(candidate), node_name="hypothesis", operation_id=OPERATION_ID
        )


@pytest.mark.anyio
async def test_wrong_purpose_and_fingerprint_are_rejected() -> None:
    wrong_purpose = definition(purpose=PromptPurpose.REMEDIATION)
    with pytest.raises(InvalidDomainValueError, match="purpose"):
        await ApprovedDiagnosisPromptResolver(Store(wrong_purpose, wrong_purpose)).require_approved(
            state(wrong_purpose), node_name="evidence_gate", operation_id=OPERATION_ID
        )

    approved = definition()
    mismatched_state = state(approved).model_copy(
        update={
            "prompt": state(approved).prompt.model_copy(update={"content_fingerprint": "0" * 64})
        }
    )
    with pytest.raises(InvalidDomainValueError, match="fingerprint"):
        await ApprovedDiagnosisPromptResolver(Store(approved, approved)).require_approved(
            mismatched_state, node_name="plan", operation_id=OPERATION_ID
        )


@pytest.mark.anyio
@pytest.mark.parametrize("operation_id", ["", "F" * 64, "g" * 64, 1])
async def test_invalid_state_node_and_operation_identity_are_rejected(operation_id: Any) -> None:
    approved = definition()
    resolver = ApprovedDiagnosisPromptResolver(Store(approved, approved))
    with pytest.raises(InvalidDomainValueError, match="operation identity"):
        await resolver.require_approved(
            state(approved), node_name="plan", operation_id=cast(str, operation_id)
        )

    with pytest.raises(InvalidDomainValueError, match="graph state"):
        await resolver.require_approved(
            cast(DiagnosisGraphState, {}), node_name="plan", operation_id=OPERATION_ID
        )
    with pytest.raises(InvalidDomainValueError, match="not allowlisted"):
        await resolver.require_approved(
            state(approved), node_name="arbitrary_shell", operation_id=OPERATION_ID
        )
