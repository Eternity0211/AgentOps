"""Immutable rollback before/after Artifact snapshot tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from test_action_dispatch import authority

from agentops_incident_commander.application import (
    AuthorizedRollbackExecution,
    RollbackAdapterResult,
)
from agentops_incident_commander.domain import (
    Artifact,
    ArtifactAlreadyExistsError,
    ArtifactContent,
    ArtifactId,
    ArtifactStorage,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Principal,
    Role,
    SemanticVersion,
    Sha256Digest,
)
from agentops_incident_commander.infrastructure import (
    ACTION_SNAPSHOT_CONTENT_SCHEMA_VERSION,
    ImmutableActionSnapshotWriter,
)
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage

NOW = datetime(2026, 10, 8, 8, 0, tzinfo=UTC)


class Observer:
    def __init__(self, version: object) -> None:
        self.version = version
        self.calls: list[object] = []

    async def deployed_version(self, target: object) -> SemanticVersion:
        self.calls.append(target)
        return cast(SemanticVersion, self.version)


class StoreResultSubstitution:
    def __init__(self, delegate: ArtifactStorage) -> None:
        self.delegate = delegate

    def store(self, artifact: Artifact, content: bytes) -> Artifact:
        self.delegate.store(artifact, content)
        return replace(artifact, encrypted=True)

    def retrieve(
        self,
        artifact_id: ArtifactId,
        *,
        incident_id: IncidentId,
        principal: Principal | None,
        at: datetime,
    ) -> ArtifactContent:
        return self.delegate.retrieve(
            artifact_id,
            incident_id=incident_id,
            principal=principal,
            at=at,
        )


class ConcurrentWinnerStorage(StoreResultSubstitution):
    def store(self, artifact: Artifact, content: bytes) -> Artifact:
        self.delegate.store(artifact, content)
        raise ArtifactAlreadyExistsError("concurrent winner")


class CorruptReadStorage(StoreResultSubstitution):
    def retrieve(
        self,
        artifact_id: ArtifactId,
        *,
        incident_id: IncidentId,
        principal: Principal | None,
        at: datetime,
    ) -> ArtifactContent:
        stored = super().retrieve(
            artifact_id,
            incident_id=incident_id,
            principal=principal,
            at=at,
        )
        return ArtifactContent(stored.artifact, b"[]")


class CorruptHashStorage(StoreResultSubstitution):
    def retrieve(
        self,
        artifact_id: ArtifactId,
        *,
        incident_id: IncidentId,
        principal: Principal | None,
        at: datetime,
    ) -> ArtifactContent:
        stored = super().retrieve(
            artifact_id,
            incident_id=incident_id,
            principal=principal,
            at=at,
        )
        return ArtifactContent(
            replace(stored.artifact, content_hash=Sha256Digest("0" * 64)),
            stored.content,
        )


class InvalidReadStorage(StoreResultSubstitution):
    def retrieve(
        self,
        artifact_id: ArtifactId,
        *,
        incident_id: IncidentId,
        principal: Principal | None,
        at: datetime,
    ) -> ArtifactContent:
        return cast(ArtifactContent, "invalid")


def storage(path: Path) -> LocalArtifactStorage:
    return LocalArtifactStorage(path / "artifacts")


def principal(authorized: AuthorizedRollbackExecution) -> Principal:
    return Principal(
        authorized.actor_id,
        authorized.incident.tenant_id,
        frozenset({Role.OPERATOR}),
    )


@pytest.mark.anyio
async def test_before_snapshot_is_immutable_content_bound_and_replayed(tmp_path: Path) -> None:
    authorized = authority()
    backend = Observer(SemanticVersion("2.0.0"))
    artifacts = storage(tmp_path)
    writer = ImmutableActionSnapshotWriter(backend, artifacts)

    first = await writer.persist_before_snapshot(authorized, observed_at=NOW)
    backend.version = SemanticVersion("1.0.0")
    replay = await writer.persist_before_snapshot(
        authorized,
        observed_at=NOW + timedelta(minutes=1),
    )

    assert replay == first
    assert backend.calls == [authorized.target]
    assert first.deployed_version == authorized.target.expected_current_version
    stored = artifacts.retrieve(
        first.artifact_id,
        incident_id=authorized.incident.id,
        principal=principal(authorized),
        at=NOW,
    )
    document = json.loads(stored.content)
    assert stored.artifact.content_schema_version == ACTION_SNAPSHOT_CONTENT_SCHEMA_VERSION
    assert stored.artifact.content_hash == first.content_hash
    assert document == {
        "deployed_version": "2.0.0",
        "environment": "PRODUCTION",
        "incident_id": authorized.incident.id.value,
        "kind": "BEFORE",
        "observed_at": NOW.isoformat(),
        "operation_reference": None,
        "schema_version": "1.0.0",
        "service": authorized.target.service,
        "target_reference": authorized.target.target_reference.value,
        "tenant_id": authorized.incident.tenant_id.value,
    }


@pytest.mark.anyio
async def test_after_snapshot_confirms_observed_result_and_replays(tmp_path: Path) -> None:
    authorized = authority()
    backend = Observer(SemanticVersion("1.0.0"))
    artifacts = storage(tmp_path)
    writer = ImmutableActionSnapshotWriter(backend, artifacts)
    result = RollbackAdapterResult(
        authorized.target.service,
        authorized.target.stable_version,
        OpaqueIdentifier("operation-1"),
    )

    first = await writer.persist_after_snapshot(authorized, result, observed_at=NOW)
    replay = await writer.persist_after_snapshot(
        authorized,
        result,
        observed_at=NOW + timedelta(minutes=1),
    )

    assert replay == first
    assert backend.calls == [authorized.target]
    stored = artifacts.retrieve(
        first.artifact_id,
        incident_id=authorized.incident.id,
        principal=principal(authorized),
        at=NOW,
    )
    assert json.loads(stored.content)["operation_reference"] == "operation-1"


@pytest.mark.anyio
async def test_concurrent_identical_snapshot_store_returns_winner(tmp_path: Path) -> None:
    authorized = authority()
    delegate = storage(tmp_path)
    writer = ImmutableActionSnapshotWriter(
        Observer(authorized.target.expected_current_version),
        ConcurrentWinnerStorage(delegate),
    )

    snapshot = await writer.persist_before_snapshot(authorized, observed_at=NOW)

    assert snapshot.observed_at == NOW


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("backend_version", "before", "message"),
    [
        (SemanticVersion("1.0.0"), True, "changed after preflight"),
        (SemanticVersion("2.0.0"), False, "does not confirm"),
        ("invalid", True, "invalid version"),
    ],
)
async def test_snapshot_rejects_unconfirmed_or_untyped_observation(
    tmp_path: Path,
    backend_version: object,
    before: bool,
    message: str,
) -> None:
    authorized = authority()
    writer = ImmutableActionSnapshotWriter(Observer(backend_version), storage(tmp_path))
    with pytest.raises(InvalidDomainValueError, match=message):
        if before:
            await writer.persist_before_snapshot(authorized, observed_at=NOW)
        else:
            await writer.persist_after_snapshot(
                authorized,
                RollbackAdapterResult(
                    authorized.target.service,
                    authorized.target.stable_version,
                    OpaqueIdentifier("operation-2"),
                ),
                observed_at=NOW,
            )


@pytest.mark.anyio
@pytest.mark.parametrize("result", ["invalid", None])
async def test_after_snapshot_rejects_untyped_result(tmp_path: Path, result: object) -> None:
    with pytest.raises(InvalidDomainValueError, match="not target-bound"):
        await ImmutableActionSnapshotWriter(
            Observer("unused"), storage(tmp_path)
        ).persist_after_snapshot(
            authority(),
            cast(RollbackAdapterResult, result),
            observed_at=NOW,
        )


@pytest.mark.anyio
async def test_after_snapshot_rejects_result_scope_substitution(tmp_path: Path) -> None:
    authorized = authority()
    result = RollbackAdapterResult(
        "inventory",
        authorized.target.stable_version,
        OpaqueIdentifier("operation-3"),
    )
    with pytest.raises(InvalidDomainValueError, match="not target-bound"):
        await ImmutableActionSnapshotWriter(
            Observer("unused"), storage(tmp_path)
        ).persist_after_snapshot(
            authorized,
            result,
            observed_at=NOW,
        )


@pytest.mark.anyio
async def test_existing_after_snapshot_rejects_changed_operation(tmp_path: Path) -> None:
    authorized = authority()
    artifacts = storage(tmp_path)
    writer = ImmutableActionSnapshotWriter(
        Observer(authorized.target.stable_version),
        artifacts,
    )
    await writer.persist_after_snapshot(
        authorized,
        RollbackAdapterResult(
            authorized.target.service,
            authorized.target.stable_version,
            OpaqueIdentifier("operation-original"),
        ),
        observed_at=NOW,
    )

    with pytest.raises(InvalidDomainValueError, match="not authority-bound"):
        await writer.persist_after_snapshot(
            authorized,
            RollbackAdapterResult(
                authorized.target.service,
                authorized.target.stable_version,
                OpaqueIdentifier("operation-changed"),
            ),
            observed_at=NOW + timedelta(minutes=1),
        )


@pytest.mark.anyio
async def test_existing_snapshot_rejects_invalid_content(tmp_path: Path) -> None:
    authorized = authority()
    delegate = storage(tmp_path)
    valid = ImmutableActionSnapshotWriter(
        Observer(authorized.target.expected_current_version),
        delegate,
    )
    await valid.persist_before_snapshot(authorized, observed_at=NOW)

    with pytest.raises(InvalidDomainValueError, match="content is invalid"):
        await ImmutableActionSnapshotWriter(
            Observer("unused"),
            CorruptReadStorage(delegate),
        ).persist_before_snapshot(authorized, observed_at=NOW)


@pytest.mark.anyio
async def test_existing_snapshot_rejects_content_hash_substitution(tmp_path: Path) -> None:
    authorized = authority()
    delegate = storage(tmp_path)
    valid = ImmutableActionSnapshotWriter(
        Observer(authorized.target.expected_current_version),
        delegate,
    )
    await valid.persist_before_snapshot(authorized, observed_at=NOW)

    with pytest.raises(InvalidDomainValueError, match="not authority-bound"):
        await ImmutableActionSnapshotWriter(
            Observer("unused"),
            CorruptHashStorage(delegate),
        ).persist_before_snapshot(authorized, observed_at=NOW)


@pytest.mark.anyio
async def test_existing_snapshot_rejects_untyped_storage_result(tmp_path: Path) -> None:
    authorized = authority()
    delegate = storage(tmp_path)
    valid = ImmutableActionSnapshotWriter(
        Observer(authorized.target.expected_current_version),
        delegate,
    )
    await valid.persist_before_snapshot(authorized, observed_at=NOW)

    with pytest.raises(InvalidDomainValueError, match="content is invalid"):
        await ImmutableActionSnapshotWriter(
            Observer("unused"),
            InvalidReadStorage(delegate),
        ).persist_before_snapshot(authorized, observed_at=NOW)


@pytest.mark.anyio
async def test_snapshot_rejects_storage_metadata_substitution(tmp_path: Path) -> None:
    authorized = authority()
    writer = ImmutableActionSnapshotWriter(
        Observer(authorized.target.expected_current_version),
        StoreResultSubstitution(storage(tmp_path)),
    )
    with pytest.raises(InvalidDomainValueError, match="different snapshot metadata"):
        await writer.persist_before_snapshot(authorized, observed_at=NOW)


@pytest.mark.anyio
async def test_snapshot_rejects_untyped_authority(tmp_path: Path) -> None:
    writer = ImmutableActionSnapshotWriter(Observer("unused"), storage(tmp_path))
    with pytest.raises(InvalidDomainValueError, match="authority is invalid"):
        await writer.persist_before_snapshot(
            cast(AuthorizedRollbackExecution, "invalid"),
            observed_at=NOW,
        )
