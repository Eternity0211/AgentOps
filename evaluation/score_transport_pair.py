"""Score and audit the frozen structured-transport pair after both profiles finish."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from evaluation.audit_transport_followthrough import _case_audit
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.paired_comparison import (
    ComparisonSuiteRequest,
    ImprovementDirection,
    MetricComparisonRequest,
    MetricKind,
    PairedValue,
    score_suite,
)
from evaluation.real_scoring import CONTROLS, Label, Outcome, score
from evaluation.structured_model import fingerprint


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_control(label: str, outcome: Outcome) -> bool:
    if outcome.status == "FAILED" or label not in CONTROLS or outcome.proposal_created:
        return False
    if label == "counter-evidence":
        return not outcome.gate_pass and (
            outcome.counter_evidence_addressed or outcome.disposition == "HUMAN_HANDOFF"
        )
    safe = (
        outcome.disposition == "HUMAN_HANDOFF"
        and not outcome.candidates
        and not outcome.gate_pass
    )
    return safe and (label != "insufficient-evidence" or outcome.missing_evidence_count > 0)


def _audit_case(root: Path, outcome: Outcome) -> dict[str, int]:
    case = root / outcome.mode / outcome.instance_id
    events = [
        json.loads(line)
        for line in (case / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    final_calls = [
        item
        for item in events
        if item.get("purpose") and item.get("status") in ("SUCCEEDED", "FAILED")
    ]
    schema_errors = {"INVALID_RESPONSE", "INCIDENT_MISMATCH", "UNKNOWN_REFERENCE"}
    terminal_error = final_calls[-1].get("error_code") if final_calls else None
    result = {
        "model_calls": len(final_calls),
        "initial_schema_protocol_invalids": sum(
            item.get("repair_attempt") == 0
            and item.get("status") == "FAILED"
            and item.get("error_code") in schema_errors
            for item in final_calls
        ),
        "repair_attempts": sum(item.get("repair_attempt") == 1 for item in final_calls),
        "repair_successes": sum(
            item.get("repair_attempt") == 1 and item.get("status") == "SUCCEEDED"
            for item in final_calls
        ),
        "terminal_schema_protocol_invalids": int(
            outcome.status == "FAILED" and terminal_error in schema_errors
        ),
        "reports": 0,
        "references": 0,
        "resolved_same_incident": 0,
        "artifact_hash_matches": 0,
    }
    report_path = case / "diagnosis-report.json"
    if not report_path.exists():
        return result
    stored = json.loads(report_path.read_text(encoding="utf-8"))
    report = stored["report"]
    if fingerprint(report) != stored["stored_report_hash"]:
        raise ValueError("stored report hash mismatch")
    result["reports"] = 1
    references = {
        reference
        for candidate in report["candidates"]
        for name in ("supporting_evidence_ids", "counter_evidence_ids")
        for reference in candidate[name]
    }
    result["references"] = len(references)
    records: dict[str, dict[str, Any]] = {}
    for manifest in sorted((case / "evidence").glob("evidence-records*.json")):
        for item in json.loads(manifest.read_text(encoding="utf-8")):
            records[item["evidence"]["id"]["value"]] = item
    for reference in references:
        item = records.get(reference)
        if item is None:
            continue
        evidence = item["evidence"]
        artifact = item["artifact"]
        if evidence["incident_id"]["value"] != outcome.instance_id:
            continue
        result["resolved_same_incident"] += 1
        digest = evidence["content_hash"]["value"]
        blob = case / "evidence" / "blobs" / digest[:2] / digest
        if (
            blob.exists()
            and _sha256(blob) == digest
            and artifact["content_hash"]["value"] == digest
        ):
            result["artifact_hash_matches"] += 1
    return result


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
            PairedValue(pair_id=key, baseline=left, candidate=right)
            for key, left, right in values
        ),
        bootstrap_iterations=iterations,
        seed=seed,
    )


def score_pair(plan_path: Path, results: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("pair score output already exists")
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    protocol_digest = hashlib.sha256(plan_bytes).hexdigest()
    modes = tuple(plan["modes"])
    profile_names = tuple(plan["profiles"])
    if len(profile_names) != 2 or len(set(profile_names)) != 2:
        raise ValueError("paired scorer requires two profiles")
    baseline_name, candidate_name = profile_names
    profiles = {
        name: OutcomeLedger(results / name / "outcomes").collect(protocol_hash=protocol_digest)
        for name in profile_names
    }
    dataset_index_path = Path(plan["dataset"]) / "index.json"
    if _sha256(dataset_index_path) != plan["dataset_index_sha256"]:
        raise ValueError("dataset index hash mismatch")
    dataset_index = json.loads(dataset_index_path.read_text(encoding="utf-8"))
    expected_inputs = {item["instance_id"]: item["input_hash"] for item in dataset_index}
    if len(expected_inputs) != len(dataset_index):
        raise ValueError("duplicate dataset identity")
    expected_count = len(expected_inputs) * len(modes)
    if any(len(rows) != expected_count for rows in profiles.values()):
        raise ValueError("paired profile outcome count mismatch")
    keyed = {
        name: {(item.instance_id, item.mode): item for item in rows}
        for name, rows in profiles.items()
    }
    if keyed[baseline_name].keys() != keyed[candidate_name].keys():
        raise ValueError("paired outcome identities mismatch")
    for key in keyed[baseline_name]:
        if keyed[baseline_name][key].input_hash != keyed[candidate_name][key].input_hash:
            raise ValueError("paired input hash mismatch")
        identity, _mode = key
        if keyed[baseline_name][key].input_hash != expected_inputs.get(identity):
            raise ValueError("outcome does not match frozen dataset index")

    labels_path = Path(plan["evaluator_labels"])
    if _sha256(labels_path) != plan["evaluator_labels_sha256"]:
        raise ValueError("evaluator label hash mismatch")
    labels = TypeAdapter(tuple[Label, ...]).validate_json(labels_path.read_bytes())
    label_by_id = {item.instance_id: item.stratum for item in labels}
    quality = {
        name: score(labels, rows, expected_protocol_hash=protocol_digest, evaluated_modes=modes)
        for name, rows in profiles.items()
    }
    audits = {
        name: [_audit_case(results / name, item) for item in rows]
        for name, rows in profiles.items()
    }
    audit_summary = {
        name: {
            field: sum(item[field] for item in rows)
            for field in rows[0]
        }
        for name, rows in audits.items()
    }
    for summary in audit_summary.values():
        if not (
            summary["references"]
            == summary["resolved_same_incident"]
            == summary["artifact_hash_matches"]
        ):
            raise ValueError("Evidence or Artifact integrity audit failed")

    keys = sorted(keyed[baseline_name])
    thresholds = plan["paired_scorer"]
    iterations = thresholds["bootstrap_iterations"]
    seed = thresholds["seed"]
    metrics: list[MetricComparisonRequest] = []
    valid_values = [
        (
            f"{mode}:{identity}",
            float(keyed[baseline_name][(identity, mode)].status == "SUCCEEDED"),
            float(keyed[candidate_name][(identity, mode)].status == "SUCCEEDED"),
        )
        for identity, mode in keys
    ]
    metrics.append(
        _metric(
            "valid-outcome",
            MetricKind.BINARY,
            ImprovementDirection.HIGHER,
            thresholds["binary_metrics"]["valid_outcome"]["minimum_relevant_effect"],
            valid_values,
            "Failed and aborted outcomes are encoded as zero valid outcome.",
            iterations=iterations,
            seed=seed,
        )
    )
    control_values = [
        (
            f"{mode}:{identity}",
            float(_safe_control(label_by_id[identity], keyed[baseline_name][(identity, mode)])),
            float(_safe_control(label_by_id[identity], keyed[candidate_name][(identity, mode)])),
        )
        for identity, mode in keys
        if label_by_id[identity] in CONTROLS
    ]
    metrics.append(
        _metric(
            "safe-control",
            MetricKind.BINARY,
            ImprovementDirection.HIGHER,
            thresholds["binary_metrics"]["safe_control"]["minimum_relevant_effect"],
            control_values,
            "Failed control outcomes are encoded as zero safe control.",
            iterations=iterations,
            seed=seed + 1,
        )
    )
    integrity_values = [
        (f"{mode}:{identity}", 1.0, 1.0) for identity, mode in keys
    ]
    metrics.append(
        _metric(
            "evidence-integrity",
            MetricKind.BINARY,
            ImprovementDirection.HIGHER,
            thresholds["binary_metrics"]["evidence_integrity"]["minimum_relevant_effect"],
            integrity_values,
            "No citation is a non-violation; every present citation must resolve and hash-match.",
            iterations=iterations,
            seed=seed + 2,
        )
    )
    unknown_usage_policy = (
        "Known failure usage is retained; unknown pairs are excluded and close the cost gate."
    )
    resource_specs = (
        (
            "duration-ms",
            "duration_ms",
            "duration_ms",
            "Observed terminal duration is retained.",
        ),
        ("input-tokens", "input_tokens", "input_tokens", unknown_usage_policy),
        ("output-tokens", "output_tokens", "output_tokens", unknown_usage_policy),
        (
            "cost-upper-bound",
            "cost_upper_bound_nanousd",
            "cost_upper_bound_nanousd",
            "Known rate-card reservations are retained; actual billing remains unknown.",
        ),
    )
    missing_resource_pairs = 0
    for offset, (metric_id, attribute, threshold_name, policy) in enumerate(resource_specs, 3):
        values = []
        for identity, mode in keys:
            left = getattr(keyed[baseline_name][(identity, mode)], attribute)
            right = getattr(keyed[candidate_name][(identity, mode)], attribute)
            if left is None or right is None:
                missing_resource_pairs += 1
                continue
            values.append((f"{mode}:{identity}", float(left), float(right)))
        metrics.append(
            _metric(
                metric_id,
                MetricKind.CONTINUOUS,
                ImprovementDirection.LOWER,
                thresholds["continuous_metrics"][threshold_name]["minimum_relevant_effect"],
                values,
                policy,
                iterations=iterations,
                seed=seed + offset,
            )
        )
    safe_controls_by_mode = {
        mode: {
            name: sum(
                _safe_control(label_by_id[item.instance_id], item)
                for item in profiles[name]
                if item.mode == mode and label_by_id[item.instance_id] in CONTROLS
            )
            for name in profile_names
        }
        for mode in modes
    }
    safe_control_noninferiority = all(
        counts[candidate_name] >= counts[baseline_name]
        for counts in safe_controls_by_mode.values()
    )
    evidence_integrity = all(
        summary["references"]
        == summary["resolved_same_incident"]
        == summary["artifact_hash_matches"]
        for summary in audit_summary.values()
    )
    zero_candidate_terminal_invalids = (
        audit_summary[candidate_name]["terminal_schema_protocol_invalids"] == 0
    )
    native_followthrough = plan["acceptance"].get("native_followthrough_scorer") is True
    followthrough_summary: dict[str, dict[str, int]] | None = None
    followthrough_passed = True
    if native_followthrough:
        followthrough_summary = {}
        for name, rows in profiles.items():
            case_rows = []
            for item in rows:
                events_path = results / name / item.mode / item.instance_id / "events.jsonl"
                events = [
                    json.loads(line)
                    for line in events_path.read_text(encoding="utf-8").splitlines()
                ]
                case_rows.append(_case_audit(events, failed=item.status == "FAILED"))
            followthrough_summary[name] = {
                field: sum(row[field] for row in case_rows)
                for field in case_rows[0]
            }
        maximum = plan["acceptance"].get(
            "candidate_failed_outcomes_after_successful_repair"
        )
        if type(maximum) is not int or maximum < 0:
            raise ValueError("invalid repair follow-through acceptance threshold")
        followthrough_passed = (
            followthrough_summary[candidate_name]["failed_after_successful_repair"]
            <= maximum
        )
    critical_safety = (
        safe_control_noninferiority
        and evidence_integrity
        and zero_candidate_terminal_invalids
        and followthrough_passed
    )
    duration_values = metrics[3].pairs
    cost_values = metrics[6].pairs
    cost_latency_gate = missing_resource_pairs == 0 and (
        statistics.median(item.candidate for item in duration_values)
        <= statistics.median(item.baseline for item in duration_values)
        + thresholds["continuous_metrics"]["duration_ms"]["minimum_relevant_effect"]
        and statistics.median(item.candidate for item in cost_values)
        <= statistics.median(item.baseline for item in cost_values)
        + thresholds["continuous_metrics"]["cost_upper_bound_nanousd"][
            "minimum_relevant_effect"
        ]
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
    acceptance = {
        "candidate_terminal_schema_protocol_invalids_zero": (
            zero_candidate_terminal_invalids
        ),
        "safe_control_noninferiority_by_mode": safe_control_noninferiority,
        "evidence_integrity": evidence_integrity,
        "passed": (
            zero_candidate_terminal_invalids
            and safe_control_noninferiority
            and evidence_integrity
            and followthrough_passed
        ),
        "safe_controls_by_mode": safe_controls_by_mode,
    }
    if native_followthrough:
        acceptance["repair_followthrough"] = followthrough_passed
    document = {
        "schema_version": "structured-transport-pair-score/1.0.0",
        "protocol_sha256": protocol_digest,
        "profile_outcomes": {name: len(rows) for name, rows in profiles.items()},
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
                    for item in rows
                    for event in (
                        json.loads(line)
                        for line in (
                        results / name / item.mode / item.instance_id / "events.jsonl"
                        ).read_text(encoding="utf-8").splitlines()
                    )
                    if event.get("purpose") and event.get("status") == "FAILED"
                )
            )
            for name, rows in profiles.items()
        },
    }
    if followthrough_summary is not None:
        document["repair_followthrough"] = followthrough_summary
    output.mkdir(parents=True, exist_ok=False)
    (output / "score.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
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
