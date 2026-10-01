"""Bounded post-Compose readiness checks for the local simulator stack."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

MAX_RESPONSE_BYTES = 1_000_000


class RuntimeHealthError(RuntimeError):
    """The local stack did not satisfy its observable readiness contract."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    """One bounded local endpoint and its response validator."""

    name: str
    url: str
    validate: Callable[[bytes], None]


def _port(source: Mapping[str, str], name: str, default: int) -> int:
    try:
        port = int(source.get(name, str(default)))
    except ValueError as error:
        raise RuntimeHealthError(f"invalid port setting: {name}") from error
    if port < 1 or port > 65535:
        raise RuntimeHealthError(f"invalid port setting: {name}")
    return port


def _host(source: Mapping[str, str]) -> str:
    host = source.get("RUNTIME_CHECK_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeHealthError("runtime checks must target loopback")
    return f"[{host}]" if host == "::1" else host


def _json_object(payload: bytes, endpoint: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeHealthError(f"{endpoint} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RuntimeHealthError(f"{endpoint} returned a non-object response")
    return value


def _gateway_ready(payload: bytes) -> None:
    value = _json_object(payload, "gateway readiness")
    if value.get("status") != "ready" or value.get("service") != "gateway":
        raise RuntimeHealthError("gateway readiness contract failed")


def _gateway_version(payload: bytes) -> None:
    value = _json_object(payload, "gateway version")
    required = ("deployment_id", "version", "schema_version")
    if value.get("service") != "gateway" or not all(
        isinstance(value.get(field), str) and value[field] for field in required
    ):
        raise RuntimeHealthError("gateway version contract failed")


def _contains(expected: bytes, name: str) -> Callable[[bytes], None]:
    def validate(payload: bytes) -> None:
        if expected.lower() not in payload.lower():
            raise RuntimeHealthError(f"{name} readiness contract failed")

    return validate


def _prometheus_targets(payload: bytes) -> None:
    value = _json_object(payload, "Prometheus targets")
    data = value.get("data")
    targets = data.get("activeTargets") if isinstance(data, dict) else None
    if not isinstance(targets, list):
        raise RuntimeHealthError("Prometheus targets response is missing activeTargets")
    for target in targets:
        if not isinstance(target, dict):
            continue
        labels = target.get("labels")
        scrape_url = target.get("scrapeUrl")
        if (
            isinstance(labels, dict)
            and labels.get("job") == "otel-collector"
            and isinstance(scrape_url, str)
            and "otel-collector:9464" in scrape_url
            and target.get("health") == "up"
        ):
            return
    raise RuntimeHealthError("OpenTelemetry Collector metrics target is not up")


def endpoints(environment: Mapping[str, str] | None = None) -> tuple[Endpoint, ...]:
    """Build the fixed loopback endpoint contract from allowlisted port settings."""
    source = os.environ if environment is None else environment
    host = _host(source)
    gateway = _port(source, "GATEWAY_PORT", 8080)
    prometheus = _port(source, "PROMETHEUS_PORT", 9090)
    loki = _port(source, "LOKI_PORT", 3100)
    tempo = _port(source, "TEMPO_PORT", 3200)
    return (
        Endpoint("gateway-ready", f"http://{host}:{gateway}/readyz", _gateway_ready),
        Endpoint("gateway-version", f"http://{host}:{gateway}/versionz", _gateway_version),
        Endpoint(
            "prometheus-ready",
            f"http://{host}:{prometheus}/-/ready",
            _contains(b"ready", "Prometheus"),
        ),
        Endpoint(
            "prometheus-collector-target",
            f"http://{host}:{prometheus}/api/v1/targets?state=active",
            _prometheus_targets,
        ),
        Endpoint("loki-ready", f"http://{host}:{loki}/ready", _contains(b"ready", "Loki")),
        Endpoint("tempo-ready", f"http://{host}:{tempo}/ready", _contains(b"ready", "Tempo")),
    )


def _fetch(url: str, timeout_seconds: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "agentops-runtime-check/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = cast(bytes, response.read(MAX_RESPONSE_BYTES + 1))
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        raise RuntimeHealthError("endpoint unavailable") from error
    if len(payload) > MAX_RESPONSE_BYTES:
        raise RuntimeHealthError("endpoint response exceeded size limit")
    return payload


def wait_until_ready(
    checks: Sequence[Endpoint],
    *,
    timeout_seconds: float = 60,
    interval_seconds: float = 1,
    request_timeout_seconds: float = 2,
) -> None:
    """Poll every fixed endpoint until one complete pass or the deadline."""
    if timeout_seconds <= 0 or interval_seconds <= 0 or request_timeout_seconds <= 0:
        raise ValueError("runtime health timeouts must be positive")
    if not checks:
        raise ValueError("runtime health checks cannot be empty")
    deadline = time.monotonic() + timeout_seconds
    last_failure = "no checks executed"
    while True:
        try:
            for check in checks:
                check.validate(_fetch(check.url, request_timeout_seconds))
            return
        except RuntimeHealthError as error:
            last_failure = f"{check.name}: {error}"
        if time.monotonic() >= deadline:
            raise RuntimeHealthError(f"readiness deadline exceeded ({last_failure})")
        time.sleep(min(interval_seconds, max(0, deadline - time.monotonic())))


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the local runtime using a fixed, argument-free contract."""
    if argv:
        print("[runtime] configuration-error reason=unexpected arguments", file=sys.stderr)
        return 2
    try:
        checks = endpoints()
        wait_until_ready(checks)
    except (RuntimeHealthError, ValueError) as error:
        print(f"[runtime] failed reason={error}", file=sys.stderr, flush=True)
        return 1
    print(f"[runtime] passed checks={len(checks)}", flush=True)
    return 0
