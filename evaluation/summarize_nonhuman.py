"""Derive descriptive metrics without treating unavailable observations as zero."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from decimal import Decimal
from pathlib import Path
from typing import Any


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot summarize an empty sample")
    durations = sorted(row["duration_ms"] for row in rows)
    metered = [row["usage"] for row in rows if row.get("usage") is not None]
    input_tokens = sum(row["prompt_tokens"] for row in metered)
    output_tokens = sum(row["completion_tokens"] for row in metered)
    return {
        "cases": len(rows),
        "validated": sum(row["status"] == "validated" for row in rows),
        "failed": sum(row["status"] != "validated" for row in rows),
        "top1_correct": sum(row.get("top1_correct", False) for row in rows),
        "top3_correct": sum(row.get("top3_correct", False) for row in rows),
        "metered_calls": len(metered),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "median_ms": statistics.median(durations),
        "p95_nearest_rank_ms": durations[math.ceil(0.95 * len(durations)) - 1],
        "min_ms": min(durations),
        "max_ms": max(durations),
        "duration_samples_ms": durations,
        "unknown_references": sum(row.get("unknown_reference_count", 0) for row in rows),
        "cost_usd_lower_bound_for_metered_calls": str(
            (Decimal(input_tokens) * Decimal(".003") + Decimal(output_tokens) * Decimal(".6"))
            / 1_000_000
        ),
        "cost_usd_upper_bound_for_metered_calls": str(
            (Decimal(input_tokens) * Decimal(".30") + Decimal(output_tokens) * Decimal("1.2"))
            / 1_000_000
        ),
        "cost_source": "rate-card.json; descriptive bounds, not provider invoice",
    }


def summarize(root: Path) -> dict[str, Any]:
    def load(path: str) -> dict[str, Any]:
        return json.loads((root / path).read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    paired = load("paired-001/results.json")["results"]
    live = load("live-002/results.json")["results"]
    adversarial = load("adversarial-001/results.json")["results"]
    live_rows = [
        {
            **row["diagnosis"],
            "top1_correct": row["top1_correct"],
            "top3_correct": row["top3_correct"],
        }
        for row in live
    ]
    summary = {
        "schema_version": "nonhuman-measurements/1.0.0",
        "paired": {
            mode: metrics([row for row in paired if row["mode"] == mode])
            for mode in ("single", "graph", "memory")
        },
        "live": metrics(live_rows),
        "adversarial": metrics(adversarial),
        "live_cleanup_success": sum(
            row["cleanup_exit"] == 0 and row["after_cleanup"]["status"] == 200 for row in live
        ),
        "live_source_nonempty": {
            source: sum(row["source_nonempty"][source] for row in live)
            for source in ("metrics", "logs", "traces", "http-probes")
        },
        "synthetic_canary": {
            "attempts": 2,
            "echoes": sum(
                row["canary_echo"] is True
                for row in adversarial
                if row["probe"] == "synthetic-secret-canary"
            ),
        },
        "missing_evidence": {
            "attempts": 2,
            "recognized": sum(
                row["missing_evidence_recognized"] is True
                for row in adversarial
                if row["probe"] == "missing-evidence"
            ),
        },
        "recovery": {"status": "AWAITING_HUMAN_APPROVAL", "success_rate": None},
        "human_efficiency": {"status": "DEFERRED_TO_USER", "improvement": None},
        "limitations": [
            "Known six-case repeats are not 18 independent faults",
            "Live diagnosis and paired replay are separate experiments",
            "No semantic support rubric, autonomous planning or full runtime Gate measurement",
            "Source presence is not evidence independence or quality",
            "CPU/memory samples are not monetary infrastructure cost",
        ],
    }
    with (root / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    summarize(parser.parse_args().root)


if __name__ == "__main__":  # pragma: no cover
    main()
