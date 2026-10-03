"""Artifact domain and local immutable storage tests."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agentops_incident_commander.domain import (
    ARTIFACT_METADATA_SCHEMA_VERSION,
    ActorId,
    Artifact,
    ArtifactAlreadyExistsError,
    ArtifactExpiredError,
    ArtifactId,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    AuthenticationError,
    AuthorizationError,
    IncidentId,
    InvalidDomainValueError,
    Principal,
    RedactionStatus,
    RetentionClass,
    Role,
    Sha256Digest,
    TenantId,
)
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage

NOW = datetime(2026, 10, 3, 8, tzinfo=UTC)
CONTENT = b'{"errors":["timeout"]}'


def viewer(*, tenant: str = "tenant-1") -> Principal:
    return Principal(ActorId("viewer"), TenantId(tenant), frozenset({Role.VIEWER}))


def artifact(
    *,
    artifact_id: str = "artifact-1",
    tenant: str = "tenant-1",
    incident: str = "incident-1",
    content: bytes = CONTENT,
    retention_class: RetentionClass = RetentionClass.INCIDENT,
    expires_at: datetime | None = NOW + timedelta(days=30),
) -> Artifact:
    identifier = ArtifactId(artifact_id)
    return Artifact(
        id=identifier,
        tenant_id=TenantId(tenant),
        incident_id=IncidentId(incident),
        locator=LocalArtifactStorage.locator(identifier),
        media_type="APPLICATION/JSON",
        content_schema_version="1.2.0",
        content_hash=Sha256Digest(hashlib.sha256(content).hexdigest()),
        size_bytes=len(content),
        retention_class=retention_class,
        created_at=NOW.astimezone(timezone(timedelta(hours=8))),
        expires_at=expires_at,
        redaction_status=RedactionStatus.REDACTED,
        encrypted=False,
    )


def test_artifact_normalizes_utc_and_exposes_expiry_boundary() -> None:
    value = artifact()

    assert value.media_type == "application/json"
    assert value.created_at == NOW
    assert value.metadata_schema_version == ARTIFACT_METADATA_SCHEMA_VERSION
    assert not value.is_expired(at=NOW + timedelta(days=29))
    assert value.is_expired(at=NOW + timedelta(days=30))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"media_type": "text"}, "media type"),
        ({"content_schema_version": "bad version"}, "content schema"),
        ({"metadata_schema_version": "2.0.0"}, "metadata schema"),
        ({"locator": "local-artifact:v1:different"}, "locator"),
        ({"size_bytes": True}, "size must be an integer"),
        ({"size_bytes": -1}, "size cannot be negative"),
        ({"expires_at": NOW}, "expiry must follow"),
        ({"retention_class": RetentionClass.TRANSIENT, "expires_at": None}, "require an expiry"),
        ({"encrypted": 1}, "must be boolean"),
    ],
)
def test_artifact_rejects_invalid_metadata(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        replace(artifact(), **changes)


def test_non_expiring_incident_and_audit_artifacts_are_allowed() -> None:
    assert artifact(expires_at=None).expires_at is None
    assert artifact(retention_class=RetentionClass.AUDIT, expires_at=None).expires_at is None


def test_local_store_persists_and_reloads_verified_content(tmp_path: Path) -> None:
    store = LocalArtifactStorage(tmp_path / "artifacts")
    value = artifact()

    assert store.store(value, CONTENT) == value
    reloaded = LocalArtifactStorage(tmp_path / "artifacts").retrieve(
        value.id, incident_id=value.incident_id, principal=viewer(), at=NOW
    )

    assert reloaded.artifact == value
    assert reloaded.content == CONTENT
    assert len(list((tmp_path / "artifacts" / "blobs").rglob(value.content_hash.value))) == 1


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_store_requires_a_positive_integer_limit(tmp_path: Path, limit: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="byte limit"):
        LocalArtifactStorage(tmp_path / "artifacts", max_artifact_bytes=limit)


def test_store_validates_bytes_limit_hash_and_size(tmp_path: Path) -> None:
    store = LocalArtifactStorage(tmp_path, max_artifact_bytes=len(CONTENT))
    value = artifact()

    with pytest.raises(InvalidDomainValueError, match="must be bytes"):
        store.store(value, "not-bytes")  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="byte limit"):
        store.store(value, CONTENT + b"x")
    with pytest.raises(ArtifactIntegrityError, match="size and hash"):
        store.store(replace(value, size_bytes=1), CONTENT)
    with pytest.raises(ArtifactIntegrityError, match="size and hash"):
        store.store(replace(value, content_hash=Sha256Digest("0" * 64)), CONTENT)


def test_artifact_identity_is_create_once_even_for_identical_content(tmp_path: Path) -> None:
    store = LocalArtifactStorage(tmp_path)
    value = artifact()
    store.store(value, CONTENT)

    with pytest.raises(ArtifactAlreadyExistsError):
        store.store(value, CONTENT)

    second = artifact(artifact_id="artifact-2")
    store.store(second, CONTENT)
    assert len(list((tmp_path / "blobs").rglob(value.content_hash.value))) == 1


def test_concurrent_creation_has_one_winner_and_never_overwrites(tmp_path: Path) -> None:
    store = LocalArtifactStorage(tmp_path)
    value = artifact()

    def attempt() -> str:
        try:
            store.store(value, CONTENT)
        except ArtifactAlreadyExistsError:
            return "duplicate"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _: attempt(), range(2)))

    assert outcomes == ["created", "duplicate"]
    assert (
        store.retrieve(value.id, incident_id=value.incident_id, principal=viewer(), at=NOW).content
        == CONTENT
    )


def test_retrieval_fails_closed_for_identity_permission_incident_and_expiry(tmp_path: Path) -> None:
    store = LocalArtifactStorage(tmp_path)
    value = artifact()
    store.store(value, CONTENT)

    with pytest.raises(ArtifactNotFoundError, match="does not exist"):
        store.retrieve(
            ArtifactId("missing"),
            incident_id=value.incident_id,
            principal=viewer(),
            at=NOW,
        )
    with pytest.raises(AuthenticationError):
        store.retrieve(value.id, incident_id=value.incident_id, principal=None, at=NOW)
    with pytest.raises(AuthorizationError, match="another tenant"):
        store.retrieve(
            value.id, incident_id=value.incident_id, principal=viewer(tenant="tenant-2"), at=NOW
        )
    with pytest.raises(ArtifactNotFoundError, match="requested incident"):
        store.retrieve(value.id, incident_id=IncidentId("incident-2"), principal=viewer(), at=NOW)
    with pytest.raises(ArtifactExpiredError):
        store.retrieve(
            value.id,
            incident_id=value.incident_id,
            principal=viewer(),
            at=NOW + timedelta(days=30),
        )


def test_retrieval_detects_missing_or_modified_content(tmp_path: Path) -> None:
    store = LocalArtifactStorage(tmp_path)
    value = artifact()
    store.store(value, CONTENT)
    blob = next((tmp_path / "blobs").rglob(value.content_hash.value))

    blob.write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError, match="integrity verification"):
        store.retrieve(value.id, incident_id=value.incident_id, principal=viewer(), at=NOW)

    blob.unlink()
    with pytest.raises(ArtifactIntegrityError, match="missing"):
        store.retrieve(value.id, incident_id=value.incident_id, principal=viewer(), at=NOW)


def test_existing_content_address_with_wrong_bytes_is_rejected(tmp_path: Path) -> None:
    store = LocalArtifactStorage(tmp_path)
    value = artifact()
    blob = tmp_path / "blobs" / value.content_hash.value[:2] / value.content_hash.value
    blob.parent.mkdir()
    blob.write_bytes(b"collision")

    with pytest.raises(ArtifactIntegrityError, match="collision"):
        store.store(value, CONTENT)


@pytest.mark.parametrize(
    "document",
    [
        b"not-json",
        b"[]",
        b"{}",
        json.dumps({"id": 3}).encode(),
    ],
)
def test_invalid_metadata_is_never_used_for_authorization(tmp_path: Path, document: bytes) -> None:
    store = LocalArtifactStorage(tmp_path)
    (tmp_path / "metadata" / "artifact-1.json").write_bytes(document)

    with pytest.raises(ArtifactIntegrityError, match="metadata failed validation"):
        store.retrieve(
            ArtifactId("artifact-1"),
            incident_id=IncidentId("incident-1"),
            principal=viewer(),
            at=NOW,
        )


def test_metadata_identity_substitution_is_detected(tmp_path: Path) -> None:
    store = LocalArtifactStorage(tmp_path)
    value = artifact(artifact_id="artifact-other")
    metadata = json.loads(store._encode_metadata(value))
    (tmp_path / "metadata" / "artifact-1.json").write_text(json.dumps(metadata))

    with pytest.raises(ArtifactIntegrityError, match="identity does not match"):
        store.retrieve(
            ArtifactId("artifact-1"),
            incident_id=IncidentId("incident-1"),
            principal=viewer(),
            at=NOW,
        )


def test_root_and_internal_symlinks_are_rejected_without_following_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == root or original(path))
    with pytest.raises(InvalidDomainValueError, match="root"):
        LocalArtifactStorage(root)

    (root / "blobs").mkdir()
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == root / "blobs" or original(path),
    )
    with pytest.raises(InvalidDomainValueError, match="directories"):
        LocalArtifactStorage(root)


def test_blob_directory_and_file_symlinks_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalArtifactStorage(tmp_path)
    value = artifact()
    blob = tmp_path / "blobs" / value.content_hash.value[:2] / value.content_hash.value
    original = Path.is_symlink

    blob.parent.mkdir()
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == blob.parent or original(path))
    with pytest.raises(InvalidDomainValueError, match="blob directory"):
        store.store(value, CONTENT)

    monkeypatch.setattr(Path, "is_symlink", lambda path: path == blob or original(path))
    with pytest.raises(InvalidDomainValueError, match="storage file"):
        store.store(value, CONTENT)


def test_metadata_creation_race_is_reported_as_immutable_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalArtifactStorage(tmp_path)
    value = artifact()
    original = store._write_once

    def race(path: Path, content: bytes) -> None:
        if path.parent.name == "metadata":
            raise FileExistsError
        original(path, content)

    monkeypatch.setattr(store, "_write_once", race)
    with pytest.raises(ArtifactAlreadyExistsError):
        store.store(value, CONTENT)


def test_containment_check_rejects_paths_outside_root(tmp_path: Path) -> None:
    store = LocalArtifactStorage(tmp_path / "root")
    with pytest.raises(InvalidDomainValueError, match="escapes"):
        store._assert_contained(tmp_path / "outside")
