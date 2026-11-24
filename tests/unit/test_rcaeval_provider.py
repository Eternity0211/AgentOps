from __future__ import annotations

import json
from typing import Any

import httpx
from evaluation.rcaeval_features import FeatureArm, LocalizationContext, ServiceFeature
from evaluation.rcaeval_provider import RcaEvalLocalizationProvider


def context() -> LocalizationContext:
    return LocalizationContext(
        case_id="re2-ob-0123456789abcdef",
        arm=FeatureArm.CANDIDATE,
        candidate_services=("alpha", "bravo", "charlie", "delta", "echo"),
        features=tuple(
            ServiceFeature(
                service=service,
                metric_after_mean=1.0,
                metric_delta=8.0 if service == "charlie" else 0.0,
                log_after_count=2 if service == "charlie" else 0,
                log_delta=2 if service == "charlie" else 0,
                trace_after_count=2 if service == "charlie" else 0,
                trace_delta=2 if service == "charlie" else 0,
                error_after_count=2 if service == "charlie" else 0,
                error_delta=2 if service == "charlie" else 0,
                duration_after_mean=20.0 if service == "charlie" else None,
                duration_delta=None,
            )
            for service in ("alpha", "bravo", "charlie", "delta", "echo")
        ),
        missing_modalities=(),
        truncated_queries=0,
        tool_calls=14,
    )


def _body(content: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": "deepseek-flash",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps(content)},
            }
        ],
    }


def test_provider_validates_service_binding_and_records_content_free_audit() -> None:
    events: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json=_body(
                {
                    "schema_version": "service-localization-output/1.0.0",
                    "case_id": "re2-ob-0123456789abcdef",
                    "ranked_services": ["charlie", "alpha", "bravo"],
                }
            ),
        )

    result = RcaEvalLocalizationProvider(
        "test-key", events.append, transport=httpx.MockTransport(handler)
    ).invoke(context())

    assert result.output is not None
    assert result.output.ranked_services[0] == "charlie"
    assert result.failure_reason is None
    assert result.model_calls == 1
    assert result.input_tokens == 100
    assert result.output_tokens == 20
    assert result.cost_upper_bound_nanousd == 54_000
    serialized = json.dumps(events)
    assert "test-key" not in serialized
    assert "telemetry_features" not in serialized


def test_provider_repairs_invalid_output_once() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = (
            {"bad": "schema"}
            if calls == 1
            else {
                "schema_version": "service-localization-output/1.0.0",
                "case_id": "re2-ob-0123456789abcdef",
                "ranked_services": ["charlie"],
            }
        )
        return httpx.Response(200, json=_body(content))

    result = RcaEvalLocalizationProvider(
        "test-key", lambda _: None, transport=httpx.MockTransport(handler)
    ).invoke(context())

    assert result.output is not None
    assert result.model_calls == 2
    assert result.input_tokens == 200
    assert result.output_tokens == 40
    assert result.cost_upper_bound_nanousd == 108_000


def test_provider_fails_closed_on_unknown_service_after_repair() -> None:
    result = RcaEvalLocalizationProvider(
        "test-key",
        lambda _: None,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=_body(
                    {
                        "schema_version": "service-localization-output/1.0.0",
                        "case_id": "re2-ob-0123456789abcdef",
                        "ranked_services": ["not-allowed"],
                    }
                ),
            )
        ),
    ).invoke(context())

    assert result.output is None
    assert result.failure_reason == "INVALID_OUTPUT"
    assert result.model_calls == 2
