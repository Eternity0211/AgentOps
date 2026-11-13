from __future__ import annotations

from pathlib import Path

from evaluation.contracts import load_json_object
from evaluation.run_final_security import _load_plan, compare

PLAN = Path("evaluation/security/v2/plan.json")
ROOT = Path("evaluation/results/final-security/v1/run-001")


def test_published_final_security_recomputes_from_both_junit_arms() -> None:
    plan, fingerprint = _load_plan(PLAN)
    result = load_json_object(ROOT / "result.json")
    recomputed = compare(
        plan,
        Path(plan["baseline_junit"]),
        ROOT / "candidate-junit.xml",
    )

    assert result == recomputed | {
        "plan_sha256": fingerprint,
        "candidate_revision": "a24b0f19c0be8aa5f86d434275e7a1ead3be269d",
        "baseline_revision": "7813bae",
    }
    assert result["accepted"] is True
    assert result["metrics"]["baseline"]["route_correctness"] == [13, 13]
    assert result["metrics"]["candidate"]["route_correctness"] == [13, 13]
    assert result["deltas"]["route_correctness"]["absolute_rate_delta"] == 0
    assert result["metrics"]["candidate"]["critical_failures"] == 0
