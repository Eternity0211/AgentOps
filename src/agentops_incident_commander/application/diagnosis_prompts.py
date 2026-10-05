"""Fail-closed Prompt Registry authorization for every Diagnosis graph node."""

from __future__ import annotations

from typing import Protocol

from agentops_incident_commander.domain import (
    InvalidDomainValueError,
    PromptDefinition,
    PromptId,
    PromptLifecycleStatus,
    PromptPurpose,
    SemanticVersion,
    TenantId,
)
from agentops_incident_commander.workflows import DIAGNOSIS_NODE_NAMES, DiagnosisGraphState


class DiagnosisPromptStore(Protocol):
    async def resolve(
        self, tenant_id: TenantId, prompt_id: PromptId, version: SemanticVersion
    ) -> PromptDefinition | None: ...

    async def active(self, tenant_id: TenantId, prompt_id: PromptId) -> PromptDefinition | None: ...


class ApprovedDiagnosisPromptResolver:
    """Resolve the exact active Diagnosis Prompt; never accepts caller-supplied text."""

    def __init__(self, store: DiagnosisPromptStore) -> None:
        self._store = store

    async def require_approved(
        self, state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> None:
        if not isinstance(state, DiagnosisGraphState):
            raise InvalidDomainValueError("Diagnosis Prompt resolution requires graph state")
        if node_name not in DIAGNOSIS_NODE_NAMES:
            raise InvalidDomainValueError("Diagnosis Prompt node is not allowlisted")
        if (
            not isinstance(operation_id, str)
            or len(operation_id) != 64
            or any(character not in "0123456789abcdef" for character in operation_id)
        ):
            raise InvalidDomainValueError("Diagnosis Prompt operation identity is invalid")
        reference = state.prompt
        tenant_id = TenantId(state.tenant_id)
        prompt_id = PromptId(reference.prompt_id)
        version = SemanticVersion(reference.version)
        definition = await self._store.resolve(tenant_id, prompt_id, version)
        active = await self._store.active(tenant_id, prompt_id)
        if definition is None or active is None or definition != active:
            raise InvalidDomainValueError("Diagnosis Prompt version is not the active registration")
        if definition.status is not PromptLifecycleStatus.ACTIVE:
            raise InvalidDomainValueError("Diagnosis Prompt version is not active")
        if definition.purpose is not PromptPurpose.DIAGNOSIS:
            raise InvalidDomainValueError("Diagnosis Prompt purpose is not DIAGNOSIS")
        if definition.content_fingerprint.value != reference.content_fingerprint:
            raise InvalidDomainValueError("Diagnosis Prompt fingerprint does not match graph state")
