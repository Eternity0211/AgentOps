"""Label-free FC4f development audit for terminal validity and graph overhead."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

import httpx

from evaluation.outcome_ledger import OutcomeLedger
from evaluation.structured_model import (
    ModelPurpose,
    StructuredEvaluationModel,
    StructuredModelFailure,
    StructuredTransportProfile,
)

ROOT = Path(__file__).resolve().parents[1]
MODES = ("single-agent", "controlled-graph")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile_95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _valid_report() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "report_id": "development-audit-report",
        "incident_id": "development-audit-incident",
        "disposition": "HUMAN_HANDOFF",
        "candidates": [],
        "missing_evidence": ["A valid structured diagnosis was not available."],
        "explanation": "Deterministic development fixture.",
    }


def _provider_body(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 100,
            "total_tokens": 200,
            "prompt_cache_hit_tokens": 0,
        },
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps(output)},
            }
        ],
    }


def _terminal_failure_fixture() -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    invalid = _valid_report() | {"explanation": "x" * 513}
    model = StructuredEvaluationModel(
        "development-only",
        events.append,
        max_calls=2,
        profile=StructuredTransportProfile.CANDIDATE_1_11,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_provider_body(invalid))
        ),
    )
    failure_code = None
    try:
        model.invoke(
            ModelPurpose.DIAGNOSE,
            {"incident_id": "development-audit-incident", "evidence_ids": []},
        )
    except StructuredModelFailure as error:
        failure_code = str(error)
    completed = [event for event in events if event.get("status") == "FAILED"]
    usage = [event["usage"] for event in completed]
    return {
        "failure_code": failure_code,
        "model_calls": len(completed),
        "repair_attempts": sum(event.get("repair_attempt") == 1 for event in completed),
        "input_tokens": sum(item["prompt_tokens"] for item in usage),
        "output_tokens": sum(item["completion_tokens"] for item in usage),
        "cost_upper_bound_nanousd": sum(
            item["prompt_tokens"] * 300 + item["completion_tokens"] * 1200 for item in usage
        ),
        "terminal_valid_output": False,
    }


def _event_counts(path: Path) -> dict[str, int]:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return {
        "model_calls": sum(
            event.get("status") == "STARTED" and "purpose" in event for event in events
        ),
        "tool_calls": sum(event.get("event_type") == "tool.call_started" for event in events),
    }


def _resource_audit(plan: dict[str, Any]) -> dict[str, Any]:
    archive = ROOT / plan["development_archive"]
    outcomes = OutcomeLedger(archive / "outcomes").collect(
        protocol_hash=plan["development_protocol_sha256"]
    )
    indexed = {(outcome.mode, outcome.instance_id): outcome for outcome in outcomes}
    identities = sorted(identity for mode, identity in indexed if mode == "single-agent")
    if len(identities) != plan["expected_pairs"] or any(
        (mode, identity) not in indexed for mode in MODES for identity in identities
    ):
        raise ValueError("development resource pair mismatch")
    metric_names = (
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "cost_upper_bound_nanousd",
        "model_calls",
        "tool_calls",
    )
    rows: dict[str, dict[str, list[int]]] = {
        mode: {metric: [] for metric in metric_names} for mode in MODES
    }
    for identity in identities:
        for mode in MODES:
            outcome = indexed[(mode, identity)]
            if outcome.status != "SUCCEEDED":
                raise ValueError("development resource outcome failed")
            counts = _event_counts(archive / mode / identity / "events.jsonl")
            values = {
                "duration_ms": outcome.duration_ms,
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
                "cost_upper_bound_nanousd": outcome.cost_upper_bound_nanousd,
                **counts,
            }
            for metric, value in values.items():
                if type(value) is not int:
                    raise ValueError("development resource value unavailable")
                rows[mode][metric].append(value)
    metrics: dict[str, Any] = {}
    for metric in metric_names:
        baseline = rows["single-agent"][metric]
        candidate = rows["controlled-graph"][metric]
        metrics[metric] = {
            "single_agent_median": statistics.median(baseline),
            "controlled_graph_median": statistics.median(candidate),
            "median_delta": statistics.median(candidate) - statistics.median(baseline),
            "single_agent_p95": _percentile_95(baseline),
            "controlled_graph_p95": _percentile_95(candidate),
            "p95_delta": _percentile_95(candidate) - _percentile_95(baseline),
        }
    return {"pair_count": len(identities), "metrics": metrics}


def audit(plan_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "final-diagnosis-optimization-audit/1.0.0":
        raise ValueError("unknown optimization audit plan")
    if any(_sha256(ROOT / path) != digest for path, digest in plan["source_hashes"].items()):
        raise ValueError("optimization audit source drift")
    if _sha256(ROOT / plan["archive_manifest"]) != plan["archive_manifest_sha256"]:
        raise ValueError("optimization audit archive drift")
    if plan.get("label_access") != "FORBIDDEN" or plan.get("run_count") != 1:
        raise ValueError("optimization audit isolation mismatch")
    return {
        "schema_version": "final-diagnosis-optimization-audit-result/1.0.0",
        "plan_sha256": _sha256(plan_path),
        "label_access": "NONE",
        "terminal_failure_fixture": _terminal_failure_fixture(),
        "development_resource_audit": _resource_audit(plan),
    }


def write_result(plan_path: Path, output: Path) -> Path:
    result = audit(plan_path)
    output.mkdir(parents=True, exist_ok=False)
    destination = output / "audit.json"
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_result(args.plan, args.output)


if __name__ == "__main__":  # pragma: no cover
    main()
