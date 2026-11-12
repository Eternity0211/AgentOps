"""Candidate 1.6 publication is reproducible and keeps repair-induced failures visible."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.score_transport_pair import score_pair

ROOT = Path("evaluation/results/structured-reliability/v2")
RUN = ROOT / "run-001"
PLAN = Path("evaluation/real_protocol/v5/structured-transport-pair.json")


def test_candidate_1_6_score_recomputes(tmp_path: Path) -> None:
    expected = json.loads((RUN / "analysis/score.json").read_text(encoding="utf-8"))
    actual = score_pair(PLAN, RUN, tmp_path / "analysis")

    assert json.loads(json.dumps(actual)) == expected
    assert actual["profile_outcomes"] == {"baseline-1.5": 81, "candidate-1.6": 81}
    assert actual["acceptance"]["passed"] is True
    assert actual["acceptance"]["safe_controls_by_mode"] == {
        mode: {"baseline-1.5": 9, "candidate-1.6": 9}
        for mode in (
            "single-agent",
            "controlled-graph",
            "controlled-graph-simulated-memory",
        )
    }
    assert actual["audit"]["baseline-1.5"]["initial_schema_protocol_invalids"] == 9
    assert actual["audit"]["candidate-1.6"]["initial_schema_protocol_invalids"] == 4
    assert actual["audit"]["candidate-1.6"]["terminal_schema_protocol_invalids"] == 0


def test_candidate_1_6_post_repair_failures_remain_visible() -> None:
    score = json.loads((RUN / "analysis/score.json").read_text(encoding="utf-8"))
    assert score["paired_result"]["cost_latency_gate_passed"] is False
    assert {item["claim"] for item in score["paired_result"]["metrics"]} == {
        "NO_PROVEN_IMPROVEMENT"
    }

    counts: dict[str, int] = {}
    for profile in ("baseline-1.5", "candidate-1.6"):
        failed_after_repair = 0
        for outcome_path in (RUN / profile / "outcomes").glob("*.json"):
            outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
            if outcome["status"] != "FAILED":
                continue
            events_path = RUN / profile / outcome["mode"] / outcome["instance_id"] / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text().splitlines()]
            model_events = [
                event
                for event in events
                if event.get("purpose") and event.get("status") in ("SUCCEEDED", "FAILED")
            ]
            failed_after_repair += int(
                any(
                    event.get("repair_attempt") == 1 and event.get("status") == "SUCCEEDED"
                    for event in model_events
                )
                and model_events[-1]["status"] == "SUCCEEDED"
            )
        counts[profile] = failed_after_repair
    assert counts == {"baseline-1.5": 4, "candidate-1.6": 3}


def test_candidate_1_6_hash_manifest() -> None:
    expected = json.loads((ROOT / "file-hashes.json").read_text(encoding="utf-8"))
    actual = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "file-hashes.json"
    }
    assert actual == expected
