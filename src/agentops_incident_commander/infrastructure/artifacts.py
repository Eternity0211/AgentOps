"""Filesystem-backed immutable Artifact storage for local development."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from agentops_incident_commander.domain import (
    Artifact,
    ArtifactAlreadyExistsError,
    ArtifactContent,
    ArtifactExpiredError,
    ArtifactId,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    IncidentId,
    InvalidDomainValueError,
    Permission,
    Principal,
    RedactionStatus,
    RetentionClass,
    Sha256Digest,
    TenantId,
    require_permission,
)

DEFAULT_MAX_ARTIFACT_BYTES: Final = 16 * 1024 * 1024


class LocalArtifactStorage:
    """Store immutable blobs and metadata beneath one trusted local root."""

    def __init__(self, root: Path, *, max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES) -> None:
        if not isinstance(max_artifact_bytes, int) or isinstance(max_artifact_bytes, bool):
            raise InvalidDomainValueError("artifact byte limit must be an integer")
        if max_artifact_bytes < 1:
            raise InvalidDomainValueError("artifact byte limit must be positive")
        root = root.absolute()
        if root.exists() and root.is_symlink():
            raise InvalidDomainValueError("artifact root cannot be a symbolic link")
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve(strict=True)
        self._blobs = self._trusted_directory("blobs")
        self._metadata = self._trusted_directory("metadata")
        self._max_artifact_bytes = max_artifact_bytes

    @staticmethod
    def locator(artifact_id: ArtifactId) -> str:
        """Generate an opaque locator; callers never supply filesystem paths."""
        return f"local-artifact:v1:{artifact_id.value}"

    def store(self, artifact: Artifact, content: bytes) -> Artifact:
        """Create an Artifact once; the same identity can never be overwritten."""
        if not isinstance(content, bytes):
            raise InvalidDomainValueError("artifact content must be bytes")
        if len(content) > self._max_artifact_bytes:
            raise InvalidDomainValueError("artifact content exceeds the configured byte limit")
        actual_hash = Sha256Digest(hashlib.sha256(content).hexdigest())
        if artifact.size_bytes != len(content) or artifact.content_hash != actual_hash:
            raise ArtifactIntegrityError("artifact content does not match declared size and hash")
        metadata_path = self._metadata_path(artifact.id)
        if metadata_path.exists():
            raise ArtifactAlreadyExistsError("artifact identity already exists")
        self._write_blob_once(self._blob_path(actual_hash), content)
        try:
            self._write_once(metadata_path, self._encode_metadata(artifact))
        except FileExistsError as error:
            raise ArtifactAlreadyExistsError("artifact identity already exists") from error
        return artifact

    def retrieve(
        self,
        artifact_id: ArtifactId,
        *,
        incident_id: IncidentId,
        principal: Principal | None,
        at: datetime,
    ) -> ArtifactContent:
        """Authorize ownership, enforce expiry, and verify content on every read."""
        artifact = self._load_metadata(artifact_id)
        require_permission(principal, Permission.EVIDENCE_READ, tenant_id=artifact.tenant_id)
        if artifact.incident_id != incident_id:
            raise ArtifactNotFoundError("artifact does not belong to the requested incident")
        if artifact.is_expired(at=at):
            raise ArtifactExpiredError("artifact content has expired")
        path = self._blob_path(artifact.content_hash)
        try:
            content = path.read_bytes()
        except FileNotFoundError as error:
            raise ArtifactIntegrityError("artifact content is missing") from error
        actual = Sha256Digest(hashlib.sha256(content).hexdigest())
        if actual != artifact.content_hash or len(content) != artifact.size_bytes:
            raise ArtifactIntegrityError("artifact content failed integrity verification")
        return ArtifactContent(artifact, content)

    def _trusted_directory(self, name: str) -> Path:
        path = self._root / name
        if path.exists() and path.is_symlink():
            raise InvalidDomainValueError("artifact storage directories cannot be symbolic links")
        path.mkdir(exist_ok=True)
        resolved = path.resolve(strict=True)
        self._assert_contained(resolved)
        return resolved

    def _assert_contained(self, path: Path) -> None:
        try:
            path.relative_to(self._root)
        except ValueError as error:
            raise InvalidDomainValueError(
                "artifact storage path escapes its trusted root"
            ) from error

    def _metadata_path(self, artifact_id: ArtifactId) -> Path:
        path = self._metadata / f"{artifact_id.value}.json"
        self._assert_safe_file(path)
        return path

    def _blob_path(self, digest: Sha256Digest) -> Path:
        path = self._blobs / digest.value[:2] / digest.value
        parent = path.parent
        if parent.exists() and parent.is_symlink():
            raise InvalidDomainValueError("artifact blob directory cannot be a symbolic link")
        parent.mkdir(exist_ok=True)
        self._assert_safe_file(path)
        return path

    def _assert_safe_file(self, path: Path) -> None:
        self._assert_contained(path.parent.resolve(strict=True))
        if path.is_symlink():
            raise InvalidDomainValueError("artifact storage file cannot be a symbolic link")

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def _write_blob_once(self, path: Path, content: bytes) -> None:
        try:
            self._write_once(path, content)
        except FileExistsError:
            existing = path.read_bytes()
            if hashlib.sha256(existing).digest() != hashlib.sha256(content).digest():
                raise ArtifactIntegrityError("content-addressed blob collision detected") from None

    @staticmethod
    def _encode_metadata(artifact: Artifact) -> bytes:
        document = {
            "content_hash": artifact.content_hash.value,
            "content_schema_version": artifact.content_schema_version,
            "created_at": artifact.created_at.isoformat(),
            "encrypted": artifact.encrypted,
            "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
            "id": artifact.id.value,
            "incident_id": artifact.incident_id.value,
            "locator": artifact.locator,
            "media_type": artifact.media_type,
            "metadata_schema_version": artifact.metadata_schema_version,
            "redaction_status": artifact.redaction_status.value,
            "retention_class": artifact.retention_class.value,
            "size_bytes": artifact.size_bytes,
            "tenant_id": artifact.tenant_id.value,
        }
        return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _load_metadata(self, artifact_id: ArtifactId) -> Artifact:
        path = self._metadata_path(artifact_id)
        try:
            raw: Any = json.loads(path.read_bytes())
            if not isinstance(raw, dict):
                raise TypeError
            artifact = Artifact(
                id=ArtifactId(raw["id"]),
                tenant_id=TenantId(raw["tenant_id"]),
                incident_id=IncidentId(raw["incident_id"]),
                locator=raw["locator"],
                media_type=raw["media_type"],
                content_schema_version=raw["content_schema_version"],
                content_hash=Sha256Digest(raw["content_hash"]),
                size_bytes=raw["size_bytes"],
                retention_class=RetentionClass(raw["retention_class"]),
                created_at=datetime.fromisoformat(raw["created_at"]),
                expires_at=(
                    datetime.fromisoformat(raw["expires_at"])
                    if raw["expires_at"] is not None
                    else None
                ),
                redaction_status=RedactionStatus(raw["redaction_status"]),
                encrypted=raw["encrypted"],
                metadata_schema_version=raw["metadata_schema_version"],
            )
        except FileNotFoundError as error:
            raise ArtifactNotFoundError("artifact does not exist") from error
        except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise ArtifactIntegrityError("artifact metadata failed validation") from error
        if artifact.id != artifact_id:
            raise ArtifactIntegrityError("artifact metadata identity does not match its locator")
        return artifact
