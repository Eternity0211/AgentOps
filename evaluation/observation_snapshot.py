"""Fixed-window evaluator capture and model-independent read-tool replay."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from agentops_incident_commander.domain import (
    ArtifactId,
    PromptInjectionStatus,
    RedactionTransformId,
    inspect_untrusted_telemetry,
    redact_sensitive_data,
)
from evaluation.live_gateway import SERVICES, LocalReadAdapter, local_definitions
from evaluation.structured_model import fingerprint


async def capture_reads(start: datetime, end: datetime) -> dict[str, Any]:
    async def capture(tool: str, service: str) -> tuple[str, dict[str, Any]]:
        adapter = LocalReadAdapter(tool, start, end)
        try:
            output = dict(await adapter.invoke(None, {"service": service}))  # type: ignore[arg-type]
            output = sanitize_output(output)
            return f"{tool}:{service}", {"status": "SUCCEEDED", "output": output}
        except Exception:
            return f"{tool}:{service}", {"status": "FAILED", "error_code": "CAPTURE_FAILED"}

    pairs = await asyncio.gather(
        *(capture(d.name, service) for d in local_definitions() for service in SERVICES)
    )
    return dict(pairs)


def write_snapshot(
    path: Path, instance_id: str, start: datetime, end: datetime, reads: dict[str, Any], alert: str
) -> str:
    document = {
        "schema_version": "1.0.0",
        "instance_id": instance_id,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "alert": alert,
        "reads": reads,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return fingerprint(document)


class SnapshotReadAdapter:
    def __init__(self, tool: str, reads: dict[str, Any]) -> None:
        self.tool = tool
        self.reads = json.loads(json.dumps(reads, allow_nan=False))

    async def invoke(self, context: Any, arguments: Any) -> dict[str, Any]:
        if set(arguments) != {"service"} or arguments["service"] not in SERVICES:
            raise ValueError("snapshot service refused")
        record = self.reads.get(f"{self.tool}:{arguments['service']}")
        if record is None or record["status"] != "SUCCEEDED":
            raise RuntimeError("snapshot source unavailable")
        return dict(json.loads(json.dumps(record["output"])))


def sanitize_output(output: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_sensitive_data(
        output,
        transform_id=RedactionTransformId("capture-redaction"),
        lineage_key=secrets.token_bytes(32),
    )
    if not isinstance(redacted.value, dict):
        raise ValueError("capture output must remain an object")
    result = dict(redacted.value)
    inspection = inspect_untrusted_telemetry(
        json.dumps(result), source_artifact_id=ArtifactId("capture-inspection")
    )
    if inspection.status is PromptInjectionStatus.SUSPECTED:
        raise ValueError("capture prompt injection quarantined")
    return result
