"""Local-only v2 read catalog over actual telemetry, behind the production Gateway."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

import httpx

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.application import ToolAdapterContext
from agentops_incident_commander.domain import (
    Permission,
    SemanticVersion,
    ToolAccessClass,
    ToolAuditPolicy,
    ToolDefinition,
    ToolIdempotency,
    ToolRetryPolicy,
    ToolRisk,
    ToolSchema,
    as_utc,
)
from evaluation.run_live_diagnosis import ENVIRONMENT, ROOT

VERSION = SemanticVersion("2.0.0")
TRACE_SUMMARY_POLICY = "prefer-otel-error-on-truncation/1.0.0"
SERVICES = ("gateway", "order", "inventory", "payment")
TRACE_RESOURCE_SERVICES = frozenset(f"agentops-simulator-{name}" for name in SERVICES)
SOURCES = {
    "query_metrics": "metrics",
    "query_logs": "logs",
    "query_traces": "traces",
    "query_deployments": "deployments",
    "get_service_topology": "topology",
}


def local_definitions() -> tuple[ToolDefinition, ...]:
    input_schema = ToolSchema.from_mapping(
        VERSION,
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"service": {"type": "string", "enum": list(SERVICES)}},
            "required": ["service"],
        },
    )
    output_schema = ToolSchema.from_mapping(
        VERSION,
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "source": {"type": "string", "enum": list(SOURCES.values())},
                "summary": {"type": "string", "maxLength": 12000},
                "provenance": {"type": "string", "maxLength": 4096},
                "complete_window": {"type": "boolean"},
                "records_seen": {"type": "integer", "minimum": 0},
            },
            "required": ["source", "summary", "provenance", "complete_window", "records_seen"],
        },
    )
    return tuple(
        ToolDefinition(
            name=name,
            semantic_version=VERSION,
            input_schema=input_schema,
            output_schema=output_schema,
            access_class=ToolAccessClass.READ,
            risk=ToolRisk.LOW,
            required_permission=Permission.EVIDENCE_READ,
            timeout_ms=20000,
            retry_policy=ToolRetryPolicy(1, 0, 0, frozenset()),
            idempotency=ToolIdempotency.NOT_APPLICABLE,
            audit=ToolAuditPolicy("tool.call", VERSION),
            max_input_bytes=512,
            max_result_bytes=24000,
        )
        for name in SOURCES
    )


def _is_error_span(record: Mapping[str, Any]) -> bool:
    status = record.get("status")
    return isinstance(status, dict) and status.get("code") in (2, "STATUS_CODE_ERROR")


def deployment_observation(service: str) -> dict[str, Any]:
    if service not in SERVICES:
        raise ValueError("unknown local service")
    # Fixed read-only probe, never a model-authored command or endpoint.
    script = (
        "import urllib.request; "
        "print(urllib.request.urlopen('http://127.0.0.1:8000/versionz', timeout=3).read().decode())"
    )
    response = subprocess.run(
        ["docker", "compose", "exec", "-T", service, "python", "-c", script],
        cwd=ROOT,
        env={**os.environ, **ENVIRONMENT},
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(response.stdout)  # type: ignore[no-any-return]


class LocalReadAdapter:
    def __init__(
        self,
        tool: str,
        start: datetime,
        end: datetime,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        deployment_probe: Callable[[str], dict[str, Any]] = deployment_observation,
    ) -> None:
        if (
            tool not in SOURCES
            or as_utc(end) <= as_utc(start)
            or (end - start).total_seconds() > 3600
        ):
            raise ValueError("invalid local tool or incident window")
        self.tool, self.start, self.end = tool, as_utc(start), as_utc(end)
        self.transport, self.probe = transport, deployment_probe

    async def invoke(
        self, context: ToolAdapterContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if set(arguments) != {"service"} or arguments["service"] not in SERVICES:
            raise ValueError("local service arguments refused")
        service = str(arguments["service"])
        source = SOURCES[self.tool]
        requests: list[dict[str, Any]] = []
        records: list[Any] = []
        if source == "deployments":
            records = [await asyncio.to_thread(self.probe, service)]
            requests = [{"probe": "fixed-loopback-versionz", "service": service}]
        elif source == "topology":
            records = [
                {"source": "gateway", "target": "order"},
                {"source": "order", "target": "inventory"},
                {"source": "order", "target": "payment"},
                {"source": "order", "target": "postgresql"},
                {"source": "inventory", "target": "redis"},
            ]
            requests = [{"configuration": "compose.yaml", "scope": "local simulator"}]
        else:
            async with httpx.AsyncClient(
                timeout=10, trust_env=False, follow_redirects=False, transport=self.transport
            ) as client:
                if source == "metrics":
                    selector = f'{{service_name="agentops-simulator-{service}"}}'
                    window_ms = max(1, (self.end - self.start) // timedelta(milliseconds=1))
                    metric_window = f"[{window_ms}ms]"
                    queries = [
                        "sum by (route,status,service_version) "
                        "(increase(simulator_http_server_requests_total"
                        + selector
                        + metric_window
                        + "))",
                        "sum by (dependency,operation,outcome) "
                        "(increase(simulator_dependency_operations_total"
                        + selector
                        + metric_window
                        + "))",
                        "histogram_quantile(0.95,sum by(le,route) "
                        "(rate(simulator_http_server_duration_milliseconds_bucket"
                        + selector
                        + metric_window
                        + ")))",
                    ]
                    for query in queries:
                        params = {"query": query, "time": str(self.end.timestamp())}
                        endpoint = "http://127.0.0.1:19090/api/v1/query"
                        body = await self._get(client, endpoint, params)
                        requests.append({"endpoint": endpoint, "parameters": params})
                        records.append({"query": query, "series": body["data"]["result"][:20]})
                elif source == "logs":
                    endpoint = "http://127.0.0.1:13100/loki/api/v1/query_range"
                    params = {
                        "query": f'{{service_name="agentops-simulator-{service}"}}',
                        "start": str(int(self.start.timestamp() * 1e9)),
                        "end": str(int(self.end.timestamp() * 1e9)),
                        "limit": "40",
                    }
                    body = await self._get(client, endpoint, params)
                    requests.append({"endpoint": endpoint, "parameters": params})
                    for stream in body["data"]["result"]:
                        for value in stream["values"]:
                            # Important fields live in labels/metadata, not event body text.
                            records.append(
                                {
                                    "event": value[1],
                                    "metadata": value[2] if len(value) > 2 else {},
                                    "stream": {
                                        k: v
                                        for k, v in stream["stream"].items()
                                        if k
                                        not in {
                                            "agentops_correlation_id",
                                            "flags",
                                            "scope_name",
                                            "scope_version",
                                            "span_id",
                                            "trace_id",
                                            "service_instance_id",
                                        }
                                        and not k.startswith("telemetry_sdk")
                                    },
                                }
                            )
                else:
                    endpoint = "http://127.0.0.1:13200/api/search"
                    params = {
                        "tags": f'service.name="agentops-simulator-{service}"',
                        "start": str(int(self.start.timestamp())),
                        "end": str(int(self.end.timestamp())),
                        "limit": "8",
                    }
                    body = await self._get(client, endpoint, params)
                    requests.append({"endpoint": endpoint, "parameters": params})
                    for trace in body.get("traces", []):
                        trace_id = trace.get("traceID")
                        if (
                            not isinstance(trace_id, str)
                            or not re.fullmatch(r"[0-9a-fA-F]{1,32}", trace_id)
                            or int(trace_id, 16) == 0
                        ):
                            raise ValueError("invalid telemetry trace identity")
                        # Tempo search can trim leading zeroes; preserve numeric identity.
                        detail_endpoint = (
                            "http://127.0.0.1:13200/api/traces/" + trace_id.lower().zfill(32)
                        )
                        detail = await self._get(client, detail_endpoint, {})
                        requests.append({"endpoint": detail_endpoint, "parameters": {}})
                        for batch in detail.get("batches", []):
                            span_service = next(
                                (
                                    attribute["value"]["stringValue"]
                                    for attribute in batch.get("resource", {}).get("attributes", [])
                                    if attribute.get("key") == "service.name"
                                    and attribute.get("value", {}).get("stringValue")
                                    in TRACE_RESOURCE_SERVICES
                                ),
                                None,
                            )
                            for scope in batch.get("scopeSpans", []):
                                for span in scope.get("spans", []):
                                    if span.get("name", "").startswith("GET /readyz"):
                                        continue
                                    records.append(
                                        {
                                            "name": span.get("name"),
                                            "service": span_service,
                                            "status": span.get("status"),
                                            "start": span.get("startTimeUnixNano"),
                                            "end": span.get("endTimeUnixNano"),
                                            "attributes": span.get("attributes", []),
                                        }
                                    )
        summary = json.dumps(records, sort_keys=True, separators=(",", ":"))
        if source == "traces" and len(summary) > 12000:
            records.sort(key=lambda record: not _is_error_span(record))
        # Trim whole records, never cut JSON or silently hide truncation.
        dropped = 0
        while len(summary) > 12000 and records:
            records.pop()
            dropped += 1
            summary = json.dumps(records, sort_keys=True, separators=(",", ":"))
        provenance = {
            "tool": self.tool,
            "version": VERSION.value,
            "service": service,
            "window_start": self.start.isoformat(),
            "window_end": self.end.isoformat(),
            "requests": requests,
            "dropped_records": dropped,
        }
        if source == "traces":
            provenance["summary_policy"] = TRACE_SUMMARY_POLICY
            provenance["span_service_source"] = "otel-resource-service-name/1.0.0"
        return {
            "source": source,
            "summary": summary,
            "provenance": json.dumps(provenance, sort_keys=True),
            "complete_window": False,
            "records_seen": len(records),
        }

    @staticmethod
    async def _get(
        client: httpx.AsyncClient, endpoint: str, parameters: dict[str, str]
    ) -> dict[str, Any]:
        async with client.stream("GET", endpoint, params=parameters) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 2 * 1024 * 1024:
                    raise ValueError("telemetry response limit exceeded")
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("telemetry response must be an object")
        return parsed
