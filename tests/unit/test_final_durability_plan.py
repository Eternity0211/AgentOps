from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

PLAN = Path("evaluation/durability/v2/plan.json")


def test_final_durability_plan_is_frozen_complete_and_source_bound() -> None:
    value = json.loads(PLAN.read_text(encoding="utf-8"))

    assert value["schema_version"] == "final-durability-plan/1.0.0"
    assert value["status"] == "FROZEN_BEFORE_MEASUREMENT"
    assert value["pair_count"] == len(value["treatments"]) == 8
    assert len({item["case_id"] for item in value["treatments"]}) == 8
    assert set(value["metrics"]) >= {
        "completion_rate",
        "duplicate_external_effects",
        "ambiguous_result_redispatches",
        "lost_evidence_records",
        "takeover_or_resume_latency_ms",
        "total_latency_ms",
        "model_calls",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "rate_card_upper_bound_nusd",
        "terminal_route",
    }
    assert value["acceptance"]["completed_pairs"] == 8
    assert value["acceptance"]["maximum_duplicate_external_effects"] == 0
    assert value["acceptance"]["maximum_ambiguous_result_redispatches"] == 0

    publication_revision = subprocess.check_output(
        [
            "git",
            "-c",
            "safe.directory=D:/AgentOps",
            "log",
            "-1",
            "--format=%H",
            "--",
            PLAN.as_posix(),
        ],
        text=True,
    ).strip()
    assert publication_revision
    for name, expected in value["source_bindings"].items():
        frozen = subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=D:/AgentOps",
                "show",
                f"{publication_revision}:{name}",
            ]
        )
        assert hashlib.sha256(frozen).hexdigest() == expected


def test_final_durability_plan_requires_control_treatment_and_delta_reporting() -> None:
    value = json.loads(PLAN.read_text(encoding="utf-8"))

    assert value["control"]["arm_id"] == "workflow-no-interruption"
    assert "control, treatment, absolute delta" in value["reporting"]["comparisons"]
    assert "never be called actual billing" in value["reporting"]["cost"]
    assert "never selectively rerun" in value["reporting"]["failures"]
