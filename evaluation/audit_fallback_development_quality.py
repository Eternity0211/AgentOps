"""Post-run exploratory paired quality audit of the FC4f development pair."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from evaluation.outcome_ledger import OutcomeLedger
from evaluation.paired_comparison import (
    ComparisonSuiteRequest,
    ImprovementDirection,
    MetricComparisonRequest,
    MetricKind,
    PairedValue,
    score_suite,
)
from evaluation.real_scoring import CAUSES, Label


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(plan_path: Path, results: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("development quality audit already exists")
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    if plan.get("schema_version") != "diagnosis-fallback-development-pair/1.0.0":
        raise ValueError("unknown development quality protocol")
    protocol_hash = hashlib.sha256(plan_bytes).hexdigest()
    index_path = Path(plan["dataset"]) / "index.json"
    labels_path = Path(plan["evaluator_labels"])
    if _sha256(index_path) != plan["dataset_index_sha256"]:
        raise ValueError("development input index drift")
    expected = {
        item["instance_id"]: item["input_hash"]
        for item in json.loads(index_path.read_text(encoding="utf-8"))
    }
    if len(expected) != plan["expected_cases"]:
        raise ValueError("development case count mismatch")
    arms = tuple(plan["profiles"])
    if len(arms) != 2:
        raise ValueError("development arm count mismatch")
    outcomes = {
        arm: OutcomeLedger(results / arm / "outcomes").collect(protocol_hash=protocol_hash)
        for arm in arms
    }
    keyed = {arm: {item.instance_id: item for item in rows} for arm, rows in outcomes.items()}
    if any(
        len(rows) != len(expected) or set(keyed[arm]) != set(expected)
        for arm, rows in outcomes.items()
    ):
        raise ValueError("incomplete development outcome pair")
    if any(
        item.input_hash != expected[item.instance_id] or item.mode != "controlled-graph"
        for rows in outcomes.values()
        for item in rows
    ):
        raise ValueError("development outcome input or mode mismatch")
    if _sha256(labels_path) != plan["evaluator_labels_sha256"]:
        raise ValueError("development label drift")
    labels = TypeAdapter(tuple[Label, ...]).validate_json(labels_path.read_bytes())
    by_id = {label.instance_id: label.stratum for label in labels}
    if len(by_id) != len(expected) or set(by_id) != set(expected):
        raise ValueError("development label identities mismatch")
    metrics = []
    counts: dict[str, dict[str, int]] = {}
    for top_k in (1, 3):
        pairs = tuple(
            PairedValue(
                pair_id=identity,
                baseline=float(
                    keyed[arms[0]][identity].status == "SUCCEEDED"
                    and by_id[identity] in keyed[arms[0]][identity].candidates[:top_k]
                ),
                candidate=float(
                    keyed[arms[1]][identity].status == "SUCCEEDED"
                    and by_id[identity] in keyed[arms[1]][identity].candidates[:top_k]
                ),
            )
            for identity in sorted(by_id)
            if by_id[identity] in CAUSES
        )
        counts[f"top{top_k}"] = {
            "baseline": int(sum(pair.baseline for pair in pairs)),
            "candidate": int(sum(pair.candidate for pair in pairs)),
            "denominator": len(pairs),
        }
        metrics.append(
            MetricComparisonRequest(
                metric_id=f"exploratory-top{top_k}",
                kind=MetricKind.BINARY,
                direction=ImprovementDirection.HIGHER,
                minimum_relevant_effect=0.15 if top_k == 1 else 0.05,
                failure_policy="Failed outcomes count as incorrect; no selective reruns.",
                pairs=pairs,
                bootstrap_iterations=10_000,
                seed=2026112301 + top_k,
            )
        )
    result = score_suite(
        ComparisonSuiteRequest(
            schema_version="paired-comparison-request/1.0.0",
            suite_id="fc4f2b-postrun-exploratory-quality",
            confidence_level=0.95,
            critical_safety_gate_passed=False,
            cost_latency_gate_passed=False,
            metrics=tuple(metrics),
        )
    )
    fallback_counts = {}
    for arm in arms:
        fallback_counts[arm] = sum(
            json.loads(line).get("kind") == "terminal-diagnosis-fallback"
            for item in outcomes[arm]
            for line in (results / arm / item.mode / item.instance_id / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
    document = {
        "schema_version": "fallback-development-quality-audit/1.0.0",
        "protocol_sha256": protocol_hash,
        "status": "POSTRUN_EXPLORATORY_NOT_CONFIRMATORY",
        "counts": counts,
        "fallback_events": fallback_counts,
        "paired_result": result.model_dump(mode="json"),
        "interpretation": (
            "The two profiles differ only after terminal repairable DIAGNOSE invalidity. "
            "Zero observed fallback events prevent attributing the measured quality or "
            "resource discordance to that fallback."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.plan, args.results, args.output)


if __name__ == "__main__":  # pragma: no cover
    main()
