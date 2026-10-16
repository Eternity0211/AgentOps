"""Standard-library adapter for the shared structured-log domain contract."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from agentops_incident_commander.domain.structured_logs import (
    StructuredLogEvent,
    StructuredLogRecord,
    StructuredLogSeverity,
    safe_structured_log_record,
)

_LEVELS = {
    StructuredLogSeverity.DEBUG: logging.DEBUG,
    StructuredLogSeverity.INFO: logging.INFO,
    StructuredLogSeverity.WARN: logging.WARNING,
    StructuredLogSeverity.ERROR: logging.ERROR,
}


def emit_structured_record(logger: logging.Logger, record: StructuredLogRecord) -> None:
    """Emit one already-validated record without reconstructing its payload."""
    logger.log(_LEVELS[record.severity], record.to_json())


def emit_structured_log(
    logger: logging.Logger,
    event: StructuredLogEvent,
    severity: StructuredLogSeverity,
    attributes: Mapping[str, object],
) -> None:
    """Emit only the validated canonical JSON representation."""
    record = safe_structured_log_record(event, severity, attributes)
    emit_structured_record(logger, record)
