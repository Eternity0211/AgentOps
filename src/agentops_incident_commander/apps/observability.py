"""Process-owned lifecycle contract for control-plane telemetry."""

from __future__ import annotations

import logging
from typing import Protocol

from agentops_incident_commander.application import ControlPlaneObserver
from agentops_incident_commander.domain import StructuredLogEvent, StructuredLogSeverity
from agentops_incident_commander.structured_logging import emit_structured_log

logger = logging.getLogger("agentops.control_plane.process_observability")


class ProcessControlPlaneObserver(ControlPlaneObserver, Protocol):
    """One observer owned and closed by exactly one API or worker process."""

    async def shutdown(self) -> None: ...


async def shutdown_process_observer(
    observer: ProcessControlPlaneObserver,
    *,
    process_role: str,
) -> None:
    """Keep exporter shutdown failures outside application authority."""

    try:
        await observer.shutdown()
    except Exception:
        emit_structured_log(
            logger,
            StructuredLogEvent.CONTROL_PLANE_OBSERVER_SHUTDOWN_FAILED,
            StructuredLogSeverity.WARN,
            {"process.role": process_role},
        )
