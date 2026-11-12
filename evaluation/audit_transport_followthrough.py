"""Audit repair follow-through and deterministic budget decisions after paired scoring."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation.outcome_ledger import OutcomeLedger


def _case_audit(events: list[dict[str, Any]], *, failed: bool) -> dict[str, int]:
    repair_succeeded = any(
        event.get("repair_attempt") == 1 and event.get("status") == "SUCCEEDED"
        for event in events
    )
    decisions = Counter(
        event.get("decision")
        for event in events
        if event.get("kind") == "model-budget-decision"
    )
    return {
        "successful_repair_outcomes": int(repair_succeeded),
        "failed_after_successful_repair": int(repair_succeeded and failed),
        "budget_allow_decisions": decisions["ALLOW"],
        "budget_handoff_decisions": decisions["HUMAN_HANDOFF"],
    }


def audit_followthrough(plan_path: Path, results: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("follow-through audit output already exists")
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    protocol_hash = hashlib.sha256(plan_bytes).hexdigest()
    expected = len(json.loads((Path(plan["dataset"]) / "index.json").read_text("utf-8"))) * len(
        plan["modes"]
    )
    summaries: dict[str, dict[str, int]] = {}
    for profile in plan["profiles"]:
        outcomes = OutcomeLedger(results / profile / "outcomes").collect(
            protocol_hash=protocol_hash
        )
        if len(outcomes) != expected:
            raise ValueError("paired profile outcome count mismatch")
        rows = []
        for outcome in outcomes:
            events_path = results / profile / outcome.mode / outcome.instance_id / "events.jsonl"
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            rows.append(_case_audit(events, failed=outcome.status == "FAILED"))
        summaries[profile] = {
            field: sum(row[field] for row in rows)
            for field in rows[0]
        }
    candidate = tuple(plan["profiles"])[1]
    threshold = plan["acceptance"].get("candidate_failed_outcomes_after_successful_repair")
    if type(threshold) is not int or threshold < 0:
        raise ValueError("missing repair follow-through acceptance threshold")
    passed = summaries[candidate]["failed_after_successful_repair"] <= threshold
    document = {
        "schema_version": "structured-transport-followthrough-audit/1.0.0",
        "protocol_sha256": protocol_hash,
        "profile_outcomes": {profile: expected for profile in plan["profiles"]},
        "profiles": summaries,
        "acceptance": {
            "candidate": candidate,
            "maximum_failed_outcomes_after_successful_repair": threshold,
            "passed": passed,
        },
        "authority": "SUPPLEMENTARY_POST_RUN_AUDIT_ONLY",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit_followthrough(args.plan, args.results, args.output)


if __name__ == "__main__":  # pragma: no cover
    main()
