"""Evaluation-only PostgreSQL effect replay; incomplete effects never redispatch."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.domain import (
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    OpaqueIdentifier,
    Permission,
    Principal,
    RedactionTransformId,
    Sha256Digest,
    redact_sensitive_data,
    require_permission,
)
from agentops_incident_commander.domain.redaction import RedactableValue
from agentops_incident_commander.infrastructure.persistence.models import (
    AuditEventRow,
    IdempotencyRecordRow,
    IncidentRow,
)
from agentops_incident_commander.infrastructure.persistence.repositories import AuditRepository
from evaluation.structured_model import SCHEMAS, ModelPurpose, StructuredResult, fingerprint

_OPERATION = "evaluation.investigation.effect/v1"


class StoredModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    output: dict[str, Any]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int | None = Field(ge=0)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_ms: int = Field(ge=0)
    cost_upper_bound_nanousd: int = Field(ge=0)
    call_id: str | None

    @classmethod
    def capture(cls, result: StructuredResult) -> StoredModelResult:
        return cls(
            **{name: getattr(result, name) for name in cls.model_fields if name != "output"},
            output=result.output.model_dump(mode="json"),
        )

    def restore(self, purpose: ModelPurpose) -> StructuredResult:
        output = SCHEMAS[purpose].model_validate_json(json.dumps(self.output))
        return StructuredResult(**(self.model_dump() | {"output": output}))


class WorkflowEffectStore(Protocol):
    async def load(self, slot: str, binding: dict[str, Any]) -> dict[str, Any] | None: ...

    async def execute(
        self,
        slot: str,
        binding: dict[str, Any],
        effect: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]: ...


class SqlInvestigationEffects:
    """Reuse the existing command-idempotency table with a separate versioned namespace.

    Claim commits before external work. Complete commits payload/hash and audit together.
    An interrupted claim is deliberately not stolen: the external result may be unknown.
    No network call runs while a database transaction/connection is held.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        principal: Principal,
        correlation_id: str,
        causation_id: str,
    ) -> None:
        self.sessions, self.principal = sessions, principal
        self.correlation = CorrelationId(correlation_id)
        self.causation = CausationId(causation_id)

    def identity(self, slot: str, binding: dict[str, Any]) -> tuple[str, str]:
        require_permission(
            self.principal, Permission.INVESTIGATION_START, tenant_id=self.principal.tenant_id
        )
        if binding.get("tenant_id") != self.principal.tenant_id.value:
            raise ValueError("effect tenant binding mismatch")
        if binding.get("actor_id") != self.principal.actor_id.value:
            raise ValueError("effect actor binding mismatch")
        if (binding.get("correlation_id"), binding.get("causation_id")) != (
            self.correlation.value,
            self.causation.value,
        ):
            raise ValueError("effect trace binding mismatch")
        if (
            not slot
            or len(slot) > 256
            or not binding.get("workflow_run_id")
            or not binding.get("incident_id")
        ):
            raise ValueError("effect scope is incomplete")
        key = fingerprint(
            {name: binding[name] for name in ("tenant_id", "incident_id", "workflow_run_id")}
            | {"slot": slot}
        )
        return key, fingerprint(binding)

    def query(self, key: str) -> Any:
        return select(IdempotencyRecordRow).where(
            IdempotencyRecordRow.tenant_id == self.principal.tenant_id.value,
            IdempotencyRecordRow.operation == _OPERATION,
            IdempotencyRecordRow.idempotency_key == key,
        )

    @staticmethod
    def decode(row: IdempotencyRecordRow, request_hash: str) -> dict[str, Any]:
        if row.request_hash != request_hash:
            raise ValueError("effect input binding changed")
        body = row.response_body
        if row.completed_at is None or row.response_status != 200 or body is None:
            raise ValueError("effect outcome uncertain; redispatch forbidden")
        if (
            set(body) != {"schema_version", "payload", "payload_hash"}
            or body["schema_version"] != "1.0.0"
        ):
            raise ValueError("effect result schema mismatch")
        payload = body["payload"]
        if not isinstance(payload, dict) or fingerprint(payload) != body["payload_hash"]:
            raise ValueError("effect result integrity mismatch")
        return payload

    async def load(self, slot: str, binding: dict[str, Any]) -> dict[str, Any] | None:
        key, digest = self.identity(slot, binding)
        async with self.sessions() as session:
            await self.require_incident(session, binding)
            row = await session.scalar(self.query(key))
            return await self.verified(session, row, digest, key) if row is not None else None

    async def require_incident(self, session: AsyncSession, binding: dict[str, Any]) -> None:
        found = await session.scalar(
            select(IncidentRow.id).where(
                IncidentRow.id == binding["incident_id"],
                IncidentRow.tenant_id == self.principal.tenant_id.value,
            )
        )
        if found is None:
            raise ValueError("effect incident ownership unavailable")

    async def verified(
        self, session: AsyncSession, row: IdempotencyRecordRow, digest: str, key: str
    ) -> dict[str, Any]:
        payload = self.decode(row, digest)
        audit = await session.scalar(
            select(AuditEventRow.id).where(
                AuditEventRow.tenant_id == self.principal.tenant_id.value,
                AuditEventRow.actor_id == self.principal.actor_id.value,
                AuditEventRow.event_type == "evaluation.effect_completed",
                AuditEventRow.target_type == "evaluation.effect",
                AuditEventRow.target_id == key,
                AuditEventRow.request_hash == digest,
                AuditEventRow.result_hash == fingerprint(payload),
                AuditEventRow.correlation_id == self.correlation.value,
                AuditEventRow.causation_id == self.causation.value,
            )
        )
        if audit is None:
            raise ValueError("effect result audit binding unavailable")
        return payload

    async def audit(
        self,
        session: AsyncSession,
        key: str,
        digest: str,
        result: str | None,
        *,
        failed: bool = False,
    ) -> None:
        await AuditRepository(session).append(
            AuditEvent(
                id=AuditEventId(f"effect-audit-{uuid4().hex}"),
                tenant_id=self.principal.tenant_id,
                type="evaluation.effect_failed"
                if failed
                else ("evaluation.effect_completed" if result else "evaluation.effect_claimed"),
                event_version=1,
                payload_schema_version="investigation_effect/v1",
                actor_id=self.principal.actor_id,
                correlation_id=self.correlation,
                causation_id=self.causation,
                target=AuditTarget("evaluation.effect", OpaqueIdentifier(key)),
                occurred_at=datetime.now(UTC),
                request_hash=Sha256Digest(digest),
                result_hash=Sha256Digest(result) if result else None,
            )
        )

    async def execute(
        self,
        slot: str,
        binding: dict[str, Any],
        effect: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        key, digest = self.identity(slot, binding)
        lock = int.from_bytes(
            hashlib.sha256(f"{_OPERATION}:{key}".encode()).digest()[:8], signed=True
        )
        async with self.sessions.begin() as session:
            await self.require_incident(session, binding)
            if not await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock}
            ):
                raise ValueError("effect claim busy; redispatch forbidden")
            row = await session.scalar(self.query(key))
            if row is not None:
                return await self.verified(session, row, digest, key)
            session.add(
                IdempotencyRecordRow(
                    tenant_id=self.principal.tenant_id.value,
                    actor_id=self.principal.actor_id.value,
                    operation=_OPERATION,
                    idempotency_key=key,
                    request_hash=digest,
                    created_at=datetime.now(UTC),
                )
            )
            await self.audit(session, key, digest, None)
        try:
            payload = self.validate_payload(await effect())
        except BaseException:
            async with self.sessions.begin() as session:
                await self.audit(session, key, digest, None, failed=True)
            raise
        result_hash = fingerprint(payload)
        async with self.sessions.begin() as session:
            row = await session.scalar(self.query(key).with_for_update())
            if row is None or row.request_hash != digest or row.completed_at is not None:
                raise ValueError("effect completion binding mismatch")
            row.response_status = 200
            row.response_body = {
                "schema_version": "1.0.0",
                "payload": payload,
                "payload_hash": result_hash,
            }
            row.completed_at = datetime.now(UTC)
            await self.audit(session, key, digest, result_hash)
        return payload

    @staticmethod
    def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
        # Callers pass typed outputs, never provider bodies or prompts.
        if not isinstance(payload, dict):
            raise ValueError("effect result must be an object")
        serialized = json.dumps(payload, allow_nan=False, ensure_ascii=False)
        if len(serialized.encode()) > 256_000:
            raise ValueError("effect result exceeds bound")
        sanitized = redact_sensitive_data(
            cast(RedactableValue, payload),
            transform_id=RedactionTransformId("effect-result-validation"),
            lineage_key=secrets.token_bytes(32),
        )
        if sanitized.lineage:
            raise ValueError("effect result requires redaction")
        return cast(dict[str, Any], json.loads(serialized))
