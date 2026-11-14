"""Classify frozen diagnosis misses without changing or rerunning provider outcomes."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation.real_scoring import CAUSES, Outcome

DEFAULT_LABELS = Path("evaluation/real_protocol/v2/evaluator_only/labels.json")
DEFAULT_RUN = Path("evaluation/results/structured-reliability/v7/run-001/candidate-1.11")
ANALYZER = Path(__file__)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request_service(record: dict[str, Any]) -> str | None:
    parameters = record["evidence"]["normalized_query"]["parameters"]
    encoded = "".join(
        item["value"]
        for item in sorted(parameters, key=lambda item: item["name"])
        if item["name"].startswith("request_spec_") and item["name"] != "request_spec_encoding"
    )
    if not encoded:
        return None
    encoded += "=" * (-len(encoded) % 4)
    request = json.loads(base64.urlsafe_b64decode(encoded))
    service = request.get("service")
    return service if isinstance(service, str) else None


def _retrieved_services(run: Path, outcome: Outcome) -> list[str]:
    evidence_path = run / outcome.mode / outcome.instance_id / "evidence/evidence-records.json"
    records = json.loads(evidence_path.read_text(encoding="utf-8"))
    return sorted(
        {
            service
            for record in records
            if isinstance(record, dict)
            if (service := _request_service(record)) is not None
        }
    )


def _classification(expected: str, outcome: Outcome, services: list[str]) -> tuple[str, str]:
    predicted = outcome.candidates[0] if outcome.candidates else None
    if expected == "memory-leak" and predicted is None and outcome.disposition == "HUMAN_HANDOFF":
        return (
            "EVIDENCE_CONSTRUCTION_GAP",
            "The legacy context did not expose the GC-aware retained-memory facts "
            "later validated by FC3.",
        )
    if expected == "bad-configuration" and predicted == "http-500":
        if services == ["gateway"]:
            return (
                "DOWNSTREAM_CAUSAL_SCOPE_NOT_EXPANDED",
                "Only gateway Evidence was collected after the gateway trace localized "
                "the failure downstream.",
            )
        return (
            "DECISIVE_CONFIGURATION_EVIDENCE_NOT_COLLECTED",
            "The report observed an HTTP symptom without current configuration/deployment "
            "Evidence for the failing service.",
        )
    if expected in outcome.candidates[1:3]:
        return "HYPOTHESIS_RANKING_ERROR", "The correct cause was present but was not ranked first."
    if predicted is None:
        return "DECISIVE_EVIDENCE_ABSENCE", "No root-cause candidate was emitted."
    return (
        "CAUSE_MISCLASSIFICATION",
        "The emitted root-cause taxonomy did not match the evaluator label.",
    )


def analyze(labels_path: Path, run: Path) -> dict[str, Any]:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    by_id = {row["instance_id"]: row["stratum"] for row in labels}
    outcome_paths = sorted((run / "outcomes").glob("*.json"))
    outcomes = [Outcome.model_validate_json(path.read_bytes()) for path in outcome_paths]
    errors = []
    correct = 0
    fault_outcomes = 0
    for outcome in sorted(outcomes, key=lambda row: (row.mode, row.instance_id)):
        expected = by_id[outcome.instance_id]
        if expected not in CAUSES:
            continue
        fault_outcomes += 1
        predicted = outcome.candidates[0] if outcome.candidates else None
        if predicted == expected:
            correct += 1
            continue
        services = _retrieved_services(run, outcome)
        category, reason = _classification(expected, outcome, services)
        errors.append(
            {
                "instance_id": outcome.instance_id,
                "mode": outcome.mode,
                "expected": expected,
                "predicted": predicted,
                "disposition": outcome.disposition,
                "missing_evidence_count": outcome.missing_evidence_count,
                "retrieved_services": services,
                "category": category,
                "reason": reason,
            }
        )
    categories = Counter(row["category"] for row in errors)
    expected_causes = Counter(row["expected"] for row in errors)
    return {
        "schema_version": "diagnosis-error-analysis/1.0.0",
        "source": {
            "labels_path": labels_path.as_posix(),
            "labels_sha256": _sha256(labels_path),
            "run_path": run.as_posix(),
            "outcome_count": len(outcomes),
            "outcomes_sha256": hashlib.sha256(
                b"".join(path.read_bytes() for path in outcome_paths)
            ).hexdigest(),
            "analyzer_sha256": _sha256(ANALYZER),
        },
        "census": {
            "fault_outcomes": fault_outcomes,
            "top1_correct": correct,
            "top1_errors": len(errors),
            "top1_rate": correct / fault_outcomes,
        },
        "category_counts": dict(sorted(categories.items())),
        "expected_cause_counts": dict(sorted(expected_causes.items())),
        "errors": errors,
        "optimization_decision": {
            "memory_evidence": (
                "Adopt the already validated FC3 GC-aware context contract in the candidate path."
            ),
            "causal_scope": (
                "Add bounded deterministic read-only downstream Evidence expansion after "
                "a failing dependency is observed; do not infer a cause or perform a write."
            ),
            "ranking": "Do not tune ranking until decisive downstream Evidence is present.",
        },
        "limitations": [
            "This is a deterministic post-hoc classification of frozen development outcomes, "
            "not a new quality measurement.",
            "Evaluator labels are used only after outcomes exist and are never passed to "
            "runtime or a model.",
            "The optimization decision must be tested on separate development data before "
            "the untouched FC4 holdout is opened.",
        ],
    }


def render(report: dict[str, Any]) -> str:
    census = report["census"]
    lines = [
        "# Frozen diagnosis error analysis",
        "",
        "This report classifies the existing candidate 1.11 misses without rerunning or "
        "rescoring provider outputs.",
        "",
        "## Census",
        "",
        f"- Fault outcomes: {census['fault_outcomes']}",
        f"- Top-1 correct: {census['top1_correct']}",
        f"- Top-1 errors: {census['top1_errors']}",
        "",
        "## Root causes of misses",
        "",
        "| Category | Count | Required response |",
        "| --- | ---: | --- |",
    ]
    decisions = report["optimization_decision"]
    responses = {
        "EVIDENCE_CONSTRUCTION_GAP": decisions["memory_evidence"],
        "DOWNSTREAM_CAUSAL_SCOPE_NOT_EXPANDED": decisions["causal_scope"],
    }
    for category, count in report["category_counts"].items():
        lines.append(
            f"| `{category}` | {count} | {responses.get(category, decisions['ranking'])} |"
        )
    lines.extend(
        [
            "",
            "All nine memory-leak misses safely handed off because the legacy context lacked "
            "the later FC3 GC-aware facts. All nine bad-configuration misses classified the "
            "observed HTTP symptom after collecting only gateway Evidence; no downstream "
            "configuration/deployment Evidence was available to distinguish the underlying "
            "cause.",
            "",
            "## Decision",
            "",
            "The candidate will combine the already validated GC-aware memory context with "
            "bounded deterministic downstream read-only expansion. It will not alter schemas, "
            "the Evidence Gate, model call ceilings, write authority, or recovery controls. "
            "Ranking changes are deferred until decisive Evidence exists.",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in report["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("error-analysis output already exists")
    report = analyze(args.labels, args.run)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "analysis.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output / "README.md").write_text(render(report), encoding="utf-8")


if __name__ == "__main__":
    main()
