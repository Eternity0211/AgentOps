"""Tests for bounded local stack readiness validation."""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Iterator
from typing import Any

import pytest

from agentops_incident_commander import runtime_health


class FakeResponse:
    """Minimal context-managed HTTP response for urllib tests."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.read_limit: int | None = None

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        self.read_limit = limit
        return self.payload


def clock(*values: float) -> Iterator[float]:
    """Yield deterministic monotonic values."""
    yield from values


def valid_targets() -> bytes:
    """Return one healthy Collector target response."""
    return json.dumps(
        {
            "data": {
                "activeTargets": [
                    "ignored",
                    {"labels": "bad", "health": "down"},
                    {
                        "labels": {"job": "otel-collector"},
                        "scrapeUrl": "http://otel-collector:9464/metrics",
                        "health": "up",
                    },
                ]
            }
        }
    ).encode()


def test_endpoints_use_loopback_and_allowlisted_ports() -> None:
    """Runtime checks never accept a caller-controlled remote target."""
    checks = runtime_health.endpoints(
        {
            "RUNTIME_CHECK_HOST": "::1",
            "GATEWAY_PORT": "18080",
            "PROMETHEUS_PORT": "19090",
            "LOKI_PORT": "13100",
            "TEMPO_PORT": "13200",
        }
    )

    assert len(checks) == 6
    assert checks[0].url == "http://[::1]:18080/readyz"
    assert checks[-1].url == "http://[::1]:13200/ready"


@pytest.mark.parametrize(
    "environment",
    [
        {"RUNTIME_CHECK_HOST": "example.com"},
        {"GATEWAY_PORT": "bad"},
        {"GATEWAY_PORT": "0"},
        {"GATEWAY_PORT": "65536"},
    ],
)
def test_endpoints_reject_remote_host_or_invalid_port(environment: dict[str, str]) -> None:
    """Health configuration cannot become an SSRF primitive or invalid socket target."""
    with pytest.raises(runtime_health.RuntimeHealthError):
        runtime_health.endpoints(environment)


def test_response_validators_accept_complete_contracts() -> None:
    """All JSON and text validators recognize their intended healthy response."""
    checks = runtime_health.endpoints({})
    payloads = (
        b'{"status":"ready","service":"gateway"}',
        b'{"service":"gateway","deployment_id":"d1","version":"1","schema_version":"1"}',
        b"Prometheus Server is Ready.",
        valid_targets(),
        b"ready",
        b"READY",
    )

    for check, payload in zip(checks, payloads, strict=True):
        check.validate(payload)


@pytest.mark.parametrize(
    ("validator", "payload", "message"),
    [
        (runtime_health._gateway_ready, b"not-json", "invalid JSON"),
        (runtime_health._gateway_ready, b"[]", "non-object"),
        (runtime_health._gateway_ready, b'{"status":"no"}', "readiness contract"),
        (
            runtime_health._gateway_version,
            b'{"service":"gateway","deployment_id":""}',
            "version contract",
        ),
        (runtime_health._contains(b"ready", "demo"), b"starting", "readiness contract"),
        (runtime_health._prometheus_targets, b'{"data":{}}', "missing activeTargets"),
        (
            runtime_health._prometheus_targets,
            b'{"data":{"activeTargets":[{"labels":{"job":"other"}}]}}',
            "not up",
        ),
    ],
)
def test_response_validators_reject_incomplete_contracts(
    validator: Any, payload: bytes, message: str
) -> None:
    """Malformed or incomplete backend responses cannot produce false readiness."""
    with pytest.raises(runtime_health.RuntimeHealthError, match=message):
        validator(payload)


def test_fetch_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP reads use a fixed user agent, deadline, and maximum response size."""
    response = FakeResponse(b"ready")

    def urlopen(request: Any, *, timeout: float) -> FakeResponse:
        assert request.get_header("User-agent") == "agentops-runtime-check/1"
        assert timeout == 2
        return response

    monkeypatch.setattr(
        "agentops_incident_commander.runtime_health.urllib.request.urlopen", urlopen
    )

    assert runtime_health._fetch("http://127.0.0.1/ready", 2) == b"ready"
    assert response.read_limit == runtime_health.MAX_RESPONSE_BYTES + 1


@pytest.mark.parametrize(
    "failure",
    [
        OSError("offline"),
        urllib.error.URLError("offline"),
    ],
)
def test_fetch_maps_transport_failures(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    """Network implementation details collapse to one stable health error."""
    monkeypatch.setattr(
        "agentops_incident_commander.runtime_health.urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(runtime_health.RuntimeHealthError, match="endpoint unavailable"):
        runtime_health._fetch("http://127.0.0.1/ready", 2)


def test_fetch_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A local endpoint cannot exhaust checker memory with an unbounded body."""
    monkeypatch.setattr(
        "agentops_incident_commander.runtime_health.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(b"x" * (runtime_health.MAX_RESPONSE_BYTES + 1)),
    )

    with pytest.raises(runtime_health.RuntimeHealthError, match="size limit"):
        runtime_health._fetch("http://127.0.0.1/ready", 2)


def test_wait_retries_then_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transient startup failures retry within the total deadline."""
    calls = 0
    sleeps: list[float] = []

    def fetch(url: str, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise runtime_health.RuntimeHealthError("starting")
        return b"ready"

    values = clock(0, 0.1, 0.2, 0.3)
    monkeypatch.setattr(runtime_health, "_fetch", fetch)
    monkeypatch.setattr(
        "agentops_incident_commander.runtime_health.time.monotonic", lambda: next(values)
    )
    monkeypatch.setattr("agentops_incident_commander.runtime_health.time.sleep", sleeps.append)
    check = runtime_health.Endpoint("demo", "http://127.0.0.1", lambda payload: None)

    runtime_health.wait_until_ready((check,), timeout_seconds=5, interval_seconds=1)

    assert calls == 2
    assert sleeps == [1]


def test_wait_reports_last_failure_at_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deadline errors name the failed bounded check without leaking transport details."""
    values = clock(0, 1, 1)
    monkeypatch.setattr(
        runtime_health,
        "_fetch",
        lambda url, timeout: (_ for _ in ()).throw(runtime_health.RuntimeHealthError("down")),
    )
    monkeypatch.setattr(
        "agentops_incident_commander.runtime_health.time.monotonic", lambda: next(values)
    )
    check = runtime_health.Endpoint("gateway", "http://127.0.0.1", lambda payload: None)

    with pytest.raises(runtime_health.RuntimeHealthError, match="gateway: down"):
        runtime_health.wait_until_ready((check,), timeout_seconds=1)


@pytest.mark.parametrize(
    "checks,timeout,interval,request_timeout",
    [
        ((), 1, 1, 1),
        ((runtime_health.Endpoint("x", "x", lambda payload: None),), 0, 1, 1),
        ((runtime_health.Endpoint("x", "x", lambda payload: None),), 1, 0, 1),
        ((runtime_health.Endpoint("x", "x", lambda payload: None),), 1, 1, 0),
    ],
)
def test_wait_rejects_empty_or_unbounded_configuration(
    checks: tuple[runtime_health.Endpoint, ...],
    timeout: float,
    interval: float,
    request_timeout: float,
) -> None:
    """The checker cannot be configured to skip work or wait without a bound."""
    with pytest.raises(ValueError):
        runtime_health.wait_until_ready(
            checks,
            timeout_seconds=timeout,
            interval_seconds=interval,
            request_timeout_seconds=request_timeout,
        )


def test_main_reports_success_failure_and_unexpected_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The script exposes stable process codes for task-runner composition."""
    monkeypatch.setattr(runtime_health, "endpoints", lambda: ())
    monkeypatch.setattr(runtime_health, "wait_until_ready", lambda checks: None)
    assert runtime_health.main() == 0
    assert "passed checks=0" in capsys.readouterr().out

    monkeypatch.setattr(
        runtime_health,
        "wait_until_ready",
        lambda checks: (_ for _ in ()).throw(runtime_health.RuntimeHealthError("down")),
    )
    assert runtime_health.main() == 1
    assert "failed reason=down" in capsys.readouterr().err

    assert runtime_health.main(("unexpected",)) == 2
    assert "unexpected arguments" in capsys.readouterr().err
