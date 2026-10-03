"""Deterministic error-log pattern clustering with raw Artifact references."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from .errors import InvalidDomainValueError
from .values import ArtifactId, Sha256Digest, as_utc

LOG_PATTERN_SCHEMA_VERSION: Final = "1.0.0"
MAX_LOG_EVENTS: Final = 1_000
_ERROR_SEVERITIES = frozenset({"ERROR", "FATAL", "CRITICAL"})
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\w.])")
_HEX = re.compile(r"\b(?:0x[0-9a-fA-F]+|[0-9a-fA-F]{12,})\b")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
_WHITESPACE = re.compile(r"\s+")


def _text(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise InvalidDomainValueError(f"log {field} must be bounded non-null text")
    return normalized


@dataclass(frozen=True, slots=True, order=True)
class ArtifactRecordReference:
    """Resolvable position of one raw log record inside an immutable Artifact."""

    artifact_id: ArtifactId
    record_index: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.record_index, int)
            or isinstance(self.record_index, bool)
            or self.record_index < 0
            or self.record_index >= MAX_LOG_EVENTS
        ):
            raise InvalidDomainValueError("log Artifact record index is outside collector bounds")


@dataclass(frozen=True, slots=True)
class LogErrorEvent:
    reference: ArtifactRecordReference
    observed_at: datetime
    service: str
    severity: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))
        object.__setattr__(self, "service", _text(self.service, field="service", maximum=128))
        object.__setattr__(
            self,
            "severity",
            _text(self.severity, field="severity", maximum=32).upper(),
        )
        object.__setattr__(self, "message", _text(self.message, field="message", maximum=4_096))

    @property
    def is_error(self) -> bool:
        return self.severity in _ERROR_SEVERITIES


@dataclass(frozen=True, slots=True)
class LogErrorPattern:
    fingerprint: Sha256Digest
    template: str
    count: int
    first_observed_at: datetime
    last_observed_at: datetime
    services: tuple[str, ...]
    severities: tuple[str, ...]
    raw_references: tuple[ArtifactRecordReference, ...]
    schema_version: str = LOG_PATTERN_SCHEMA_VERSION


def normalize_log_template(message: str) -> str:
    """Remove common volatile values without interpreting untrusted log text."""
    value = _text(message, field="message", maximum=4_096).lower()
    value = _UUID.sub("<uuid>", value)
    value = _IPV4.sub("<ip>", value)
    value = _HEX.sub("<hex>", value)
    value = _NUMBER.sub("<num>", value)
    value = _WHITESPACE.sub(" ", value).strip()
    if len(value) > 512:
        value = value[:512]
    return value


def cluster_log_errors(events: tuple[LogErrorEvent, ...]) -> tuple[LogErrorPattern, ...]:
    """Group error records by stable template while retaining every raw reference."""
    if len(events) > MAX_LOG_EVENTS:
        raise InvalidDomainValueError("log clustering event limit exceeded")
    groups: dict[str, list[LogErrorEvent]] = {}
    seen_references: set[ArtifactRecordReference] = set()
    for event in events:
        if event.reference in seen_references:
            raise InvalidDomainValueError("log clustering references must be unique")
        seen_references.add(event.reference)
        if event.is_error:
            groups.setdefault(normalize_log_template(event.message), []).append(event)

    patterns: list[LogErrorPattern] = []
    for template, members in groups.items():
        ordered = sorted(members, key=lambda item: (item.observed_at, item.reference))
        patterns.append(
            LogErrorPattern(
                fingerprint=Sha256Digest(hashlib.sha256(template.encode("utf-8")).hexdigest()),
                template=template,
                count=len(ordered),
                first_observed_at=ordered[0].observed_at,
                last_observed_at=ordered[-1].observed_at,
                services=tuple(sorted({item.service for item in ordered})),
                severities=tuple(sorted({item.severity for item in ordered})),
                raw_references=tuple(item.reference for item in ordered),
            )
        )
    return tuple(sorted(patterns, key=lambda item: (-item.count, item.fingerprint.value)))
