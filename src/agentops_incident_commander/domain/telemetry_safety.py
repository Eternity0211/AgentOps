"""Deterministic prompt-injection screening and quarantine for untrusted telemetry."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from .errors import InvalidDomainValueError
from .evidence import PromptInjectionStatus
from .values import ArtifactId, Sha256Digest

TELEMETRY_SAFETY_SCHEMA_VERSION: Final = "1.0.0"
MAX_TELEMETRY_TEXT: Final = 65_536
_WHITESPACE = re.compile(r"\s+")
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060\ufeff]")


class InjectionReason(StrEnum):
    INSTRUCTION_OVERRIDE = "instruction-override"
    ROLE_IMPERSONATION = "role-impersonation"
    TOOL_EXECUTION = "tool-execution"
    POLICY_BYPASS = "policy-bypass"
    DATA_EXFILTRATION = "data-exfiltration"


_RULES: Final = (
    (
        InjectionReason.INSTRUCTION_OVERRIDE,
        re.compile(
            r"\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b"
        ),
    ),
    (
        InjectionReason.ROLE_IMPERSONATION,
        re.compile(
            r"(?:<\/?(?:system|developer)>|\b(?:system|developer)\s+message\s*:|\byou\s+are\s+now\b)"
        ),
    ),
    (
        InjectionReason.TOOL_EXECUTION,
        re.compile(r"\b(?:call|invoke|use)\s+(?:the\s+)?(?:tool|shell|terminal)\b"),
    ),
    (
        InjectionReason.POLICY_BYPASS,
        re.compile(
            r"\b(?:bypass|disable|override)\s+(?:the\s+)?(?:policy|safety|approval|evidence\s+gate)\b"
        ),
    ),
    (
        InjectionReason.DATA_EXFILTRATION,
        re.compile(
            r"\b(?:reveal|print|return|send|exfiltrate)\s+(?:the\s+)?(?:secret|password|credential|system\s+prompt)s?\b"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class TelemetrySafetyEnvelope:
    source_artifact_id: ArtifactId
    status: PromptInjectionStatus
    reasons: tuple[InjectionReason, ...]
    content_hash: Sha256Digest
    content_length: int
    delimited_content: str | None
    schema_version: str = TELEMETRY_SAFETY_SCHEMA_VERSION


def _normalize_for_detection(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = _ZERO_WIDTH.sub("", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def _delimit(text: str) -> str:
    encoded = json.dumps(text, ensure_ascii=True)
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e")
    return (
        f'<UNTRUSTED_TELEMETRY_DATA encoding="json-string">\n{encoded}\n</UNTRUSTED_TELEMETRY_DATA>'
    )


def inspect_untrusted_telemetry(
    text: str, *, source_artifact_id: ArtifactId
) -> TelemetrySafetyEnvelope:
    """Classify telemetry as data; never execute or semantically follow its contents."""
    if not isinstance(text, str) or not text or len(text) > MAX_TELEMETRY_TEXT or "\x00" in text:
        raise InvalidDomainValueError("untrusted telemetry text is outside bounds")
    detection_text = _normalize_for_detection(text)
    reasons = tuple(reason for reason, pattern in _RULES if pattern.search(detection_text))
    suspected = bool(reasons)
    return TelemetrySafetyEnvelope(
        source_artifact_id=source_artifact_id,
        status=(PromptInjectionStatus.SUSPECTED if suspected else PromptInjectionStatus.NONE),
        reasons=reasons,
        content_hash=Sha256Digest(hashlib.sha256(text.encode("utf-8")).hexdigest()),
        content_length=len(text.encode("utf-8")),
        delimited_content=None if suspected else _delimit(text),
    )


def quarantine_telemetry(
    inspection: TelemetrySafetyEnvelope,
) -> TelemetrySafetyEnvelope:
    """Mark suspected content quarantined without copying raw content into the result."""
    if inspection.status is not PromptInjectionStatus.SUSPECTED:
        raise InvalidDomainValueError("only suspected telemetry can enter quarantine")
    if not inspection.reasons or inspection.delimited_content is not None:
        raise InvalidDomainValueError("suspected telemetry quarantine metadata is inconsistent")
    return replace(inspection, status=PromptInjectionStatus.QUARANTINED)
