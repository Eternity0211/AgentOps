"""Score memory-context reports only after loading evaluator-only labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def claims_sustained_memory(report: dict[str, Any], *, profile: str = "v1") -> bool:
    if profile not in {"v1", "v2"}:
        raise ValueError("unknown memory claim scoring profile")
    terms = ("memory leak", "memory retention", "retained memory", "memory growth")
    negations = (
        "not a leak",
        "normal warmup",
        "normal warm-up",
        "no sustained",
        "insufficient evidence",
        "does not establish",
    )
    return any(
        any(term in candidate["statement"].lower() for term in terms)
        and (
            profile == "v1"
            or not any(negation in candidate["statement"].lower() for negation in negations)
        )
        for candidate in report["candidates"]
    )


def score_pair(
    labels_path: Path, results: Path, output: Path, *, claim_profile: str = "v1"
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("memory-context score already exists")
    labels = json.loads(labels_path.read_text("utf-8"))["labels"]
    summaries = {}
    for arm in ("baseline-context", "candidate-context"):
        correct = safe_negative = detected = 0
        resources: dict[str, list[int]] = {
            "duration_ms": [],
            "input_tokens": [],
            "output_tokens": [],
            "cost_upper_bound_nanousd": [],
        }
        for case_id, label in labels.items():
            row = json.loads((results / arm / case_id / "result.json").read_text("utf-8"))
            succeeded = row["status"] == "SUCCEEDED"
            claimed = succeeded and claims_sustained_memory(
                row["report"], profile=claim_profile
            )
            expected = label == "SUSTAINED_RETENTION"
            correct += int(succeeded and claimed == expected)
            detected += int(expected and claimed)
            safe_negative += int(succeeded and not expected and not claimed)
            for metric in resources:
                if row[metric] is not None:
                    resources[metric].append(row[metric])
        summaries[arm] = {
            "correct": correct,
            "total": len(labels),
            "sustained_detected": detected,
            "safe_negatives": safe_negative,
            "failures": len(labels) - sum(
                json.loads((results / arm / case_id / "result.json").read_text("utf-8"))[
                    "status"
                ]
                == "SUCCEEDED"
                for case_id in labels
            ),
            "resource_totals": {key: sum(values) for key, values in resources.items()},
        }
    document = {"schema_version": "memory-context-score/1.0.0", "arms": summaries}
    if claim_profile != "v1":
        document["claim_profile"] = claim_profile
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--claim-profile", choices=("v1", "v2"), default="v1")
    args = parser.parse_args()
    score_pair(args.labels, args.results, args.output, claim_profile=args.claim_profile)


if __name__ == "__main__":  # pragma: no cover
    main()
