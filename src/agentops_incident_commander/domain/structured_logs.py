"""Versioned, bounded, secret-safe structured telemetry log records."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .redaction import REDACTION_MARKER

STRUCTURED_LOG_SCHEMA_VERSION: Final = "1.0.0"
MAX_STRUCTURED_LOG_ATTRIBUTES: Final = 40
MAX_STRUCTURED_LOG_ATTRIBUTE_BYTES: Final = 256
MAX_STRUCTURED_LOG_RECORD_BYTES: Final = 4_096

type StructuredLogScalar = str | int | float | bool


class StructuredLogSeverity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class StructuredLogEvent(StrEnum):
    HTTP_REQUEST = "http_request"
    HTTP_CLIENT_REQUEST = "http_client_request"
    DEPENDENCY_OPERATION = "dependency_operation"
    DEPENDENCY_POOL_ACQUIRE_TIMEOUT = "dependency_pool_acquire_timeout"
    DEPENDENCY_TIMEOUT = "dependency_timeout"
    DEPENDENCY_TELEMETRY_FAILED = "dependency_telemetry_failed"
    SERVICE_DEPLOYMENT_CHANGED = "service.deployment.changed"
    DEPLOYMENT_OBSERVER_FAILED = "deployment_observer_failed"
    MEMORY_RETENTION = "memory_retention"
    TELEMETRY_SHUTDOWN_TIMEOUT = "telemetry_shutdown_timeout"
    TELEMETRY_INITIALIZATION_FAILED = "telemetry_initialization_failed"
    CONTROL_PLANE_OPERATION = "control_plane.operation"
    CONTROL_PLANE_OBSERVATION_FAILED = "control_plane_observation_failed"
    CHECKPOINT_OBSERVATION_DROPPED = "checkpoint_observation_dropped"
    CONTROL_PLANE_OBSERVER_SHUTDOWN_FAILED = "control_plane_observer_shutdown_failed"
    CONTROL_PLANE_TELEMETRY_SHUTDOWN_TIMEOUT = "control_plane_telemetry_shutdown_timeout"
    CONTROL_PLANE_TELEMETRY_INITIALIZATION_FAILED = "control_plane_telemetry_initialization_failed"
    PAYLOAD_REFUSED = "structured_log.payload_refused"


class StructuredLogRejection(StrEnum):
    INVALID_EVENT = "INVALID_EVENT"
    INVALID_SEVERITY = "INVALID_SEVERITY"
    INVALID_ATTRIBUTES = "INVALID_ATTRIBUTES"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    TOO_MANY_ATTRIBUTES = "TOO_MANY_ATTRIBUTES"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    SENSITIVE_FIELD = "SENSITIVE_FIELD"
    INVALID_VALUE = "INVALID_VALUE"
    RECORD_TOO_LARGE = "RECORD_TOO_LARGE"


class StructuredLogError(ValueError):
    """A content-free rejection with a stable reason code."""

    def __init__(self, reason: StructuredLogRejection) -> None:
        self.reason = reason
        super().__init__(reason.value)


_COMMON_FIELDS: Final = frozenset(
    {
        "agentops.correlation_id",
        "agentops.log.dropped_attributes",
        "agentops.log.redacted",
        "agentops.log.truncated",
        "duration_ms",
        "service.name",
    }
)
_EVENT_FIELDS: Final[dict[StructuredLogEvent, frozenset[str]]] = {
    StructuredLogEvent.HTTP_REQUEST: frozenset(
        {
            "http.request.method",
            "http.response.status_code",
            "http.route",
        }
    ),
    StructuredLogEvent.HTTP_CLIENT_REQUEST: frozenset(
        {
            "error.type",
            "http.request.method",
            "http.response.status_code",
            "http.route",
            "request.result",
            "server.address",
        }
    ),
    StructuredLogEvent.DEPENDENCY_OPERATION: frozenset({"dependency", "operation", "result"}),
    StructuredLogEvent.DEPENDENCY_POOL_ACQUIRE_TIMEOUT: frozenset(
        {"dependency", "pool_idle", "pool_size"}
    ),
    StructuredLogEvent.DEPENDENCY_TIMEOUT: frozenset({"dependency", "operation", "timeout_ms"}),
    StructuredLogEvent.DEPENDENCY_TELEMETRY_FAILED: frozenset({"dependency", "operation"}),
    StructuredLogEvent.SERVICE_DEPLOYMENT_CHANGED: frozenset(
        {
            "deployment.environment",
            "deployment.id",
            "event.observed_at",
            "event.schema.version",
            "service.previous_version",
            "service.version",
        }
    ),
    StructuredLogEvent.DEPLOYMENT_OBSERVER_FAILED: frozenset({"deployment.id"}),
    StructuredLogEvent.MEMORY_RETENTION: frozenset(
        {
            "process.memory.retained_bytes",
            "process.memory.retention_allocations",
            "process.memory.retention_limit_bytes",
        }
    ),
    StructuredLogEvent.TELEMETRY_SHUTDOWN_TIMEOUT: frozenset(),
    StructuredLogEvent.TELEMETRY_INITIALIZATION_FAILED: frozenset(),
    StructuredLogEvent.CONTROL_PLANE_OPERATION: frozenset(
        {
            "agentops.attempt",
            "agentops.causation_id",
            "agentops.component",
            "agentops.duration_ms",
            "agentops.incident_id",
            "agentops.max_attempts",
            "agentops.model.cost_currency",
            "agentops.model.cost_nanounits",
            "agentops.model.cost_source",
            "agentops.model.metering_unavailable",
            "agentops.model.rate_card_version",
            "agentops.operation",
            "agentops.operation_id",
            "agentops.outcome",
            "agentops.result_code",
            "agentops.route",
            "agentops.schema.version",
            "agentops.subject.name",
            "agentops.subject.version",
            "agentops.tenant_id",
            "agentops.workflow_run_id",
            "gen_ai.usage.cached_input_tokens",
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.output_tokens",
            "gen_ai.usage.reasoning_tokens",
            "gen_ai.usage.total_tokens",
        }
    ),
    StructuredLogEvent.CONTROL_PLANE_OBSERVATION_FAILED: frozenset(
        {"agentops.component", "agentops.operation"}
    ),
    StructuredLogEvent.CHECKPOINT_OBSERVATION_DROPPED: frozenset({"agentops.operation"}),
    StructuredLogEvent.CONTROL_PLANE_OBSERVER_SHUTDOWN_FAILED: frozenset({"process.role"}),
    StructuredLogEvent.CONTROL_PLANE_TELEMETRY_SHUTDOWN_TIMEOUT: frozenset(),
    StructuredLogEvent.CONTROL_PLANE_TELEMETRY_INITIALIZATION_FAILED: frozenset(),
    StructuredLogEvent.PAYLOAD_REFUSED: frozenset({"rejected.event", "rejection.reason"}),
}
_IDENTITY_FIELDS: Final = frozenset(
    {
        "agentops.causation_id",
        "agentops.correlation_id",
        "agentops.incident_id",
        "agentops.operation_id",
        "agentops.tenant_id",
        "agentops.workflow_run_id",
        "service.name",
    }
)
_SENSITIVE_FIELDS: Final = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "cookie",
        "passwd",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "set_cookie",
        "token",
    }
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.DOTALL,
)
_AUTHORIZATION = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_TOKEN_PREFIX = re.compile(r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{8,}")
_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|cookie)\s*[:=]\s*[^\s,;]+"
)
_URI_CREDENTIALS = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


def _normalize_field(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(".", "_")


def _truncate_utf8(value: str, maximum: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum:
        return value, False
    marker = "…"
    budget = maximum - len(marker.encode("utf-8"))
    if budget <= 0:
        return "", True
    prefix = encoded[:budget]
    while prefix:
        try:
            return prefix.decode("utf-8") + marker, True
        except UnicodeDecodeError:
            prefix = prefix[:-1]
    return marker, True  # pragma: no cover - a positive UTF-8 prefix always reaches a boundary


def _redact_text(value: str) -> tuple[str, bool]:
    redacted = value
    count = 0
    for pattern in (
        _PRIVATE_KEY,
        _AUTHORIZATION,
        _TOKEN_PREFIX,
        _ASSIGNMENT,
        _URI_CREDENTIALS,
    ):
        redacted, replacements = pattern.subn(REDACTION_MARKER, redacted)
        count += replacements
    redacted = _CONTROL_CHARACTER.sub(" ", redacted)
    return redacted, count > 0


def sanitize_structured_log_scalar(
    value: object,
) -> tuple[StructuredLogScalar, bool, bool]:
    """Return a scalar plus redaction/truncation flags; reject containers and non-finite data."""
    if isinstance(value, bool | int):
        return value, False, False
    if isinstance(value, float):
        if not math.isfinite(value):
            raise StructuredLogError(StructuredLogRejection.INVALID_VALUE)
        return value, False, False
    if not isinstance(value, str):
        raise StructuredLogError(StructuredLogRejection.INVALID_VALUE)
    redacted, was_redacted = _redact_text(value)
    bounded, was_truncated = _truncate_utf8(redacted, MAX_STRUCTURED_LOG_ATTRIBUTE_BYTES)
    return bounded, was_redacted, was_truncated


@dataclass(frozen=True, slots=True)
class StructuredLogRecord:
    event: StructuredLogEvent
    severity: StructuredLogSeverity
    attributes: Mapping[str, StructuredLogScalar]
    schema_version: str = STRUCTURED_LOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.event, StructuredLogEvent):
            raise StructuredLogError(StructuredLogRejection.INVALID_EVENT)
        if not isinstance(self.severity, StructuredLogSeverity):
            raise StructuredLogError(StructuredLogRejection.INVALID_SEVERITY)
        if self.schema_version != STRUCTURED_LOG_SCHEMA_VERSION:
            raise StructuredLogError(StructuredLogRejection.UNSUPPORTED_SCHEMA)
        if not isinstance(self.attributes, Mapping):
            raise StructuredLogError(StructuredLogRejection.INVALID_ATTRIBUTES)
        if len(self.attributes) > MAX_STRUCTURED_LOG_ATTRIBUTES:
            raise StructuredLogError(StructuredLogRejection.TOO_MANY_ATTRIBUTES)
        allowed = _COMMON_FIELDS | _EVENT_FIELDS[self.event]
        frozen: dict[str, StructuredLogScalar] = {}
        for key, value in self.attributes.items():
            if not isinstance(key, str) or key not in allowed:
                raise StructuredLogError(StructuredLogRejection.UNKNOWN_FIELD)
            clean, redacted, truncated = sanitize_structured_log_scalar(value)
            if clean != value or redacted or truncated:
                raise StructuredLogError(StructuredLogRejection.INVALID_VALUE)
            frozen[key] = clean
        if _record_size(self.event, self.severity, frozen) > MAX_STRUCTURED_LOG_RECORD_BYTES:
            raise StructuredLogError(StructuredLogRejection.RECORD_TOO_LARGE)
        object.__setattr__(self, "attributes", MappingProxyType(frozen))

    def as_dict(self) -> dict[str, StructuredLogScalar]:
        return {
            "log.schema.version": self.schema_version,
            "event.name": self.event.value,
            "severity.text": self.severity.value,
            **dict(self.attributes),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def utf8_size(self) -> int:
        return len(self.to_json().encode("utf-8"))


def _record_size(
    event: StructuredLogEvent,
    severity: StructuredLogSeverity,
    attributes: Mapping[str, StructuredLogScalar],
) -> int:
    return len(
        json.dumps(
            {
                "log.schema.version": STRUCTURED_LOG_SCHEMA_VERSION,
                "event.name": event.value,
                "severity.text": severity.value,
                **attributes,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def build_structured_log_record(
    event: StructuredLogEvent,
    severity: StructuredLogSeverity,
    attributes: Mapping[str, object],
) -> StructuredLogRecord:
    """Validate, redact, and deterministically bound one closed-schema record."""
    if not isinstance(event, StructuredLogEvent):
        raise StructuredLogError(StructuredLogRejection.INVALID_EVENT)
    if not isinstance(severity, StructuredLogSeverity):
        raise StructuredLogError(StructuredLogRejection.INVALID_SEVERITY)
    if not isinstance(attributes, Mapping):
        raise StructuredLogError(StructuredLogRejection.INVALID_ATTRIBUTES)
    if len(attributes) > MAX_STRUCTURED_LOG_ATTRIBUTES:
        raise StructuredLogError(StructuredLogRejection.TOO_MANY_ATTRIBUTES)

    allowed = _COMMON_FIELDS | _EVENT_FIELDS[event]
    sanitized: dict[str, StructuredLogScalar] = {}
    was_redacted = False
    was_truncated = False
    for key in sorted(attributes):
        if not isinstance(key, str):
            raise StructuredLogError(StructuredLogRejection.UNKNOWN_FIELD)
        if key == "event.name":
            if attributes[key] != event.value:
                raise StructuredLogError(StructuredLogRejection.INVALID_VALUE)
            continue
        if _normalize_field(key) in _SENSITIVE_FIELDS:
            raise StructuredLogError(StructuredLogRejection.SENSITIVE_FIELD)
        if key not in allowed or key.startswith("agentops.log."):
            raise StructuredLogError(StructuredLogRejection.UNKNOWN_FIELD)
        clean, redacted, truncated = sanitize_structured_log_scalar(attributes[key])
        sanitized[key] = clean
        was_redacted = was_redacted or redacted
        was_truncated = was_truncated or truncated

    if was_redacted:
        sanitized["agentops.log.redacted"] = True
    if was_truncated:
        sanitized["agentops.log.truncated"] = True

    dropped = 0
    while _record_size(event, severity, sanitized) > MAX_STRUCTURED_LOG_RECORD_BYTES:
        candidates = sorted(key for key in sanitized if key not in _IDENTITY_FIELDS)
        candidates = [key for key in candidates if not key.startswith("agentops.log.")]
        if not candidates:
            raise StructuredLogError(StructuredLogRejection.RECORD_TOO_LARGE)
        del sanitized[candidates[-1]]
        dropped += 1
        sanitized["agentops.log.truncated"] = True
        sanitized["agentops.log.dropped_attributes"] = dropped

    return StructuredLogRecord(event=event, severity=severity, attributes=sanitized)


def safe_structured_log_record(
    event: StructuredLogEvent,
    severity: StructuredLogSeverity,
    attributes: Mapping[str, object],
) -> StructuredLogRecord:
    """Return a content-free refusal record when an untrusted record violates the contract."""
    try:
        return build_structured_log_record(event, severity, attributes)
    except StructuredLogError as error:
        rejected_event = event.value if isinstance(event, StructuredLogEvent) else "UNRECOGNIZED"
        return build_structured_log_record(
            StructuredLogEvent.PAYLOAD_REFUSED,
            StructuredLogSeverity.WARN,
            {
                "rejected.event": rejected_event,
                "rejection.reason": error.reason.value,
            },
        )
