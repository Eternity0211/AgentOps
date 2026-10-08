"""Immutable, idempotent Artifact snapshots for authorized rollback execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Protocol

from agentops_incident_commander.application import (
    AuthorizedRollbackExecution,
    RollbackAdapterResult,
)
from agentops_incident_commander.domain import (
    ACTION_SNAPSHOT_SCHEMA_VERSION,
    ActionSnapshot,
    Artifact,
    ArtifactAlreadyExistsError,
    ArtifactContent,
    ArtifactId,
    ArtifactNotFoundError,
    ArtifactStorage,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    PolicyEnvironment,
    Principal,
    RedactionStatus,
    ResolvedRollbackTarget,
    RetentionClass,
    Role,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    as_utc,
)

ACTION_SNAPSHOT_CONTENT_SCHEMA_VERSION = "action-snapshot-1.0.0"
_SnapshotKind = Literal["BEFORE", "AFTER"]
_CONTENT_FIELDS = frozenset(
    {
        "deployed_version",
        "environment",
        "incident_id",
        "kind",
        "observed_at",
        "operation_reference",
        "schema_version",
        "service",
        "target_reference",
        "tenant_id",
    }
)


class DeploymentVersionObserver(Protocol):
    """Read the version of the server-resolved deployment target."""

    async def deployed_version(
        self,
        target: ResolvedRollbackTarget,
    ) -> SemanticVersion: ...


class ImmutableActionSnapshotWriter:
    """Persist content-bound before/after observations with deterministic identities."""

    def __init__(self, observer: DeploymentVersionObserver, storage: ArtifactStorage) -> None:
        self._observer = observer
        self._storage = storage

    async def persist_before_snapshot(
        self,
        authority: AuthorizedRollbackExecution,
        *,
        observed_at: datetime,
    ) -> ActionSnapshot:
        self._validate_authority(authority)
        observed_at = as_utc(observed_at)
        existing = self._load_existing(
            authority,
            kind="BEFORE",
            expected_version=authority.target.expected_current_version,
            operation_reference=None,
            at=observed_at,
        )
        if existing is not None:
            return existing
        deployed = await self._observe(authority)
        if deployed != authority.target.expected_current_version:
            raise InvalidDomainValueError(
                "before snapshot deployed version changed after preflight"
            )
        return self._store(
            authority,
            kind="BEFORE",
            deployed_version=deployed,
            operation_reference=None,
            observed_at=observed_at,
        )

    async def persist_after_snapshot(
        self,
        authority: AuthorizedRollbackExecution,
        result: RollbackAdapterResult,
        *,
        observed_at: datetime,
    ) -> ActionSnapshot:
        self._validate_authority(authority)
        if not isinstance(result, RollbackAdapterResult) or (
            result.service != authority.target.service
            or result.deployed_version != authority.target.stable_version
        ):
            raise InvalidDomainValueError("after snapshot adapter result is not target-bound")
        observed_at = as_utc(observed_at)
        existing = self._load_existing(
            authority,
            kind="AFTER",
            expected_version=result.deployed_version,
            operation_reference=result.operation_reference,
            at=observed_at,
        )
        if existing is not None:
            return existing
        deployed = await self._observe(authority)
        if deployed != result.deployed_version:
            raise InvalidDomainValueError("after snapshot does not confirm the adapter result")
        return self._store(
            authority,
            kind="AFTER",
            deployed_version=deployed,
            operation_reference=result.operation_reference,
            observed_at=observed_at,
        )

    async def _observe(self, authority: AuthorizedRollbackExecution) -> SemanticVersion:
        deployed = await self._observer.deployed_version(authority.target)
        if not isinstance(deployed, SemanticVersion):
            raise InvalidDomainValueError("deployment observer returned an invalid version")
        return deployed

    def _store(
        self,
        authority: AuthorizedRollbackExecution,
        *,
        kind: _SnapshotKind,
        deployed_version: SemanticVersion,
        operation_reference: OpaqueIdentifier | None,
        observed_at: datetime,
    ) -> ActionSnapshot:
        artifact_id = self._artifact_id(authority, kind)
        content = self._content(
            authority,
            kind=kind,
            deployed_version=deployed_version,
            operation_reference=operation_reference,
            observed_at=observed_at,
        )
        content_hash = Sha256Digest(hashlib.sha256(content).hexdigest())
        artifact = Artifact(
            id=artifact_id,
            tenant_id=authority.incident.tenant_id,
            incident_id=authority.incident.id,
            locator=f"local-artifact:v1:{artifact_id.value}",
            media_type="application/json",
            content_schema_version=ACTION_SNAPSHOT_CONTENT_SCHEMA_VERSION,
            content_hash=content_hash,
            size_bytes=len(content),
            retention_class=RetentionClass.INCIDENT,
            created_at=observed_at,
            expires_at=None,
            redaction_status=RedactionStatus.NOT_REQUIRED,
            encrypted=False,
        )
        try:
            stored = self._storage.store(artifact, content)
        except ArtifactAlreadyExistsError:
            existing = self._load_existing(
                authority,
                kind=kind,
                expected_version=deployed_version,
                operation_reference=operation_reference,
                at=observed_at,
            )
            if existing is None:  # pragma: no cover - storage contract defense
                raise InvalidDomainValueError("stored action snapshot disappeared") from None
            return existing
        if stored != artifact:
            raise InvalidDomainValueError("artifact storage returned different snapshot metadata")
        return ActionSnapshot(
            artifact_id=artifact_id,
            tenant_id=authority.incident.tenant_id,
            incident_id=authority.incident.id,
            service=authority.target.service,
            environment=authority.target.environment,
            target_reference=authority.target.target_reference,
            deployed_version=deployed_version,
            observed_at=observed_at,
            content_hash=content_hash,
        )

    def _load_existing(
        self,
        authority: AuthorizedRollbackExecution,
        *,
        kind: _SnapshotKind,
        expected_version: SemanticVersion,
        operation_reference: OpaqueIdentifier | None,
        at: datetime,
    ) -> ActionSnapshot | None:
        artifact_id = self._artifact_id(authority, kind)
        principal = Principal(
            authority.actor_id,
            authority.incident.tenant_id,
            frozenset({Role.OPERATOR}),
        )
        try:
            stored = self._storage.retrieve(
                artifact_id,
                incident_id=authority.incident.id,
                principal=principal,
                at=at,
            )
        except ArtifactNotFoundError:
            return None
        try:
            if not isinstance(stored, ArtifactContent):
                raise TypeError
            raw = json.loads(stored.content)
            if not isinstance(raw, dict) or set(raw) != _CONTENT_FIELDS:
                raise TypeError
            snapshot = ActionSnapshot(
                artifact_id=stored.artifact.id,
                tenant_id=TenantId(raw["tenant_id"]),
                incident_id=IncidentId(raw["incident_id"]),
                service=raw["service"],
                environment=PolicyEnvironment(raw["environment"]),
                target_reference=OpaqueIdentifier(raw["target_reference"]),
                deployed_version=SemanticVersion(raw["deployed_version"]),
                observed_at=datetime.fromisoformat(raw["observed_at"]),
                content_hash=stored.artifact.content_hash,
                schema_version=raw["schema_version"],
            )
            operation = raw["operation_reference"]
            if operation is not None:
                operation = OpaqueIdentifier(operation)
        except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise InvalidDomainValueError("stored action snapshot content is invalid") from error
        expected_scope = (
            authority.incident.tenant_id,
            authority.incident.id,
            authority.target.service,
            authority.target.environment,
            authority.target.target_reference,
            expected_version,
        )
        actual_scope = (
            snapshot.tenant_id,
            snapshot.incident_id,
            snapshot.service,
            snapshot.environment,
            snapshot.target_reference,
            snapshot.deployed_version,
        )
        if (
            raw.get("kind") != kind
            or operation != operation_reference
            or actual_scope != expected_scope
            or stored.artifact.id != artifact_id
            or stored.artifact.tenant_id != snapshot.tenant_id
            or stored.artifact.incident_id != snapshot.incident_id
            or stored.artifact.media_type != "application/json"
            or stored.artifact.content_schema_version != ACTION_SNAPSHOT_CONTENT_SCHEMA_VERSION
            or stored.artifact.retention_class is not RetentionClass.INCIDENT
            or stored.artifact.created_at != snapshot.observed_at
            or stored.artifact.expires_at is not None
            or stored.artifact.redaction_status is not RedactionStatus.NOT_REQUIRED
            or stored.artifact.encrypted
            or stored.artifact.size_bytes != len(stored.content)
            or stored.artifact.content_hash
            != Sha256Digest(hashlib.sha256(stored.content).hexdigest())
        ):
            raise InvalidDomainValueError("stored action snapshot is not authority-bound")
        return snapshot

    @staticmethod
    def _validate_authority(authority: AuthorizedRollbackExecution) -> None:
        if not isinstance(authority, AuthorizedRollbackExecution):
            raise InvalidDomainValueError("action snapshot authority is invalid")

    @staticmethod
    def _artifact_id(
        authority: AuthorizedRollbackExecution,
        kind: _SnapshotKind,
    ) -> ArtifactId:
        identity = {
            "actor_id": authority.actor_id.value,
            "idempotency_key": authority.request.idempotency_key.value,
            "incident_id": authority.incident.id.value,
            "kind": kind,
            "tenant_id": authority.incident.tenant_id.value,
        }
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        return ArtifactId(f"action-snapshot-{hashlib.sha256(canonical).hexdigest()}")

    @staticmethod
    def _content(
        authority: AuthorizedRollbackExecution,
        *,
        kind: _SnapshotKind,
        deployed_version: SemanticVersion,
        operation_reference: OpaqueIdentifier | None,
        observed_at: datetime,
    ) -> bytes:
        document = {
            "deployed_version": deployed_version.value,
            "environment": authority.target.environment.value,
            "incident_id": authority.incident.id.value,
            "kind": kind,
            "observed_at": observed_at.isoformat(),
            "operation_reference": (
                None if operation_reference is None else operation_reference.value
            ),
            "schema_version": ACTION_SNAPSHOT_SCHEMA_VERSION,
            "service": authority.target.service,
            "target_reference": authority.target.target_reference.value,
            "tenant_id": authority.incident.tenant_id.value,
        }
        return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
