"""Failures and unavailable usage remain visible in reported denominators."""

from __future__ import annotations

import pytest
from evaluation.summarize_nonhuman import metrics


def test_failures_do_not_disappear_from_quality_or_usage_denominators() -> None:
    result = metrics(
        [
            {
                "duration_ms": 100,
                "status": "validated",
                "top1_correct": True,
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
            },
            {"duration_ms": 60000, "status": "failed", "usage": None},
        ]
    )
    assert result["cases"] == 2 and result["validated"] == 1 and result["failed"] == 1
    assert result["top1_correct"] == 1
    assert result["metered_calls"] == 1
    assert result["p95_nearest_rank_ms"] == 60000
    assert result["cost_usd_upper_bound_for_metered_calls"] == "0.00042"
    with pytest.raises(ValueError):
        metrics([])
