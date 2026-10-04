"""Deterministic sensitive-data redaction with non-reversible transformation lineage."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .artifacts import RedactionStatus
from .errors import InvalidDomainValueError
from .values import RedactionTransformId, Sha256Digest

type RedactableScalar = str | int | float | bool | None
type RedactableValue = RedactableScalar | list[RedactableValue] | dict[str, RedactableValue]

REDACTION_SCHEMA_VERSION: Final = "1.0.0"
MAX_REDACTION_DEPTH: Final = 12
MAX_REDACTION_NODES: Final = 10_000
MAX_REDACTION_TEXT: Final = 65_536
REDACTION_MARKER: Final = "[REDACTED]"

_SENSITIVE_FIELDS = frozenset(
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
_ASSIGNMENT = re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+")


class RedactionRule(StrEnum):
    SENSITIVE_FIELD = "sensitive-field"
    PRIVATE_KEY = "private-key"
    AUTHORIZATION = "authorization"
    TOKEN_PREFIX = "token-prefix"
    SECRET_ASSIGNMENT = "secret-assignment"


@dataclass(frozen=True, slots=True)
class RedactionLineage:
    path: str
    occurrence: int
    rule: RedactionRule
    original_hmac: Sha256Digest
    replacement: str = REDACTION_MARKER


@dataclass(frozen=True, slots=True)
class RedactionResult:
    value: RedactableValue
    status: RedactionStatus
    transform_id: RedactionTransformId
    lineage: tuple[RedactionLineage, ...]
    schema_version: str = REDACTION_SCHEMA_VERSION


def _pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _digest(value: RedactableValue, key: bytes) -> Sha256Digest:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return Sha256Digest(hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest())


def _normalized_field(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def redact_sensitive_data(
    value: RedactableValue,
    *,
    transform_id: RedactionTransformId,
    lineage_key: bytes,
) -> RedactionResult:
    """Return a structure-preserving redacted value and secret-free audit lineage."""
    if not isinstance(lineage_key, bytes) or len(lineage_key) < 32:
        raise InvalidDomainValueError("redaction lineage key must contain at least 32 bytes")

    lineage: list[RedactionLineage] = []
    nodes = 0

    def record(path: str, rule: RedactionRule, original: RedactableValue) -> str:
        lineage.append(
            RedactionLineage(
                path=path or "/",
                occurrence=sum(item.path == (path or "/") for item in lineage),
                rule=rule,
                original_hmac=_digest(original, lineage_key),
            )
        )
        return REDACTION_MARKER

    def redact_text(text: str, path: str) -> str:
        if len(text) > MAX_REDACTION_TEXT or "\x00" in text:
            raise InvalidDomainValueError("redaction text is outside bounds")

        def replacement(selected_rule: RedactionRule) -> Callable[[re.Match[str]], str]:
            def replace(match: re.Match[str]) -> str:
                return record(path, selected_rule, match.group(0))

            return replace

        result = text
        for rule, pattern in (
            (RedactionRule.PRIVATE_KEY, _PRIVATE_KEY),
            (RedactionRule.AUTHORIZATION, _AUTHORIZATION),
            (RedactionRule.TOKEN_PREFIX, _TOKEN_PREFIX),
            (RedactionRule.SECRET_ASSIGNMENT, _ASSIGNMENT),
        ):
            result = pattern.sub(replacement(rule), result)
        return result

    def visit(item: RedactableValue, path: str, depth: int) -> RedactableValue:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_REDACTION_NODES:
            raise InvalidDomainValueError("redaction node limit exceeded")
        if depth > MAX_REDACTION_DEPTH:
            raise InvalidDomainValueError("redaction depth limit exceeded")
        if item is None or isinstance(item, bool | int):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise InvalidDomainValueError("redaction numeric values must be finite")
            return item
        if isinstance(item, str):
            return redact_text(item, path)
        if isinstance(item, list):
            return [visit(child, f"{path}/{index}", depth + 1) for index, child in enumerate(item)]
        if isinstance(item, dict):
            result: dict[str, RedactableValue] = {}
            for key in sorted(item):
                if not isinstance(key, str) or not key or len(key) > 256 or "\x00" in key:
                    raise InvalidDomainValueError("redaction object keys must be bounded text")
                child_path = f"{path}/{_pointer_part(key)}"
                child = item[key]
                result[key] = (
                    record(child_path, RedactionRule.SENSITIVE_FIELD, child)
                    if _normalized_field(key) in _SENSITIVE_FIELDS
                    else visit(child, child_path, depth + 1)
                )
            return result
        raise InvalidDomainValueError("redaction input must contain only JSON-compatible values")

    redacted = visit(value, "", 0)
    return RedactionResult(
        value=redacted,
        status=RedactionStatus.REDACTED if lineage else RedactionStatus.NOT_REQUIRED,
        transform_id=transform_id,
        lineage=tuple(lineage),
    )
