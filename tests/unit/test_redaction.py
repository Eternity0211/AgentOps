"""Sensitive-data redaction and transformation-lineage tests."""

from __future__ import annotations

from typing import Any, cast

import pytest

from agentops_incident_commander.domain import (
    MAX_REDACTION_DEPTH,
    MAX_REDACTION_NODES,
    MAX_REDACTION_TEXT,
    REDACTION_MARKER,
    REDACTION_SCHEMA_VERSION,
    InvalidDomainValueError,
    RedactableValue,
    RedactionResult,
    RedactionRule,
    RedactionStatus,
    RedactionTransformId,
    redact_sensitive_data,
)

KEY = b"lineage-key-for-tests-is-at-least-32-bytes"
CANARY = "seeded-canary-secret-8f3c1a"


def redact(value: RedactableValue, *, key: bytes = KEY) -> RedactionResult:
    return redact_sensitive_data(
        value,
        transform_id=RedactionTransformId("redaction-test-1"),
        lineage_key=key,
    )


def test_sensitive_fields_are_replaced_with_secret_free_lineage() -> None:
    source: RedactableValue = {
        "user": "operator",
        "credentials": {
            "password": CANARY,
            "api-key": "key-canary-123",
            "nested/field~name": "safe",
        },
        "authorization": {"unexpected": "nested-secret"},
    }
    result = redact(source)

    assert result.value == {
        "authorization": REDACTION_MARKER,
        "credentials": {
            "api-key": REDACTION_MARKER,
            "nested/field~name": "safe",
            "password": REDACTION_MARKER,
        },
        "user": "operator",
    }
    assert result.status is RedactionStatus.REDACTED
    assert result.transform_id == RedactionTransformId("redaction-test-1")
    assert result.schema_version == REDACTION_SCHEMA_VERSION
    assert tuple(item.path for item in result.lineage) == (
        "/authorization",
        "/credentials/api-key",
        "/credentials/password",
    )
    assert all(item.rule is RedactionRule.SENSITIVE_FIELD for item in result.lineage)
    assert all(item.replacement == REDACTION_MARKER for item in result.lineage)
    assert CANARY not in repr(result)
    assert "key-canary-123" not in repr(result)
    assert "nested-secret" not in repr(result)


def test_inline_secret_patterns_are_redacted_and_paths_are_escaped() -> None:
    private_key = (
        "-----BEGIN " + "PRIVATE KEY-----\nseeded-private-canary\n-----END PRIVATE KEY-----"
    )
    provider_credential = "github_" + "pat_seededCanary12345"
    source: RedactableValue = {
        "logs/~raw": [
            f"auth Bearer {CANARY}",
            f"github {provider_credential}",
            "password" + "=seeded-assignment-canary",
            private_key,
        ]
    }
    result = redact(source)
    rendered = repr(result)

    assert result.value == {
        "logs/~raw": [
            f"auth {REDACTION_MARKER}",
            f"github {REDACTION_MARKER}",
            REDACTION_MARKER,
            REDACTION_MARKER,
        ]
    }
    assert tuple(item.rule for item in result.lineage) == (
        RedactionRule.AUTHORIZATION,
        RedactionRule.TOKEN_PREFIX,
        RedactionRule.SECRET_ASSIGNMENT,
        RedactionRule.PRIVATE_KEY,
    )
    assert tuple(item.path for item in result.lineage) == (
        "/logs~1~0raw/0",
        "/logs~1~0raw/1",
        "/logs~1~0raw/2",
        "/logs~1~0raw/3",
    )
    for canary in (
        CANARY,
        "seededCanary12345",
        "seeded-assignment-canary",
        "seeded-private-canary",
    ):
        assert canary not in rendered


def test_multiple_matches_record_stable_occurrences_without_plaintext() -> None:
    result = redact(f"Bearer {CANARY}; Bearer another-seeded-secret")
    assert result.value == f"{REDACTION_MARKER}; {REDACTION_MARKER}"
    assert tuple(item.occurrence for item in result.lineage) == (0, 1)
    assert result.lineage[0].original_hmac != result.lineage[1].original_hmac


def test_lineage_is_deterministic_for_one_key_and_keyed_against_guessing() -> None:
    first = redact({"password": CANARY})
    second = redact({"password": CANARY})
    other_key = redact({"password": CANARY}, key=b"a-different-lineage-key-of-32-bytes-minimum")
    assert first == second
    assert first.lineage[0].original_hmac != other_key.lineage[0].original_hmac


def test_safe_json_preserves_structure_and_needs_no_redaction() -> None:
    source: RedactableValue = {
        "enabled": True,
        "count": 2,
        "ratio": 1.5,
        "missing": None,
        "items": ["healthy", False],
    }
    result = redact(source)
    assert result.value == source
    assert result.status is RedactionStatus.NOT_REQUIRED
    assert result.lineage == ()


@pytest.mark.parametrize("key", [b"short", "not-bytes", bytearray(b"x" * 32)])
def test_lineage_key_must_be_strong_bytes(key: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="lineage key"):
        redact_sensitive_data(
            "safe",
            transform_id=RedactionTransformId("redaction"),
            lineage_key=key,
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_numbers_are_rejected(value: float) -> None:
    with pytest.raises(InvalidDomainValueError, match="finite"):
        redact(value)


@pytest.mark.parametrize(
    "value",
    ["x" * (MAX_REDACTION_TEXT + 1), "bad\x00text"],
    ids=("oversized", "null-byte"),
)
def test_text_bounds_are_enforced(value: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="text"):
        redact(value)


@pytest.mark.parametrize("key", ["", "x" * 257, "bad\x00key"])
def test_object_key_bounds_are_enforced(key: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="object keys"):
        redact({key: "value"})


def test_depth_limit_is_enforced() -> None:
    value: RedactableValue = "leaf"
    for _ in range(MAX_REDACTION_DEPTH + 1):
        value = [value]
    with pytest.raises(InvalidDomainValueError, match="depth"):
        redact(value)


def test_node_limit_is_enforced() -> None:
    with pytest.raises(InvalidDomainValueError, match="node limit"):
        redact([None] * MAX_REDACTION_NODES)


def test_non_json_values_are_rejected() -> None:
    with pytest.raises(InvalidDomainValueError, match="JSON-compatible"):
        redact(cast(RedactableValue, ("tuple",)))


def test_non_string_object_key_is_rejected_at_runtime() -> None:
    with pytest.raises(InvalidDomainValueError, match="object keys"):
        redact(cast(RedactableValue, {1: "value"}))
