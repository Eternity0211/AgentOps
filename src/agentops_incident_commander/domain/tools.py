"""Immutable versioned tool definitions and fail-closed registry selection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import total_ordering
from types import MappingProxyType
from typing import Any

from .auth import Permission
from .errors import InvalidDomainValueError, ToolNotFoundError, ToolVersionDisabledError

MAX_TOOL_SCHEMA_BYTES = 64 * 1024
MAX_TOOL_RESULT_BYTES = 16 * 1024 * 1024
MAX_TOOL_TIMEOUT_MS = 300_000
MAX_TOOL_ATTEMPTS = 5

_SEMANTIC_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_AUDIT_EVENT = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9_]+)+$")


@total_ordering
@dataclass(frozen=True, slots=True)
class SemanticVersion:
    """A deliberately strict release version with deterministic ordering."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _SEMANTIC_VERSION.fullmatch(self.value) is None:
            raise InvalidDomainValueError("tool semantic version must be MAJOR.MINOR.PATCH")

    @property
    def parts(self) -> tuple[int, int, int]:
        major, minor, patch = self.value.split(".")
        return (int(major), int(minor), int(patch))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return self.parts < other.parts

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ToolSchema:
    """Canonical strict JSON Schema retained without a mutable dictionary escape."""

    version: SemanticVersion
    canonical_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.version, SemanticVersion):
            raise InvalidDomainValueError("tool schema version must be semantic")
        if not isinstance(self.canonical_json, str):
            raise InvalidDomainValueError("tool schema must be canonical JSON text")
        if len(self.canonical_json.encode("utf-8")) > MAX_TOOL_SCHEMA_BYTES:
            raise InvalidDomainValueError("tool schema exceeds the byte limit")
        try:
            document = json.loads(self.canonical_json)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise InvalidDomainValueError("tool schema must be valid JSON") from exc
        if not isinstance(document, dict):
            raise InvalidDomainValueError("tool schema root must be an object")
        try:
            canonical = json.dumps(
                document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except ValueError as exc:
            raise InvalidDomainValueError("tool schema must contain JSON values") from exc
        if canonical != self.canonical_json:
            raise InvalidDomainValueError("tool schema JSON must be canonical")
        if document.get("type") != "object" or document.get("additionalProperties") is not False:
            raise InvalidDomainValueError(
                "tool schema must be a strict object with additional properties disabled"
            )
        properties = document.get("properties")
        if not isinstance(properties, dict):
            raise InvalidDomainValueError("tool schema must declare object properties")
        required = document.get("required", [])
        if (
            not isinstance(required, list)
            or any(not isinstance(value, str) for value in required)
            or not set(required) <= set(properties)
        ):
            raise InvalidDomainValueError(
                "tool schema required fields must name declared properties"
            )

    @classmethod
    def from_mapping(cls, version: SemanticVersion, document: Mapping[str, Any]) -> ToolSchema:
        try:
            canonical = json.dumps(
                document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise InvalidDomainValueError("tool schema must contain JSON values") from exc
        return cls(version, canonical)

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.canonical_json)
        return value

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    def is_compatible_with(self, previous: object) -> bool:
        """Conservatively allow direct reuse only for an unchanged same-major schema."""
        if not isinstance(previous, ToolSchema):
            return False
        return (
            self.version.parts[0] == previous.version.parts[0]
            and self.content_hash == previous.content_hash
        )


class ToolAccessClass(StrEnum):
    READ = "READ"
    WRITE = "WRITE"


class ToolRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RetryableToolError(StrEnum):
    TIMEOUT = "TIMEOUT"
    CONNECTION = "CONNECTION"
    RATE_LIMIT = "RATE_LIMIT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


class ToolIdempotency(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REQUIRED_RESULT_REPLAY = "REQUIRED_RESULT_REPLAY"


class ToolAuditMode(StrEnum):
    REQUEST_AND_RESULT_HASHES = "REQUEST_AND_RESULT_HASHES"


@dataclass(frozen=True, slots=True)
class ToolRetryPolicy:
    """Finite retry contract; max attempts includes the initial call."""

    max_attempts: int
    initial_backoff_ms: int
    max_backoff_ms: int
    retryable_errors: frozenset[RetryableToolError]

    def __post_init__(self) -> None:
        for name, value in (
            ("max attempts", self.max_attempts),
            ("initial backoff", self.initial_backoff_ms),
            ("maximum backoff", self.max_backoff_ms),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise InvalidDomainValueError(f"tool retry {name} must be an integer")
        if not 1 <= self.max_attempts <= MAX_TOOL_ATTEMPTS:
            raise InvalidDomainValueError("tool retry attempts are outside the bounded range")
        if (
            self.initial_backoff_ms < 0
            or self.max_backoff_ms < self.initial_backoff_ms
            or self.max_backoff_ms > MAX_TOOL_TIMEOUT_MS
        ):
            raise InvalidDomainValueError("tool retry backoff range is invalid")
        if not isinstance(self.retryable_errors, frozenset) or any(
            not isinstance(value, RetryableToolError) for value in self.retryable_errors
        ):
            raise InvalidDomainValueError("tool retry error classes are invalid")
        if self.max_attempts == 1 and (
            self.initial_backoff_ms != 0 or self.max_backoff_ms != 0 or self.retryable_errors
        ):
            raise InvalidDomainValueError("single-attempt tools cannot declare retry behavior")
        if self.max_attempts > 1 and not self.retryable_errors:
            raise InvalidDomainValueError("retried tools must classify retryable errors")


@dataclass(frozen=True, slots=True)
class ToolAuditPolicy:
    """Required append-only audit identity for every gateway call."""

    event_type: str
    schema_version: SemanticVersion
    mode: ToolAuditMode = ToolAuditMode.REQUEST_AND_RESULT_HASHES

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, str) or _AUDIT_EVENT.fullmatch(self.event_type) is None:
            raise InvalidDomainValueError("tool audit event type is invalid")
        if not isinstance(self.schema_version, SemanticVersion):
            raise InvalidDomainValueError("tool audit schema version must be semantic")
        if self.mode is not ToolAuditMode.REQUEST_AND_RESULT_HASHES:
            raise InvalidDomainValueError("tool audit must retain request and result hashes")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """One exact server-owned tool contract version."""

    name: str
    semantic_version: SemanticVersion
    input_schema: ToolSchema
    output_schema: ToolSchema
    access_class: ToolAccessClass
    risk: ToolRisk
    required_permission: Permission
    timeout_ms: int
    retry_policy: ToolRetryPolicy
    idempotency: ToolIdempotency
    audit: ToolAuditPolicy
    max_input_bytes: int
    max_result_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _TOOL_NAME.fullmatch(self.name) is None:
            raise InvalidDomainValueError("tool name must be lower snake case")
        expected_types = (
            (self.semantic_version, SemanticVersion),
            (self.input_schema, ToolSchema),
            (self.output_schema, ToolSchema),
            (self.access_class, ToolAccessClass),
            (self.risk, ToolRisk),
            (self.required_permission, Permission),
            (self.retry_policy, ToolRetryPolicy),
            (self.idempotency, ToolIdempotency),
            (self.audit, ToolAuditPolicy),
        )
        if any(not isinstance(value, expected) for value, expected in expected_types):
            raise InvalidDomainValueError("tool definition contains invalid typed metadata")
        for name, value, maximum in (
            ("timeout", self.timeout_ms, MAX_TOOL_TIMEOUT_MS),
            ("input byte limit", self.max_input_bytes, MAX_TOOL_RESULT_BYTES),
            ("result byte limit", self.max_result_bytes, MAX_TOOL_RESULT_BYTES),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise InvalidDomainValueError(f"tool {name} must be an integer")
            if not 1 <= value <= maximum:
                raise InvalidDomainValueError(f"tool {name} is outside the bounded range")
        if self.access_class is ToolAccessClass.READ:
            if self.idempotency is not ToolIdempotency.NOT_APPLICABLE:
                raise InvalidDomainValueError("read tools cannot require write idempotency")
        elif self.idempotency is not ToolIdempotency.REQUIRED_RESULT_REPLAY:
            raise InvalidDomainValueError("write tools require idempotent result replay")
        if self.retry_policy.max_backoff_ms > self.timeout_ms:
            raise InvalidDomainValueError("tool retry backoff cannot exceed its timeout")

    @property
    def identity(self) -> tuple[str, SemanticVersion]:
        return (self.name, self.semantic_version)


@dataclass(frozen=True, slots=True)
class ToolVersionRange:
    minimum: SemanticVersion
    maximum: SemanticVersion

    def __post_init__(self) -> None:
        if not isinstance(self.minimum, SemanticVersion) or not isinstance(
            self.maximum, SemanticVersion
        ):
            raise InvalidDomainValueError("tool version range bounds must be semantic")
        if self.maximum < self.minimum:
            raise InvalidDomainValueError("enabled tool version range is reversed")

    def includes(self, version: SemanticVersion) -> bool:
        return self.minimum <= version <= self.maximum


class ToolRegistry:
    """Resolve only registered definitions inside server-enabled version ranges."""

    def __init__(
        self,
        definitions: tuple[ToolDefinition, ...],
        *,
        enabled_ranges: Mapping[str, ToolVersionRange] | None = None,
    ) -> None:
        if not isinstance(definitions, tuple) or not definitions:
            raise InvalidDomainValueError("tool registry requires at least one definition")
        by_identity: dict[tuple[str, SemanticVersion], ToolDefinition] = {}
        versions_by_name: dict[str, list[SemanticVersion]] = {}
        for definition in definitions:
            if not isinstance(definition, ToolDefinition):
                raise InvalidDomainValueError("tool registry entries must be definitions")
            if definition.identity in by_identity:
                raise InvalidDomainValueError("tool registry contains a duplicate definition")
            by_identity[definition.identity] = definition
            versions_by_name.setdefault(definition.name, []).append(definition.semantic_version)
        if enabled_ranges is None:
            ranges = {
                name: ToolVersionRange(min(versions), max(versions))
                for name, versions in versions_by_name.items()
            }
        else:
            ranges = dict(enabled_ranges)
            if not set(ranges) <= set(versions_by_name):
                raise InvalidDomainValueError("enabled range names must be registered tools")
            for name, version_range in ranges.items():
                if not isinstance(version_range, ToolVersionRange):
                    raise InvalidDomainValueError("enabled tool ranges are invalid")
                if not any(version_range.includes(version) for version in versions_by_name[name]):
                    raise InvalidDomainValueError(
                        "enabled tool range must include a registered version"
                    )
        self._definitions = MappingProxyType(by_identity)
        self._enabled_ranges = MappingProxyType(ranges)

    def resolve(self, name: str, version: SemanticVersion) -> ToolDefinition:
        definition = self._definitions.get((name, version))
        if definition is None:
            raise ToolNotFoundError("requested tool name and version are not registered")
        enabled = self._enabled_ranges.get(name)
        if enabled is None or not enabled.includes(version):
            raise ToolVersionDisabledError("requested tool version is disabled")
        return definition

    def catalog(self, *, access_class: ToolAccessClass | None = None) -> tuple[ToolDefinition, ...]:
        visible = (
            definition
            for definition in self._definitions.values()
            if (enabled := self._enabled_ranges.get(definition.name)) is not None
            and enabled.includes(definition.semantic_version)
            and (access_class is None or definition.access_class is access_class)
        )
        return tuple(
            sorted(
                visible,
                key=lambda definition: (definition.name, definition.semantic_version.parts),
            )
        )
