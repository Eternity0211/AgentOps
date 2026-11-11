"""Fixed-window evaluator capture and model-independent read-tool replay."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from agentops_incident_commander.application import ToolGatewayError
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
            code = (
                "SNAPSHOT_CAPTURE_FAILED"
                if isinstance(record, dict) and record.get("error_code") == "CAPTURE_FAILED"
                else "SNAPSHOT_SOURCE_UNAVAILABLE"
            )
            raise ToolGatewayError(code, "snapshot source unavailable")
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


def load_snapshot(path: Path, *, expected_hash: str) -> dict[str, Any]:
    import hashlib
    import re

    with path.open("rb") as stream:
        raw = stream.read(4_194_305)
    if len(raw) > 4_194_304 or hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("snapshot hash/size mismatch")
    snapshot = json.loads(raw)
    expected_fields = {
        "schema_version",
        "instance_id",
        "window_start",
        "window_end",
        "alert",
        "reads",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != expected_fields:
        raise ValueError("snapshot schema mismatch")
    if snapshot["schema_version"] != "1.0.0" or not re.fullmatch(
        r"instance-[0-9a-f]{16}", snapshot["instance_id"]
    ):
        raise ValueError("snapshot identity/version mismatch")
    start, end = (datetime.fromisoformat(snapshot[key]) for key in ("window_start", "window_end"))
    if start.utcoffset() is None or end.utcoffset() is None or start > end:
        raise ValueError("snapshot window mismatch")
    if not isinstance(snapshot["alert"], str) or len(snapshot["alert"]) > 16000:
        raise ValueError("snapshot alert invalid")
    keys = {f"{d.name}:{service}" for d in local_definitions() for service in SERVICES}
    if not isinstance(snapshot["reads"], dict) or set(snapshot["reads"]) != keys:
        raise ValueError("snapshot read catalog mismatch")
    return dict(snapshot)
