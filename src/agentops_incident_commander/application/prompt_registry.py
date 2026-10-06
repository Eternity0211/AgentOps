"""RBAC-protected Prompt lifecycle orchestration with hash-bound audit."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Permission,
    Principal,
    PromptDefinition,
    PromptId,
    PromptLifecycleStatus,
    PromptRegressionEvaluation,
    PromptVersionReference,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    as_utc,
    require_permission,
)


@dataclass(frozen=True, slots=True)
class PromptLifecycleChange:
    action: str
    before: tuple[PromptDefinition, ...]
    after: tuple[PromptDefinition, ...]
    evaluation: PromptRegressionEvaluation | None = None


class PromptLifecycleStore(Protocol):
    async def resolve(
        self, tenant_id: TenantId, prompt_id: PromptId, version: SemanticVersion
    ) -> PromptDefinition | None: ...

    async def active(self, tenant_id: TenantId, prompt_id: PromptId) -> PromptDefinition | None: ...

    async def apply(self, change: PromptLifecycleChange, audit_event: AuditEvent) -> None: ...


class PromptLifecycleManager:
    """Apply finite Prompt lifecycle transitions; the store owns transaction atomicity."""

    def __init__(
        self,
        store: PromptLifecycleStore,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    async def draft(
        self,
        definition: PromptDefinition,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> PromptDefinition:
        actor = require_permission(principal, Permission.ADMIN_MANAGE, tenant_id=_tenant(principal))
        if definition.status is not PromptLifecycleStatus.DRAFT:
            raise InvalidDomainValueError("new Prompt versions must begin as DRAFT")
        change = PromptLifecycleChange("drafted", (), (definition,))
        await self._apply(change, actor, correlation_id, causation_id, definition)
        return definition

    async def evaluate(
        self,
        evaluation: PromptRegressionEvaluation,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> PromptDefinition:
        actor = require_permission(principal, Permission.ADMIN_MANAGE, tenant_id=_tenant(principal))
        current = await self._required(actor.tenant_id, evaluation.prompt)
        if current.status is not PromptLifecycleStatus.DRAFT:
            raise InvalidDomainValueError("only DRAFT Prompt versions can be evaluated")
        if current.memory_aware and not evaluation.memory_comparison_passed:
            raise InvalidDomainValueError(
                "memory-aware Prompt requires a passing paired memory regression"
            )
        if not evaluation.passed:
            raise InvalidDomainValueError("Prompt regression fixture gate did not pass")
        evaluated = replace(current, status=PromptLifecycleStatus.EVALUATED)
        change = PromptLifecycleChange("evaluated", (current,), (evaluated,), evaluation)
        await self._apply(change, actor, correlation_id, causation_id, evaluated)
        return evaluated

    async def promote(
        self,
        reference: PromptVersionReference,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> PromptDefinition:
        actor = require_permission(principal, Permission.ADMIN_MANAGE, tenant_id=_tenant(principal))
        current = await self._required(actor.tenant_id, reference)
        if current.status is not PromptLifecycleStatus.EVALUATED:
            raise InvalidDomainValueError("only EVALUATED Prompt versions can be promoted")
        prior_active = await self._store.active(actor.tenant_id, reference.prompt_id)
        before = (current,) if prior_active is None else (prior_active, current)
        after = (
            (replace(current, status=PromptLifecycleStatus.ACTIVE),)
            if prior_active is None
            else (
                replace(prior_active, status=PromptLifecycleStatus.RETIRED),
                replace(current, status=PromptLifecycleStatus.ACTIVE),
            )
        )
        change = PromptLifecycleChange("promoted", before, after)
        promoted = after[-1]
        await self._apply(change, actor, correlation_id, causation_id, promoted)
        return promoted

    async def rollback(
        self,
        target: PromptVersionReference,
        replacement: PromptDefinition,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> PromptDefinition:
        actor = require_permission(principal, Permission.ADMIN_MANAGE, tenant_id=_tenant(principal))
        target_definition = await self._required(actor.tenant_id, target)
        active = await self._store.active(actor.tenant_id, target.prompt_id)
        if active is None or target_definition.status is not PromptLifecycleStatus.RETIRED:
            raise InvalidDomainValueError(
                "rollback requires an active and a retired target version"
            )
        expected_predecessor = PromptVersionReference(active.prompt_id, active.version)
        copied_contract = (
            replacement.prompt_id,
            replacement.purpose,
            replacement.content_fingerprint,
            replacement.model_parameters,
            replacement.schema_compatibility,
            replacement.status,
            replacement.rollback_predecessor,
        )
        expected_contract = (
            target_definition.prompt_id,
            target_definition.purpose,
            target_definition.content_fingerprint,
            target_definition.model_parameters,
            target_definition.schema_compatibility,
            PromptLifecycleStatus.DRAFT,
            expected_predecessor,
        )
        if (
            copied_contract != expected_contract
            or replacement.content != target_definition.content
            or replacement.version <= active.version
        ):
            raise InvalidDomainValueError(
                "rollback must create a newer copy of the retired target Prompt"
            )
        rolled_back = replace(replacement, status=PromptLifecycleStatus.ACTIVE)
        change = PromptLifecycleChange(
            "rolled_back",
            (active, target_definition),
            (replace(active, status=PromptLifecycleStatus.RETIRED), rolled_back),
        )
        await self._apply(change, actor, correlation_id, causation_id, rolled_back)
        return rolled_back

    async def _required(
        self, tenant_id: TenantId, reference: PromptVersionReference
    ) -> PromptDefinition:
        value = await self._store.resolve(tenant_id, reference.prompt_id, reference.version)
        if value is None:
            raise InvalidDomainValueError("Prompt lifecycle reference is not registered")
        return value

    async def _apply(
        self,
        change: PromptLifecycleChange,
        principal: Principal,
        correlation_id: CorrelationId,
        causation_id: CausationId,
        target: PromptDefinition,
    ) -> None:
        occurred_at = as_utc(self._clock())
        request_hash = _change_hash(change.action, change.before, change.evaluation)
        result_hash = _change_hash(change.action, change.after, change.evaluation)
        audit = AuditEvent(
            id=AuditEventId(self._id_factory()),
            tenant_id=principal.tenant_id,
            type=f"prompt.{change.action}",
            event_version=1,
            payload_schema_version="prompt/v1",
            actor_id=principal.actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            target=AuditTarget(
                "prompt.version",
                OpaqueIdentifier(f"{target.prompt_id.value}:{target.version.value}"),
            ),
            occurred_at=occurred_at,
            request_hash=request_hash,
            result_hash=result_hash,
        )
        await self._store.apply(change, audit)


def _tenant(principal: Principal | None) -> TenantId:
    if principal is None:
        return TenantId("unauthenticated")
    return principal.tenant_id


def _change_hash(
    action: str,
    definitions: tuple[PromptDefinition, ...],
    evaluation: PromptRegressionEvaluation | None,
) -> Sha256Digest:
    document: dict[str, object] = {
        "action": action,
        "definitions": [
            {
                "content_fingerprint": item.content_fingerprint.value,
                "prompt_id": item.prompt_id.value,
                "status": item.status.value,
                "version": item.version.value,
            }
            for item in definitions
        ],
    }
    if evaluation is not None:
        document["evaluation"] = {
            "evaluated_at": evaluation.evaluated_at.isoformat(),
            "fixtures": [
                {
                    "authorization_violations": item.authorization_violations,
                    "context": item.context.value,
                    "fabricated_references": item.fabricated_references,
                    "fixture_id": item.fixture_id,
                    "ground_truth_visible": item.ground_truth_visible,
                    "passed": item.passed,
                    "unsupported_conclusions": item.unsupported_conclusions,
                }
                for item in evaluation.results
            ],
            "suite_version": evaluation.suite_version.value,
        }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return Sha256Digest(hashlib.sha256(encoded).hexdigest())
