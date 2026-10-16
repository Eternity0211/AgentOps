"""Closed-schema, secret-safe structured logging contract tests."""

from __future__ import annotations

import ast
import json
import logging
from collections.abc import Mapping
from math import inf, nan
from pathlib import Path
from typing import cast

import pytest

from agentops_incident_commander.domain import (
    MAX_STRUCTURED_LOG_ATTRIBUTE_BYTES,
    MAX_STRUCTURED_LOG_ATTRIBUTES,
    MAX_STRUCTURED_LOG_RECORD_BYTES,
    REDACTION_MARKER,
    STRUCTURED_LOG_SCHEMA_VERSION,
    StructuredLogError,
    StructuredLogEvent,
    StructuredLogRecord,
    StructuredLogRejection,
    StructuredLogSeverity,
    build_structured_log_record,
    safe_structured_log_record,
    sanitize_structured_log_scalar,
    structured_logs,
)
from agentops_incident_commander.structured_logging import (
    emit_structured_log,
    emit_structured_record,
)


def test_record_is_canonical_versioned_and_immutable() -> None:
    record = build_structured_log_record(
        StructuredLogEvent.HTTP_REQUEST,
        StructuredLogSeverity.INFO,
        {
            "event.name": "http_request",
            "service.name": "agentops-simulator-gateway",
            "http.request.method": "GET",
            "http.route": "/healthz",
            "http.response.status_code": 200,
            "duration_ms": 1.25,
            "agentops.correlation_id": "correlation-1",
        },
    )

    parsed = json.loads(record.to_json())
    assert parsed == record.as_dict()
    assert parsed["log.schema.version"] == STRUCTURED_LOG_SCHEMA_VERSION
    assert parsed["event.name"] == "http_request"
    assert parsed["severity.text"] == "INFO"
    assert record.utf8_size <= MAX_STRUCTURED_LOG_RECORD_BYTES
    with pytest.raises(TypeError):
        record.attributes["new"] = "value"  # type: ignore[index]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"event": "http_request"}, StructuredLogRejection.INVALID_EVENT),
        ({"severity": "INFO"}, StructuredLogRejection.INVALID_SEVERITY),
        ({"schema_version": "2.0.0"}, StructuredLogRejection.UNSUPPORTED_SCHEMA),
        ({"attributes": cast(Mapping[str, object], [])}, StructuredLogRejection.INVALID_ATTRIBUTES),
        (
            {"attributes": {f"field-{index}": index for index in range(41)}},
            StructuredLogRejection.TOO_MANY_ATTRIBUTES,
        ),
        ({"attributes": {"unknown": "value"}}, StructuredLogRejection.UNKNOWN_FIELD),
        (
            {"attributes": {"http.route": "password" + "=secret-value"}},
            StructuredLogRejection.INVALID_VALUE,
        ),
    ],
)
def test_record_constructor_cannot_bypass_the_builder(
    overrides: dict[str, object], reason: StructuredLogRejection
) -> None:
    values: dict[str, object] = {
        "event": StructuredLogEvent.HTTP_REQUEST,
        "severity": StructuredLogSeverity.INFO,
        "attributes": {},
    }
    values.update(overrides)
    with pytest.raises(StructuredLogError) as raised:
        StructuredLogRecord(**values)  # type: ignore[arg-type]
    assert raised.value.reason is reason


@pytest.mark.parametrize(
    "seed",
    [
        "Authorization: " + "Bearer " + "abcdefghijklmnop",
        "Basic " + "dXNlcjpwYXNzd29yZA==",
        "api_key" + "=sk-" + "abcdefghijklmnop",
        "github_" + "pat_" + "abcdefghijklmnop1234",
        "postgresql://operator:" + "supersecret@database/agentops",
        "-----BEGIN " + "PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
        "cookie=session-value-123456789",
    ],
)
def test_secret_patterns_are_redacted_without_line_breaks(seed: str) -> None:
    record = build_structured_log_record(
        StructuredLogEvent.HTTP_CLIENT_REQUEST,
        StructuredLogSeverity.ERROR,
        {"server.address": f"dependency failed: {seed}\nsecond line"},
    )

    encoded = record.to_json()
    assert REDACTION_MARKER in encoded
    assert "supersecret" not in encoded
    assert "abcdefghijklmnop" not in encoded
    server_address = record.attributes["server.address"]
    assert isinstance(server_address, str)
    assert "\n" not in server_address
    assert record.attributes["agentops.log.redacted"] is True


def test_unicode_is_truncated_on_a_valid_utf8_boundary() -> None:
    record = build_structured_log_record(
        StructuredLogEvent.HTTP_REQUEST,
        StructuredLogSeverity.INFO,
        {"http.route": "界" * 400},
    )

    route = record.attributes["http.route"]
    assert isinstance(route, str)
    assert route.endswith("…")
    assert len(route.encode("utf-8")) <= MAX_STRUCTURED_LOG_ATTRIBUTE_BYTES
    assert record.attributes["agentops.log.truncated"] is True
    assert structured_logs._truncate_utf8("界", 2) == ("", True)


def test_record_limit_drops_optional_fields_but_preserves_identities() -> None:
    attributes: dict[str, object] = {
        key: "界" * 200
        for key in structured_logs._EVENT_FIELDS[StructuredLogEvent.CONTROL_PLANE_OPERATION]
    }
    attributes.update(
        {
            "agentops.tenant_id": "tenant-1",
            "agentops.incident_id": "incident-1",
            "agentops.correlation_id": "correlation-1",
            "agentops.causation_id": "cause-1",
            "agentops.operation_id": "operation-1",
            "agentops.workflow_run_id": "workflow-1",
        }
    )

    record = build_structured_log_record(
        StructuredLogEvent.CONTROL_PLANE_OPERATION,
        StructuredLogSeverity.INFO,
        attributes,
    )

    assert record.utf8_size <= MAX_STRUCTURED_LOG_RECORD_BYTES
    assert record.attributes["agentops.log.truncated"] is True
    assert cast(int, record.attributes["agentops.log.dropped_attributes"]) > 0
    for key in (
        "agentops.tenant_id",
        "agentops.incident_id",
        "agentops.correlation_id",
        "agentops.causation_id",
        "agentops.operation_id",
        "agentops.workflow_run_id",
    ):
        assert key in record.attributes


@pytest.mark.parametrize(
    ("attributes", "reason"),
    [
        ({"unknown": "value"}, StructuredLogRejection.UNKNOWN_FIELD),
        ({"password": "value"}, StructuredLogRejection.SENSITIVE_FIELD),
        ({"http.route": {"nested": "value"}}, StructuredLogRejection.INVALID_VALUE),
        ({"http.route": ["nested"]}, StructuredLogRejection.INVALID_VALUE),
        ({"duration_ms": nan}, StructuredLogRejection.INVALID_VALUE),
        ({"duration_ms": inf}, StructuredLogRejection.INVALID_VALUE),
        ({"event.name": "wrong"}, StructuredLogRejection.INVALID_VALUE),
    ],
)
def test_invalid_fields_and_values_are_refused(
    attributes: dict[str, object], reason: StructuredLogRejection
) -> None:
    with pytest.raises(StructuredLogError) as raised:
        build_structured_log_record(
            StructuredLogEvent.HTTP_REQUEST,
            StructuredLogSeverity.INFO,
            attributes,
        )
    assert raised.value.reason is reason
    assert str(raised.value) == reason.value


def test_invalid_shape_and_typed_discriminators_are_refused() -> None:
    cases: tuple[tuple[object, object, object, StructuredLogRejection], ...] = (
        (
            cast(StructuredLogEvent, "http_request"),
            StructuredLogSeverity.INFO,
            {},
            StructuredLogRejection.INVALID_EVENT,
        ),
        (
            StructuredLogEvent.HTTP_REQUEST,
            cast(StructuredLogSeverity, "INFO"),
            {},
            StructuredLogRejection.INVALID_SEVERITY,
        ),
        (
            StructuredLogEvent.HTTP_REQUEST,
            StructuredLogSeverity.INFO,
            cast(dict[str, object], []),
            StructuredLogRejection.INVALID_ATTRIBUTES,
        ),
        (
            StructuredLogEvent.HTTP_REQUEST,
            StructuredLogSeverity.INFO,
            {f"field-{index}": index for index in range(MAX_STRUCTURED_LOG_ATTRIBUTES + 1)},
            StructuredLogRejection.TOO_MANY_ATTRIBUTES,
        ),
    )
    for event, severity, attributes, expected in cases:
        with pytest.raises(StructuredLogError) as raised:
            build_structured_log_record(
                cast(StructuredLogEvent, event),
                cast(StructuredLogSeverity, severity),
                cast(Mapping[str, object], attributes),
            )
        assert raised.value.reason is expected


def test_non_string_key_and_reserved_metadata_are_refused() -> None:
    with pytest.raises(StructuredLogError) as non_string:
        build_structured_log_record(
            StructuredLogEvent.HTTP_REQUEST,
            StructuredLogSeverity.INFO,
            cast(dict[str, object], {1: "value"}),
        )
    assert non_string.value.reason is StructuredLogRejection.UNKNOWN_FIELD

    with pytest.raises(StructuredLogError) as reserved:
        build_structured_log_record(
            StructuredLogEvent.HTTP_REQUEST,
            StructuredLogSeverity.INFO,
            {"agentops.log.redacted": False},
        )
    assert reserved.value.reason is StructuredLogRejection.UNKNOWN_FIELD


def test_unshrinkable_identity_record_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(structured_logs, "MAX_STRUCTURED_LOG_RECORD_BYTES", 64)
    with pytest.raises(StructuredLogError) as raised:
        build_structured_log_record(
            StructuredLogEvent.HTTP_REQUEST,
            StructuredLogSeverity.INFO,
            {"agentops.correlation_id": "correlation-1"},
        )
    assert raised.value.reason is StructuredLogRejection.RECORD_TOO_LARGE
    with pytest.raises(StructuredLogError) as direct:
        StructuredLogRecord(
            StructuredLogEvent.HTTP_REQUEST,
            StructuredLogSeverity.INFO,
            {},
        )
    assert direct.value.reason is StructuredLogRejection.RECORD_TOO_LARGE


def test_safe_builder_replaces_invalid_payload_with_content_free_refusal() -> None:
    record = safe_structured_log_record(
        StructuredLogEvent.HTTP_REQUEST,
        StructuredLogSeverity.INFO,
        {"authorization": "Bearer never-export-this"},
    )
    assert record.event is StructuredLogEvent.PAYLOAD_REFUSED
    assert record.severity is StructuredLogSeverity.WARN
    assert record.attributes == {
        "rejected.event": "http_request",
        "rejection.reason": "SENSITIVE_FIELD",
    }
    assert "never-export-this" not in record.to_json()

    unrecognized = safe_structured_log_record(
        cast(StructuredLogEvent, "invented"),
        StructuredLogSeverity.INFO,
        {},
    )
    assert unrecognized.attributes["rejected.event"] == "UNRECOGNIZED"


def test_scalar_sanitizer_preserves_safe_scalars_and_rejects_other_values() -> None:
    for valid_value in (True, 7, 1.5, "safe"):
        sanitized, redacted, truncated = sanitize_structured_log_scalar(valid_value)
        assert sanitized == valid_value
        assert redacted is False
        assert truncated is False

    for invalid_value in (None, object(), nan, -inf):
        with pytest.raises(StructuredLogError) as raised:
            sanitize_structured_log_scalar(invalid_value)
        assert raised.value.reason is StructuredLogRejection.INVALID_VALUE


def test_standard_logging_adapter_emits_only_canonical_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("agentops.test.structured")
    caplog.set_level(logging.INFO, logger=logger.name)
    emit_structured_log(
        logger,
        StructuredLogEvent.HTTP_REQUEST,
        StructuredLogSeverity.INFO,
        {"http.route": "/healthz"},
    )
    emitted = json.loads(caplog.records[-1].message)
    assert emitted["event.name"] == "http_request"
    assert emitted["http.route"] == "/healthz"

    emit_structured_record(
        logger,
        build_structured_log_record(
            StructuredLogEvent.DEPENDENCY_TIMEOUT,
            StructuredLogSeverity.WARN,
            {"dependency": "redis"},
        ),
    )
    assert json.loads(caplog.records[-1].message)["severity.text"] == "WARN"


def test_runtime_modules_do_not_bypass_the_structured_logging_adapter() -> None:
    package = Path(__file__).resolve().parents[2] / "src" / "agentops_incident_commander"
    bypasses: list[str] = []
    direct_methods = {"debug", "info", "warning", "error", "exception", "critical", "log"}
    for path in package.rglob("*.py"):
        if path.name == "structured_logging.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"
                and node.func.attr in direct_methods
            ):
                bypasses.append(f"{path.relative_to(package)}:{node.lineno}")
    assert bypasses == []
