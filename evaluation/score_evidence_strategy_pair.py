"""Score the frozen FC4 evidence-strategy development pair with quality deltas."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
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
from evaluation.real_scoring import CAUSES, CONTROLS, Label, Outcome, score
from evaluation.score_transport_pair import _audit_case, _safe_control


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric(
    identifier: str,
    kind: MetricKind,
    direction: ImprovementDirection,
    minimum: float,
    values: list[tuple[str, float, float]],
    failure_policy: str,
    *,
    iterations: int,
    seed: int,
) -> MetricComparisonRequest:
    return MetricComparisonRequest(
        metric_id=identifier,
        kind=kind,
        direction=direction,
        minimum_relevant_effect=minimum,
        failure_policy=failure_policy,
        pairs=tuple(
            PairedValue(pair_id=identity, baseline=baseline, candidate=candidate)
            for identity, baseline, candidate in values
        ),
        bootstrap_iterations=iterations,
        seed=seed,
    )


def _load_pair(
    plan: dict[str, Any], plan_digest: str, results: Path
) -> tuple[
    tuple[str, str],
    dict[str, tuple[Outcome, ...]],
    dict[str, dict[str, Outcome]],
    tuple[Label, ...],
]:
    arm_names = tuple(plan["profiles"])
    if len(arm_names) != 2 or tuple(plan["arms"]) != arm_names:
        raise ValueError("pair arm order mismatch")
    profiles = {
        name: OutcomeLedger(results / name / "outcomes").collect(protocol_hash=plan_digest)
        for name in arm_names
    }
    index_path = Path(plan["dataset"]) / "index.json"
    if _sha256(index_path) != plan["dataset_index_sha256"]:
        raise ValueError("dataset index hash mismatch")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    expected_inputs = {item["instance_id"]: item["input_hash"] for item in index}
    expected_count = len(expected_inputs)
    if expected_count != 27 or any(len(rows) != expected_count for rows in profiles.values()):
        raise ValueError("paired outcome count mismatch")
    keyed = {name: {row.instance_id: row for row in rows} for name, rows in profiles.items()}
    if any(set(rows) != set(expected_inputs) for rows in keyed.values()):
        raise ValueError("paired outcome identities mismatch")
    for identity, expected_hash in expected_inputs.items():
        if any(rows[identity].input_hash != expected_hash for rows in keyed.values()):
            raise ValueError("paired input hash mismatch")
        if any(rows[identity].mode != "controlled-graph" for rows in keyed.values()):
            raise ValueError("unexpected development pair mode")

    labels_path = Path(plan["evaluator_labels"])
    if _sha256(labels_path) != plan["evaluator_labels_sha256"]:
        raise ValueError("evaluator label hash mismatch")
    labels = TypeAdapter(tuple[Label, ...]).validate_json(labels_path.read_bytes())
    if {item.instance_id for item in labels} != set(expected_inputs):
        raise ValueError("evaluator label identities mismatch")
    return (arm_names[0], arm_names[1]), profiles, keyed, labels


def _render(document: dict[str, Any]) -> str:
    lines = [
        "# Evidence-strategy development comparison",
        "",
        "This is a complete paired development result, not the untouched FC4 confirmatory run.",
        "",
        "| Metric | Baseline | Candidate | Delta | 95% interval | Claim |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for metric in document["paired_result"]["metrics"]:
        estimate = metric["estimates"][0]
        interval = estimate["absolute_delta_interval"]
        lines.append(
            f"| `{metric['metric_id']}` | {estimate['baseline']:.6g} | "
            f"{estimate['candidate']:.6g} | {estimate['absolute_delta']:+.6g} | "
            f"[{interval['lower']:.6g}, {interval['upper']:.6g}] | "
            f"{metric['claim']} |"
        )
    acceptance = document["acceptance"]
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Acceptance passed: `{str(acceptance['passed']).lower()}`",
            f"- Baseline Top-1 correct: {acceptance['top1_correct']['baseline']}",
            f"- Candidate Top-1 correct: {acceptance['top1_correct']['candidate']}",
            f"- Top-1 correct gain: {acceptance['top1_correct']['gain']:+d}",
            "- All failures, handoffs and unknown resource values remain in the publication.",
            "",
        ]
    )
    return "\n".join(lines)


def score_pair(plan_path: Path, results: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("evidence-strategy score output already exists")
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    plan_digest = hashlib.sha256(plan_bytes).hexdigest()
    (baseline_name, candidate_name), profiles, keyed, labels = _load_pair(
        plan, plan_digest, results
    )
    label_by_id = {item.instance_id: item.stratum for item in labels}
    quality = {
        name: score(
            labels,
            rows,
            expected_protocol_hash=plan_digest,
            evaluated_modes=("controlled-graph",),
        )
        for name, rows in profiles.items()
    }
    audits = {
        name: [_audit_case(results / name, row) for row in rows] for name, rows in profiles.items()
    }
    audit_summary = {
        name: {field: sum(row[field] for row in rows) for field in rows[0]}
        for name, rows in audits.items()
    }
    evidence_integrity = all(
        summary["references"]
        == summary["resolved_same_incident"]
        == summary["artifact_hash_matches"]
        for summary in audit_summary.values()
    )
    if not evidence_integrity:
        raise ValueError("Evidence or Artifact integrity audit failed")

    thresholds = plan["paired_scorer"]
    iterations, seed = thresholds["bootstrap_iterations"], thresholds["seed"]
    identities = sorted(label_by_id)
    metrics: list[MetricComparisonRequest] = []

    def binary_values(kind: str) -> list[tuple[str, float, float]]:
        values = []
        for identity in identities:
            label = label_by_id[identity]
            before, after = keyed[baseline_name][identity], keyed[candidate_name][identity]
            if kind == "top1" and label in CAUSES:
                left = before.status == "SUCCEEDED" and before.candidates[:1] == (label,)
                right = after.status == "SUCCEEDED" and after.candidates[:1] == (label,)
            elif kind == "top3" and label in CAUSES:
                left = before.status == "SUCCEEDED" and label in before.candidates[:3]
                right = after.status == "SUCCEEDED" and label in after.candidates[:3]
            elif kind == "safe_control" and label in CONTROLS:
                left = _safe_control(label, before)
                right = _safe_control(label, after)
            elif kind == "valid":
                left, right = before.status == "SUCCEEDED", after.status == "SUCCEEDED"
            elif kind == "integrity":
                left = right = True
            else:
                continue
            values.append((identity, float(left), float(right)))
        return values

    binary_specs = (
        ("top1", "top1", "Failed fault outcomes are encoded as incorrect Top-1."),
        ("top3", "top3", "Failed fault outcomes are encoded as incorrect Top-3."),
        ("safe-control", "safe_control", "Failed controls are encoded as unsafe."),
        ("valid-outcome", "valid", "Failed outcomes are encoded as invalid."),
        (
            "evidence-integrity",
            "integrity",
            "No citation is a non-violation; every citation must resolve and hash-match.",
        ),
    )
    for offset, (metric_id, key, policy) in enumerate(binary_specs):
        metrics.append(
            _metric(
                metric_id,
                MetricKind.BINARY,
                ImprovementDirection.HIGHER,
                thresholds["binary_metrics"][key]["minimum_relevant_effect"],
                binary_values(key),
                policy,
                iterations=iterations,
                seed=seed + offset,
            )
        )

    missing_resource_pairs = 0
    resources = (
        ("duration-ms", "duration_ms", "duration_ms"),
        ("input-tokens", "input_tokens", "input_tokens"),
        ("output-tokens", "output_tokens", "output_tokens"),
        ("cost-upper-bound", "cost_upper_bound_nanousd", "cost_upper_bound_nanousd"),
    )
    for offset, (metric_id, attribute, threshold_key) in enumerate(resources, len(metrics)):
        values = []
        for identity in identities:
            left = getattr(keyed[baseline_name][identity], attribute)
            right = getattr(keyed[candidate_name][identity], attribute)
            if left is None or right is None:
                missing_resource_pairs += 1
                continue
            values.append((identity, float(left), float(right)))
        metrics.append(
            _metric(
                metric_id,
                MetricKind.CONTINUOUS,
                ImprovementDirection.LOWER,
                thresholds["continuous_metrics"][threshold_key]["minimum_relevant_effect"],
                values,
                "Unknown paired resource values are excluded and close the cost gate.",
                iterations=iterations,
                seed=seed + offset,
            )
        )

    top1_counts = {
        "baseline": sum(item.baseline for item in metrics[0].pairs),
        "candidate": sum(item.candidate for item in metrics[0].pairs),
    }
    top3_counts = {
        "baseline": sum(item.baseline for item in metrics[1].pairs),
        "candidate": sum(item.candidate for item in metrics[1].pairs),
    }
    safe_counts = {
        "baseline": sum(item.baseline for item in metrics[2].pairs),
        "candidate": sum(item.candidate for item in metrics[2].pairs),
    }
    candidate_failures = sum(row.status == "FAILED" for row in profiles[candidate_name])
    critical_safety = (
        evidence_integrity
        and safe_counts["candidate"] >= safe_counts["baseline"]
        and candidate_failures == 0
        and audit_summary[candidate_name]["terminal_schema_protocol_invalids"] == 0
    )
    duration_pairs, cost_pairs = metrics[5].pairs, metrics[8].pairs
    cost_latency_gate = missing_resource_pairs == 0 and (
        statistics.median(item.candidate for item in duration_pairs)
        <= statistics.median(item.baseline for item in duration_pairs)
        + thresholds["continuous_metrics"]["duration_ms"]["minimum_relevant_effect"]
        and statistics.median(item.candidate for item in cost_pairs)
        <= statistics.median(item.baseline for item in cost_pairs)
        + thresholds["continuous_metrics"]["cost_upper_bound_nanousd"]["minimum_relevant_effect"]
    )
    request = ComparisonSuiteRequest(
        schema_version="paired-comparison-request/1.0.0",
        suite_id=plan["protocol_id"],
        confidence_level=0.95,
        critical_safety_gate_passed=critical_safety,
        cost_latency_gate_passed=cost_latency_gate,
        metrics=tuple(metrics),
    )
    paired_result = score_suite(request)
    gain = int(top1_counts["candidate"] - top1_counts["baseline"])
    acceptance = {
        "top1_correct": {
            "baseline": int(top1_counts["baseline"]),
            "candidate": int(top1_counts["candidate"]),
            "gain": gain,
        },
        "top3_noninferior": top3_counts["candidate"] >= top3_counts["baseline"],
        "safe_control_noninferior": safe_counts["candidate"] >= safe_counts["baseline"],
        "candidate_failures_zero": candidate_failures == 0,
        "candidate_terminal_schema_protocol_invalids_zero": (
            audit_summary[candidate_name]["terminal_schema_protocol_invalids"] == 0
        ),
        "evidence_integrity": evidence_integrity,
        "cost_latency_gate": cost_latency_gate,
        "passed": (
            gain >= plan["acceptance"]["minimum_top1_correct_gain"]
            and top3_counts["candidate"] >= top3_counts["baseline"]
            and critical_safety
            and cost_latency_gate
        ),
    }
    document = {
        "schema_version": "evidence-strategy-pair-score/1.0.0",
        "protocol_sha256": plan_digest,
        "arm_outcomes": {name: len(rows) for name, rows in profiles.items()},
        "quality": quality,
        "audit": audit_summary,
        "acceptance": acceptance,
        "missing_resource_pairs": missing_resource_pairs,
        "paired_request": request.model_dump(mode="json"),
        "paired_result": paired_result.model_dump(mode="json"),
        "provider_error_codes": {
            name: dict(
                Counter(
                    event.get("error_code") or "UNCLASSIFIED"
                    for row in rows
                    for event in (
                        json.loads(line)
                        for line in (results / name / row.mode / row.instance_id / "events.jsonl")
                        .read_text(encoding="utf-8")
                        .splitlines()
                    )
                    if event.get("purpose") and event.get("status") == "FAILED"
                )
            )
            for name, rows in profiles.items()
        },
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "score.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "README.md").write_text(_render(document), encoding="utf-8")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    score_pair(args.plan, args.results, args.output)


if __name__ == "__main__":  # pragma: no cover
    main()
