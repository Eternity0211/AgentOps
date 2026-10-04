"""Deterministic validation, authorization, dispatch, retry, limit, and audit gateway."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from agentops_incident_commander.domain import (
    ActorId,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    IncidentId,
    Principal,
    RetryableToolError,
    SemanticVersion,
    Sha256Digest,
    ToolAccessClass,
    ToolCallId,
    ToolDefinition,
    ToolRegistry,
    WorkflowRunId,
    require_permission,
    utc_now,
)

TOOL_AUDIT_SCHEMA_VERSION = "tool-call/v1"
MAX_SCHEMA_DEPTH = 16
_ALLOWED_SCHEMA_KEYS = frozenset(
    {
        "additionalProperties",
        "const",
        "enum",
        "items",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "properties",
        "required",
        "type",
    }
)
_JSON_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})
_RAW_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_ABSOLUTE_PATH = re.compile(r"^(?:[a-z]:[\\/]|/)", re.IGNORECASE)
_SHELL_COMMAND = re.compile(
    r"^(?:bash|sh|zsh|cmd(?:\.exe)?|powershell(?:\.exe)?|pwsh)(?:\s|$)", re.IGNORECASE
)


class ToolGatewayError(RuntimeError):
    """A tool call was rejected or failed behind the deterministic gateway."""

    def __init__(self, code: str, detail: str, *, attempts: int = 0) -> None:
        super().__init__(detail)
        self.code = code
        self.attempts = attempts


class ToolPayloadValidationError(ToolGatewayError):
    """Input or output did not match its registered strict schema."""


class ToolSchemaConfigurationError(ToolGatewayError):
    """A registered schema uses unsupported or internally invalid constraints."""


class ToolResultLimitError(ToolGatewayError):
    """A valid adapter result exceeded its registered byte ceiling."""


class ToolAdapterFailure(RuntimeError):
    """A classified adapter dependency failure safe for retry policy evaluation."""

    def __init__(self, classification: RetryableToolError, detail: str) -> None:
        super().__init__(detail)
        self.classification = classification


@dataclass(frozen=True, slots=True)
class ToolAdapterContext:
    call_id: ToolCallId
    incident_id: IncidentId
    workflow_run_id: WorkflowRunId
    actor_id: ActorId
    correlation_id: CorrelationId
    causation_id: CausationId


class ToolAdapter(Protocol):
    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


class AuditWriter(Protocol):
    async def append(self, event: AuditEvent) -> object: ...


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
Sleeper = Callable[[float], Awaitable[None]]
ToolIdentity = tuple[str, SemanticVersion]


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ToolPayloadValidationError("PAYLOAD_NOT_JSON", "tool payload must be JSON") from exc


def _digest(value: object) -> Sha256Digest:
    return Sha256Digest(hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest())


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    call_id: ToolCallId
    tool_name: str
    tool_version: SemanticVersion
    incident_id: IncidentId
    workflow_run_id: WorkflowRunId
    principal: Principal
    correlation_id: CorrelationId
    causation_id: CausationId
    arguments_json: str

    def __post_init__(self) -> None:
        try:
            value = json.loads(self.arguments_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ToolPayloadValidationError(
                "PAYLOAD_NOT_JSON", "tool arguments must be canonical JSON"
            ) from exc
        if not isinstance(value, dict) or _canonical_json(value) != self.arguments_json:
            raise ToolPayloadValidationError(
                "PAYLOAD_NOT_CANONICAL", "tool arguments must be a canonical JSON object"
            )

    @classmethod
    def from_mapping(
        cls,
        *,
        call_id: ToolCallId,
        tool_name: str,
        tool_version: SemanticVersion,
        incident_id: IncidentId,
        workflow_run_id: WorkflowRunId,
        principal: Principal,
        correlation_id: CorrelationId,
        causation_id: CausationId,
        arguments: Mapping[str, Any],
    ) -> ToolCallRequest:
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            tool_version=tool_version,
            incident_id=incident_id,
            workflow_run_id=workflow_run_id,
            principal=principal,
            correlation_id=correlation_id,
            causation_id=causation_id,
            arguments_json=_canonical_json(arguments),
        )

    def arguments(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.arguments_json)
        return value

    @property
    def request_hash(self) -> Sha256Digest:
        return _digest(
            {
                "actor_id": self.principal.actor_id.value,
                "arguments": self.arguments(),
                "incident_id": self.incident_id.value,
                "tenant_id": self.principal.tenant_id.value,
                "tool_name": self.tool_name,
                "tool_version": self.tool_version.value,
                "workflow_run_id": self.workflow_run_id.value,
            }
        )


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    call_id: ToolCallId
    tool_name: str
    tool_version: SemanticVersion
    attempts: int
    result_json: str
    content_hash: Sha256Digest

    def result(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.result_json)
        return value


def _configuration_error(detail: str) -> ToolSchemaConfigurationError:
    return ToolSchemaConfigurationError("INVALID_TOOL_SCHEMA", detail)


def _check_schema(schema: object, *, path: str = "$", depth: int = 0) -> None:
    if depth > MAX_SCHEMA_DEPTH:
        raise _configuration_error("tool schema nesting exceeds the supported depth")
    if not isinstance(schema, dict):
        raise _configuration_error(f"{path} schema node must be an object")
    unknown = set(schema) - _ALLOWED_SCHEMA_KEYS
    if unknown:
        raise _configuration_error(f"{path} schema contains unsupported keywords")
    expected = schema.get("type")
    if expected not in _JSON_TYPES:
        raise _configuration_error(f"{path} schema type is unsupported")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise _configuration_error(f"{path} enum must be a non-empty array")
    if expected == "object":
        properties = schema.get("properties")
        required = schema.get("required", [])
        if not isinstance(properties, dict) or schema.get("additionalProperties") is not False:
            raise _configuration_error(f"{path} object schema must be strict")
        if not isinstance(required, list) or not set(required) <= set(properties):
            raise _configuration_error(f"{path} required fields are invalid")
        for name, child in properties.items():
            if not isinstance(name, str):
                raise _configuration_error(f"{path} property names must be strings")
            _check_schema(child, path=f"{path}.{name}", depth=depth + 1)
    elif expected == "array":
        if "items" not in schema:
            raise _configuration_error(f"{path} array schema requires items")
        _check_schema(schema["items"], path=f"{path}[]", depth=depth + 1)
        _check_integer_bounds(schema, "minItems", "maxItems", path)
    elif expected == "string":
        _check_integer_bounds(schema, "minLength", "maxLength", path)
        pattern = schema.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                raise _configuration_error(f"{path} pattern must be a string")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise _configuration_error(f"{path} pattern is invalid") from exc
    elif expected in {"integer", "number"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        for bound in (minimum, maximum):
            if bound is not None and (
                not isinstance(bound, (int, float))
                or isinstance(bound, bool)
                or not math.isfinite(bound)
            ):
                raise _configuration_error(f"{path} numeric bound is invalid")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise _configuration_error(f"{path} numeric bounds are reversed")


def _check_integer_bounds(
    schema: Mapping[str, Any], minimum_name: str, maximum_name: str, path: str
) -> None:
    minimum = schema.get(minimum_name, 0)
    maximum = schema.get(maximum_name)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        raise _configuration_error(f"{path} minimum size is invalid")
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < minimum
    ):
        raise _configuration_error(f"{path} maximum size is invalid")


def _validate_payload(schema: Mapping[str, Any], value: object, *, path: str = "$") -> None:
    expected = schema["type"]
    if not _matches_json_type(expected, value):
        raise ToolPayloadValidationError("SCHEMA_VALIDATION_FAILED", f"{path} has invalid type")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolPayloadValidationError("SCHEMA_VALIDATION_FAILED", f"{path} is not allowed")
    if "const" in schema and value != schema["const"]:
        raise ToolPayloadValidationError("SCHEMA_VALIDATION_FAILED", f"{path} is not constant")
    if expected == "object":
        assert isinstance(value, dict)
        properties = schema["properties"]
        missing = set(schema.get("required", [])) - set(value)
        unknown = set(value) - set(properties)
        if missing:
            raise ToolPayloadValidationError(
                "SCHEMA_VALIDATION_FAILED", f"{path} is missing required fields"
            )
        if unknown:
            raise ToolPayloadValidationError(
                "SCHEMA_VALIDATION_FAILED", f"{path} contains unknown fields"
            )
        for name, child in properties.items():
            if name in value:
                _validate_payload(child, value[name], path=f"{path}.{name}")
    elif expected == "array":
        assert isinstance(value, list)
        if len(value) < schema.get("minItems", 0) or (
            "maxItems" in schema and len(value) > schema["maxItems"]
        ):
            raise ToolPayloadValidationError(
                "SCHEMA_VALIDATION_FAILED", f"{path} has invalid item count"
            )
        for index, item in enumerate(value):
            _validate_payload(schema["items"], item, path=f"{path}[{index}]")
    elif expected == "string":
        assert isinstance(value, str)
        if len(value) < schema.get("minLength", 0) or (
            "maxLength" in schema and len(value) > schema["maxLength"]
        ):
            raise ToolPayloadValidationError(
                "SCHEMA_VALIDATION_FAILED", f"{path} has invalid length"
            )
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ToolPayloadValidationError(
                "SCHEMA_VALIDATION_FAILED", f"{path} has invalid format"
            )
    elif expected in {"integer", "number"}:
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        if ("minimum" in schema and value < schema["minimum"]) or (
            "maximum" in schema and value > schema["maximum"]
        ):
            raise ToolPayloadValidationError(
                "SCHEMA_VALIDATION_FAILED", f"{path} is outside the allowed range"
            )


def _matches_json_type(expected: str, value: object) -> bool:
    if expected == "array":
        return isinstance(value, list)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    if expected == "number":
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )
    if expected == "object":
        return isinstance(value, dict)
    return isinstance(value, str)


def _validate_diagnosis_arguments(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for name, child in value.items():
            _validate_diagnosis_arguments(child, path=f"{path}.{name}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_diagnosis_arguments(child, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    normalized = value.strip()
    if (
        _RAW_URL.match(normalized)
        or _ABSOLUTE_PATH.match(normalized)
        or "../" in normalized
        or "..\\" in normalized
        or _SHELL_COMMAND.match(normalized)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ToolPayloadValidationError(
            "DIAGNOSIS_UNSAFE_ARGUMENT",
            f"{path} contains a URL, path, command, or control character",
        )


class ToolGateway:
    """Execute only exact registered adapters behind deterministic controls."""

    def __init__(
        self,
        registry: ToolRegistry,
        adapters: Mapping[ToolIdentity, ToolAdapter],
        audit_writer: AuditWriter,
        *,
        clock: Clock = utc_now,
        audit_id_factory: IdFactory,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        enabled = {definition.identity: definition for definition in registry.catalog()}
        if set(adapters) != set(enabled):
            raise ToolSchemaConfigurationError(
                "ADAPTER_REGISTRATION_MISMATCH",
                "enabled tool definitions and adapters must match exactly",
            )
        for definition in enabled.values():
            _check_schema(definition.input_schema.as_dict())
            _check_schema(definition.output_schema.as_dict())
        self._registry = registry
        self._adapters = dict(adapters)
        self._audit_writer = audit_writer
        self._clock = clock
        self._audit_id_factory = audit_id_factory
        self._sleeper = sleeper

    def diagnosis_catalog(self) -> tuple[ToolDefinition, ...]:
        return self._registry.catalog(access_class=ToolAccessClass.READ)

    async def invoke(self, call: ToolCallRequest) -> ToolCallResult:
        return await self._invoke(call, diagnosis=False)

    async def invoke_diagnosis(self, call: ToolCallRequest) -> ToolCallResult:
        return await self._invoke(call, diagnosis=True)

    async def _invoke(self, call: ToolCallRequest, *, diagnosis: bool) -> ToolCallResult:
        request_hash = call.request_hash
        try:
            definition = self._registry.resolve(call.tool_name, call.tool_version)
            if diagnosis and definition.access_class is not ToolAccessClass.READ:
                raise ToolPayloadValidationError(
                    "DIAGNOSIS_WRITE_TOOL_FORBIDDEN",
                    "diagnosis can invoke read-only tools only",
                )
            require_permission(
                call.principal,
                definition.required_permission,
                tenant_id=call.principal.tenant_id,
            )
            if len(call.arguments_json.encode("utf-8")) > definition.max_input_bytes:
                raise ToolPayloadValidationError(
                    "INPUT_LIMIT_EXCEEDED", "tool input exceeds its registered byte limit"
                )
            _validate_payload(definition.input_schema.as_dict(), call.arguments())
            if diagnosis:
                _validate_diagnosis_arguments(call.arguments())
        except Exception as exc:
            await self._audit(
                call,
                "tool.call_rejected",
                request_hash=request_hash,
                result_hash=_digest({"error": type(exc).__name__}),
            )
            raise

        await self._audit(
            call,
            f"{definition.audit.event_type}_started",
            request_hash=request_hash,
            result_hash=None,
        )
        context = ToolAdapterContext(
            call_id=call.call_id,
            incident_id=call.incident_id,
            workflow_run_id=call.workflow_run_id,
            actor_id=call.principal.actor_id,
            correlation_id=call.correlation_id,
            causation_id=call.causation_id,
        )
        attempts = 0
        while attempts < definition.retry_policy.max_attempts:
            attempts += 1
            try:
                raw_result = await asyncio.wait_for(
                    self._adapters[definition.identity].invoke(context, call.arguments()),
                    timeout=definition.timeout_ms / 1000,
                )
                result_json = _canonical_json(raw_result)
                result = json.loads(result_json)
                if not isinstance(result, dict):
                    raise ToolPayloadValidationError(
                        "OUTPUT_NOT_OBJECT", "tool output must be a JSON object", attempts=attempts
                    )
                _validate_payload(definition.output_schema.as_dict(), result)
                if len(result_json.encode("utf-8")) > definition.max_result_bytes:
                    raise ToolResultLimitError(
                        "RESULT_LIMIT_EXCEEDED",
                        "tool result exceeds its registered byte limit",
                        attempts=attempts,
                    )
            except asyncio.CancelledError:
                await self._audit_failure(call, request_hash, "CANCELLED", attempts, definition)
                raise
            except TimeoutError:
                classification = RetryableToolError.TIMEOUT
                failure: Exception = ToolGatewayError(
                    "TOOL_TIMEOUT", "tool adapter exceeded its timeout", attempts=attempts
                )
            except ToolAdapterFailure as exc:
                classification = exc.classification
                failure = ToolGatewayError(
                    f"ADAPTER_{classification.value}",
                    "tool adapter reported a classified dependency failure",
                    attempts=attempts,
                )
            except ToolGatewayError as exc:
                if exc.attempts == 0:
                    exc.attempts = attempts
                await self._audit_failure(call, request_hash, exc.code, attempts, definition)
                raise
            except Exception as exc:
                failure = ToolGatewayError(
                    "TOOL_ADAPTER_FAILED", "tool adapter failed", attempts=attempts
                )
                classification = None
                failure.__cause__ = exc
            else:
                result_hash = Sha256Digest(hashlib.sha256(result_json.encode("utf-8")).hexdigest())
                await self._audit(
                    call,
                    f"{definition.audit.event_type}_succeeded",
                    request_hash=request_hash,
                    result_hash=result_hash,
                )
                return ToolCallResult(
                    call_id=call.call_id,
                    tool_name=definition.name,
                    tool_version=definition.semantic_version,
                    attempts=attempts,
                    result_json=result_json,
                    content_hash=result_hash,
                )

            retryable = (
                classification is not None
                and classification in definition.retry_policy.retryable_errors
                and attempts < definition.retry_policy.max_attempts
            )
            if retryable:
                delay_ms = min(
                    definition.retry_policy.initial_backoff_ms * (2 ** (attempts - 1)),
                    definition.retry_policy.max_backoff_ms,
                )
                await self._sleeper(delay_ms / 1000)
                continue
            assert isinstance(failure, ToolGatewayError)
            await self._audit_failure(call, request_hash, failure.code, attempts, definition)
            raise failure
        raise AssertionError(
            "bounded tool loop exhausted without a terminal result"
        )  # pragma: no cover

    async def _audit_failure(
        self,
        call: ToolCallRequest,
        request_hash: Sha256Digest,
        code: str,
        attempts: int,
        definition: ToolDefinition,
    ) -> None:
        await self._audit(
            call,
            f"{definition.audit.event_type}_failed",
            request_hash=request_hash,
            result_hash=_digest({"attempts": attempts, "error": code}),
        )

    async def _audit(
        self,
        call: ToolCallRequest,
        event_type: str,
        *,
        request_hash: Sha256Digest,
        result_hash: Sha256Digest | None,
    ) -> None:
        await self._audit_writer.append(
            AuditEvent(
                id=AuditEventId(self._audit_id_factory()),
                tenant_id=call.principal.tenant_id,
                type=event_type,
                event_version=1,
                payload_schema_version=TOOL_AUDIT_SCHEMA_VERSION,
                actor_id=call.principal.actor_id,
                correlation_id=call.correlation_id,
                causation_id=call.causation_id,
                target=AuditTarget("tool.call", call.call_id),
                occurred_at=self._clock(),
                request_hash=request_hash,
                result_hash=result_hash,
            )
        )
