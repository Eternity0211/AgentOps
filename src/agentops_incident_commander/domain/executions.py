"""Immutable recovery ActionExecution lifecycle and snapshot bindings."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .errors import InvalidDomainValueError
from .policy import PolicyEnvironment
from .recovery import IdempotencyKey, ResolvedRollbackTarget
from .tools import SemanticVersion
from .values import (
    ActorId,
    AggregateVersion,
    ApprovalId,
    ArtifactId,
    IncidentId,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    as_utc,
)

ACTION_EXECUTION_SCHEMA_VERSION = "1.0.0"
ACTION_SNAPSHOT_SCHEMA_VERSION = "1.0.0"
_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SERVICE = re.compile(r"^[a-z][a-z0-9-]{0,127}$")


class ActionExecutionStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class ActionSnapshot:
    artifact_id: ArtifactId
    tenant_id: TenantId
    incident_id: IncidentId
    service: str
    environment: PolicyEnvironment
    target_reference: OpaqueIdentifier
    deployed_version: SemanticVersion
    observed_at: datetime
    content_hash: Sha256Digest
    schema_version: str = ACTION_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.artifact_id, ArtifactId),
            (self.tenant_id, TenantId),
            (self.incident_id, IncidentId),
            (self.environment, PolicyEnvironment),
            (self.target_reference, OpaqueIdentifier),
            (self.deployed_version, SemanticVersion),
            (self.content_hash, Sha256Digest),
        )
        if any(not isinstance(value, kind) for value, kind in expected):
            raise InvalidDomainValueError("action snapshot types are invalid")
        if not isinstance(self.service, str) or _SERVICE.fullmatch(self.service) is None:
            raise InvalidDomainValueError("action snapshot service is invalid")
        if self.schema_version != ACTION_SNAPSHOT_SCHEMA_VERSION:
            raise InvalidDomainValueError("action snapshot schema version is unsupported")
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))


@dataclass(frozen=True, slots=True)
class ActionExecution:
    id: OpaqueIdentifier
    tenant_id: TenantId
    incident_id: IncidentId
    approval_id: ApprovalId
    idempotency_key: IdempotencyKey
    actor_id: ActorId
    proposal_fingerprint: Sha256Digest
    policy_decision_fingerprint: Sha256Digest
    target: ResolvedRollbackTarget
    before_snapshot: ActionSnapshot
    status: ActionExecutionStatus
    version: AggregateVersion
    started_at: datetime
    completed_at: datetime | None = None
    after_snapshot: ActionSnapshot | None = None
    failure_code: str | None = None
    schema_version: str = ACTION_EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.id, OpaqueIdentifier),
            (self.tenant_id, TenantId),
            (self.incident_id, IncidentId),
            (self.approval_id, ApprovalId),
            (self.idempotency_key, IdempotencyKey),
            (self.actor_id, ActorId),
            (self.proposal_fingerprint, Sha256Digest),
            (self.policy_decision_fingerprint, Sha256Digest),
            (self.target, ResolvedRollbackTarget),
            (self.before_snapshot, ActionSnapshot),
            (self.status, ActionExecutionStatus),
            (self.version, AggregateVersion),
        )
        if any(not isinstance(value, kind) for value, kind in expected):
            raise InvalidDomainValueError("action execution types are invalid")
        started_at = as_utc(self.started_at)
        completed_at = None if self.completed_at is None else as_utc(self.completed_at)
        if self.schema_version != ACTION_EXECUTION_SCHEMA_VERSION:
            raise InvalidDomainValueError("action execution schema version is unsupported")
        if (
            self.tenant_id != self.target.tenant_id
            or self.before_snapshot.tenant_id != self.tenant_id
            or self.before_snapshot.incident_id != self.incident_id
            or self.before_snapshot.service != self.target.service
            or self.before_snapshot.environment is not self.target.environment
            or self.before_snapshot.target_reference != self.target.target_reference
            or self.before_snapshot.deployed_version != self.target.expected_current_version
            or self.before_snapshot.observed_at > started_at
        ):
            raise InvalidDomainValueError("action execution before snapshot is not target-bound")
        terminal = self.status is not ActionExecutionStatus.STARTED
        if terminal != (completed_at is not None):
            raise InvalidDomainValueError("action execution completion state is inconsistent")
        if completed_at is not None and completed_at < started_at:
            raise InvalidDomainValueError("action execution cannot complete before it starts")
        if self.status is ActionExecutionStatus.SUCCEEDED:
            if self.after_snapshot is None or self.failure_code is not None:
                raise InvalidDomainValueError("successful action requires only an after snapshot")
            if self.after_snapshot.deployed_version != self.target.stable_version:
                raise InvalidDomainValueError("successful action did not reach the stable version")
        elif terminal:
            if self.failure_code is None or _FAILURE_CODE.fullmatch(self.failure_code) is None:
                raise InvalidDomainValueError("failed action requires a stable failure code")
        elif self.after_snapshot is not None or self.failure_code is not None:
            raise InvalidDomainValueError("started action cannot contain a terminal result")
        if self.after_snapshot is not None and (
            self.after_snapshot.tenant_id != self.tenant_id
            or self.after_snapshot.incident_id != self.incident_id
            or self.after_snapshot.service != self.target.service
            or self.after_snapshot.environment is not self.target.environment
            or self.after_snapshot.target_reference != self.target.target_reference
            or completed_at is None
            or self.after_snapshot.observed_at < started_at
            or self.after_snapshot.observed_at > completed_at
        ):
            raise InvalidDomainValueError("action execution after snapshot is not target-bound")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)

    @property
    def fingerprint(self) -> Sha256Digest:
        document = self._document()
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(canonical).hexdigest())

    @property
    def request_fingerprint(self) -> Sha256Digest:
        document = self._document()
        for field in (
            "after_snapshot",
            "completed_at",
            "failure_code",
            "id",
            "started_at",
            "status",
            "version",
        ):
            document.pop(field)
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return Sha256Digest(hashlib.sha256(canonical).hexdigest())

    def _document(self) -> dict[str, object]:
        return {
            "after_snapshot": _snapshot_document(self.after_snapshot),
            "approval_id": self.approval_id.value,
            "actor_id": self.actor_id.value,
            "before_snapshot": _snapshot_document(self.before_snapshot),
            "completed_at": None if self.completed_at is None else self.completed_at.isoformat(),
            "failure_code": self.failure_code,
            "id": self.id.value,
            "idempotency_key": self.idempotency_key.value,
            "incident_id": self.incident_id.value,
            "policy_decision_fingerprint": self.policy_decision_fingerprint.value,
            "proposal_fingerprint": self.proposal_fingerprint.value,
            "schema_version": self.schema_version,
            "started_at": self.started_at.isoformat(),
            "status": self.status.value,
            "target": {
                "environment": self.target.environment.value,
                "expected_current_version": self.target.expected_current_version.value,
                "service": self.target.service,
                "stable_version": self.target.stable_version.value,
                "target_reference": self.target.target_reference.value,
            },
            "tenant_id": self.tenant_id.value,
            "version": self.version.value,
        }

    def succeed(self, *, after_snapshot: ActionSnapshot, at: datetime) -> ActionExecution:
        return self._finish(
            ActionExecutionStatus.SUCCEEDED,
            at=at,
            after_snapshot=after_snapshot,
        )

    def fail(
        self,
        status: ActionExecutionStatus,
        *,
        failure_code: str,
        at: datetime,
        after_snapshot: ActionSnapshot | None = None,
    ) -> ActionExecution:
        if status not in {
            ActionExecutionStatus.FAILED,
            ActionExecutionStatus.TIMED_OUT,
            ActionExecutionStatus.UNCERTAIN,
        }:
            raise InvalidDomainValueError("action failure status is invalid")
        return self._finish(
            status,
            at=at,
            after_snapshot=after_snapshot,
            failure_code=failure_code,
        )

    def _finish(
        self,
        status: ActionExecutionStatus,
        *,
        at: datetime,
        after_snapshot: ActionSnapshot | None,
        failure_code: str | None = None,
    ) -> ActionExecution:
        if self.status is not ActionExecutionStatus.STARTED:
            raise InvalidDomainValueError("only a started action can finish")
        return replace(
            self,
            status=status,
            version=self.version.next(),
            completed_at=at,
            after_snapshot=after_snapshot,
            failure_code=failure_code,
        )


def _snapshot_document(snapshot: ActionSnapshot | None) -> dict[str, str] | None:
    if snapshot is None:
        return None
    return {
        "artifact_id": snapshot.artifact_id.value,
        "content_hash": snapshot.content_hash.value,
        "deployed_version": snapshot.deployed_version.value,
        "environment": snapshot.environment.value,
        "incident_id": snapshot.incident_id.value,
        "observed_at": snapshot.observed_at.isoformat(),
        "schema_version": snapshot.schema_version,
        "service": snapshot.service,
        "target_reference": snapshot.target_reference.value,
        "tenant_id": snapshot.tenant_id.value,
    }
