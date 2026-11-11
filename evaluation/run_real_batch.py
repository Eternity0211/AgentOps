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
from evaluation.real_scoring import SIMULATED_MEMORY_MODE, Outcome, protocol_hash
from evaluation.run_snapshot_comparison import run_snapshot
from evaluation.simulated_history_source import memory_source


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
    simulated_history_bank: Path | None = None,
) -> None:
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required before batch start")
    if (
        not modes
        or len(set(modes)) != len(modes)
        or any(
            m not in ("single-agent", "controlled-graph", SIMULATED_MEMORY_MODE) for m in modes
        )
    ):
        raise ValueError("batch modes require configured single/graph/simulated-memory")
    if (SIMULATED_MEMORY_MODE in modes) != (simulated_history_bank is not None):
        raise ValueError("simulated-memory mode requires exactly one frozen simulated bank")
    rows = preflight(dataset)
    excluded = frozenset(row["instance_id"] for row in rows)
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
                memory_source=(
                    memory_source(
                        simulated_history_bank,
                        load_snapshot(
                            dataset / "inputs" / f"{row['instance_id']}.json",
                            expected_hash=row["input_hash"],
                        ),
                        excluded,
                    )
                    if mode == SIMULATED_MEMORY_MODE and simulated_history_bank is not None
                    else None
                ),
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/datasets/real-v1"))
    parser.add_argument(
        "--protocol", type=Path, default=Path("evaluation/real_protocol/v1/plan.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--simulated-history-bank", type=Path)
    parser.add_argument("--include-simulated-memory", action="store_true")
    args = parser.parse_args()
    modes: tuple[str, ...] = ("single-agent", "controlled-graph")
    if args.include_simulated_memory:
        modes = (*modes, SIMULATED_MEMORY_MODE)
    run_batch(
        args.dataset,
        args.output,
        args.protocol,
        key=os.environ.get("DEEPSEEK_API_KEY", ""),
        modes=modes,
        simulated_history_bank=args.simulated_history_bank,
    )


if __name__ == "__main__":
    main()
