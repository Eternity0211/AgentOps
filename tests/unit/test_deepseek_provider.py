"""Real-provider transport is fail-closed and journals without payloads or secrets."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from evaluation.deepseek_provider import DeepSeekEvaluationProvider

OBSERVATIONS = [{"id": "e1", "source": "logs", "summary": "bounded error"}]


def response_body() -> dict[str, Any]:
    return {
        "model": "deepseek-flash",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "incident_id": "i1",
                            "disposition": "HUMAN_HANDOFF",
                            "candidates": [],
                            "missing_evidence": ["independent sources"],
                            "explanation": "Need more evidence",
                        }
                    )
                },
            }
        ],
    }


def test_success_journals_before_dispatch_without_payload_or_secret() -> None:
    events: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert events[0]["event"] == "started"
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 2048
        return httpx.Response(200, json=response_body())

    result = DeepSeekEvaluationProvider(
        "test-secret",
        events.append,
        transport=httpx.MockTransport(handle),
    ).diagnose("i1", OBSERVATIONS)
    assert result["status"] == "validated"
    assert result["usage"]["total_tokens"] == 30
    assert result["cost"] is None
    assert result["runtime_gate"] == "NOT_RUN"
    assert len(events) == 2
    serialized = json.dumps(events)
    assert "test-secret" not in serialized
    assert "bounded error" not in serialized
    assert "Need more evidence" not in serialized


@pytest.mark.parametrize("status", [401, 402, 429, 500, 302])
def test_http_failure_has_no_body_or_retry(status: int) -> None:
    events: list[dict[str, Any]] = []
    provider = DeepSeekEvaluationProvider(
        "test-secret",
        events.append,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="sensitive provider body")
        ),
    )
    result = provider.diagnose("i1", OBSERVATIONS)
    assert result["error_code"] == f"HTTP_{status}"
    assert len(events) == 2
    assert "sensitive" not in json.dumps(events)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("timeout", "TIMEOUT"),
        ("transport", "TRANSPORT_ERROR"),
        ("large", "RESPONSE_TOO_LARGE"),
        ("json", "INVALID_RESPONSE"),
        ("schema", "INVALID_RESPONSE"),
        ("usage", "INVALID_USAGE"),
        ("arithmetic", "INVALID_USAGE"),
        ("truncated", "INCOMPLETE_OUTPUT"),
        ("incident", "INCIDENT_MISMATCH"),
        ("reference", "UNKNOWN_REFERENCE"),
    ],
)
def test_provider_failures(mode: str, expected: str) -> None:
    events: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if mode == "timeout":
            raise httpx.ReadTimeout("secret")
        if mode == "transport":
            raise httpx.ConnectError("secret")
        if mode == "large":
            return httpx.Response(200, content=b"x" * 262145)
        if mode == "json":
            return httpx.Response(200, text="bad json")
        body = response_body()
        if mode == "usage":
            body["usage"]["prompt_tokens"] = True
        if mode == "arithmetic":
            body["usage"]["total_tokens"] = 99
        if mode == "truncated":
            body["choices"][0]["finish_reason"] = "length"
        if mode == "schema":
            body["choices"][0]["message"]["content"] = "{}"
        if mode == "incident":
            body["choices"][0]["message"]["content"] = body["choices"][0]["message"][
                "content"
            ].replace('"i1"', '"other"')
        if mode == "reference":
            report = json.loads(body["choices"][0]["message"]["content"])
            report.update(
                disposition="CANDIDATES",
                candidates=[
                    {
                        "candidate_id": "cause",
                        "rank": 1,
                        "statement": "hypothesis",
                        "supporting_evidence_ids": ["fabricated"],
                        "counter_evidence_ids": [],
                        "counter_evidence_treatment": "NOT_APPLICABLE",
                        "missing_evidence": [],
                        "uncertainty": "uncertain",
                        "confidence_basis_points": 100,
                    }
                ],
            )
            body["choices"][0]["message"]["content"] = json.dumps(report)
        return httpx.Response(200, json=body)

    result = DeepSeekEvaluationProvider(
        "test-secret", events.append, transport=httpx.MockTransport(handle)
    ).diagnose("i1", OBSERVATIONS)
    assert result["status"] == "failed"
    assert result["error_code"] == expected
    assert len(events) == 2


def test_invalid_input_and_audit_failure_never_dispatch() -> None:
    with pytest.raises(ValueError):
        DeepSeekEvaluationProvider("", lambda event: None)
    provider = DeepSeekEvaluationProvider("test-secret", lambda event: None)
    for observations in ([], [{"unexpected": "x"}], [dict(OBSERVATIONS[0], summary="x" * 2049)]):
        with pytest.raises(ValueError):
            provider.diagnose("i1", observations)

    def unavailable(event: dict[str, Any]) -> None:
        raise OSError("audit unavailable")

    with pytest.raises(OSError):
        DeepSeekEvaluationProvider("test-secret", unavailable).diagnose("i1", OBSERVATIONS)
