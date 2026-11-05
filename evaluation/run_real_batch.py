"""Label-free batch preflight and bounded resumable real-provider comparison."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from evaluation.observation_snapshot import load_snapshot
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import Outcome, protocol_hash
from evaluation.run_snapshot_comparison import run_snapshot


def preflight(dataset: Path) -> tuple[dict[str, str], ...]:
    rows = json.loads((dataset / "index.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != 27:
        raise ValueError("exactly 27 input snapshots required")
    seen = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"instance_id", "input_hash"}
            or not re.fullmatch(r"instance-[0-9a-f]{16}", row["instance_id"])
            or row["instance_id"] in seen
        ):
            raise ValueError("duplicate/invalid snapshot index")
        seen.add(row["instance_id"])
        snapshot = load_snapshot(
            dataset / "inputs" / f"{row['instance_id']}.json", expected_hash=row["input_hash"]
        )
        if snapshot["instance_id"] != row["instance_id"]:
            raise ValueError("snapshot index binding mismatch")
    return tuple(rows)


def run_batch(
    dataset: Path,
    output: Path,
    protocol: Path,
    *,
    key: str,
    modes: tuple[str, ...] = ("single-agent", "controlled-graph"),
    transport: Any = None,
) -> None:
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required before batch start")
    if (
        not modes
        or len(set(modes)) != len(modes)
        or any(m not in ("single-agent", "controlled-graph") for m in modes)
    ):
        raise ValueError(
            "batch modes require configured single/graph; memory needs an authorized source"
        )
    rows = preflight(dataset)
    digest = protocol_hash(protocol)
    ledger = OutcomeLedger(output / "outcomes")
    existing = {(r.instance_id, r.mode): r for r in ledger.collect(protocol_hash=digest)}
    for row in rows:
        for mode in modes:
            previous = existing.get((row["instance_id"], mode))
            if previous is not None:
                if previous.input_hash != row["input_hash"]:
                    raise ValueError("resume input hash mismatch")
                continue
            run_root = output / mode / row["instance_id"]
            if run_root.exists():
                ledger.append(
                    Outcome(
                        instance_id=row["instance_id"],
                        mode=mode,
                        protocol_hash=digest,
                        input_hash=row["input_hash"],
                        status="FAILED",
                    )
                )
                continue  # Uncertain prior provider effects must not be silently replayed.
            run_snapshot(
                dataset / "inputs" / f"{row['instance_id']}.json",
                row["input_hash"],
                mode,
                output,
                digest,
                key=key,
                transport=transport,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/datasets/real-v1"))
    parser.add_argument(
        "--protocol", type=Path, default=Path("evaluation/real_protocol/v1/plan.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_batch(args.dataset, args.output, args.protocol, key=os.environ.get("DEEPSEEK_API_KEY", ""))


if __name__ == "__main__":
    main()
