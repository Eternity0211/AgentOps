"""Run an interleaved, label-free structured-transport before/after comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from evaluation.historical_context import MemoryReplaySource
from evaluation.observation_snapshot import load_snapshot
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import SIMULATED_MEMORY_MODE, Outcome
from evaluation.run_real_batch import preflight
from evaluation.run_snapshot_comparison import run_snapshot
from evaluation.simulated_history_source import memory_source
from evaluation.structured_model import StructuredTransportProfile

FROZEN_V1_PROFILES = (
    ("baseline-1.4", StructuredTransportProfile.BASELINE_1_4),
    ("candidate-1.5", StructuredTransportProfile.CANDIDATE_1_5),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profiles(plan: dict[str, Any]) -> tuple[tuple[str, StructuredTransportProfile], ...]:
    try:
        profiles = tuple(
            (name, StructuredTransportProfile(version))
            for name, version in plan["profiles"].items()
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("transport profile binding mismatch") from error
    if len(profiles) != 2 or len({name for name, _profile in profiles}) != 2:
        raise ValueError("transport profile binding mismatch")
    return profiles


def _check_plan(
    plan: dict[str, Any], revision: str, dataset: Path, bank: Path
) -> tuple[tuple[str, StructuredTransportProfile], ...]:
    if plan.get("schema_version") != "structured-transport-pair/1.0.0":
        raise ValueError("unknown transport-pair plan")
    binding = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=D:/AgentOps",
            "merge-base",
            "--is-ancestor",
            plan["implementation_commit"],
            revision,
        ],
        check=False,
    )
    if binding.returncode != 0:
        raise ValueError("frozen implementation commit is not an ancestor")
    if _sha256(dataset / "index.json") != plan["dataset_index_sha256"]:
        raise ValueError("dataset index hash mismatch")
    if _sha256(bank) != plan["simulated_history_bank_sha256"]:
        raise ValueError("simulated-history bank hash mismatch")
    source_root = Path(__file__).resolve().parents[1]
    required_sources = {
        "evaluation/run_transport_pair.py",
        "evaluation/structured_model.py",
    }
    if set(plan.get("source_hashes", {})) != required_sources or any(
        _sha256(source_root / name) != digest
        for name, digest in plan["source_hashes"].items()
    ):
        raise ValueError("transport source hash mismatch")
    return _profiles(plan)


def _history(
    mode: str,
    bank: Path,
    snapshot: dict[str, Any],
    excluded: frozenset[str],
) -> MemoryReplaySource | None:
    return (
        memory_source(bank, snapshot, excluded)
        if mode == SIMULATED_MEMORY_MODE
        else None
    )


def run_pair(
    dataset: Path,
    plan_path: Path,
    output: Path,
    bank: Path,
    *,
    key: str,
    transport: Any = None,
) -> None:
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required before pair start")
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    profiles = _check_plan(plan, revision, dataset, bank)
    rows = preflight(dataset)
    modes = tuple(plan["modes"])
    if modes != ("single-agent", "controlled-graph", SIMULATED_MEMORY_MODE):
        raise ValueError("transport pair requires the frozen three modes")
    digest = hashlib.sha256(plan_bytes).hexdigest()
    excluded = frozenset(row["instance_id"] for row in rows)
    for row_index, row in enumerate(rows):
        snapshot_path = dataset / "inputs" / f"{row['instance_id']}.json"
        snapshot = load_snapshot(snapshot_path, expected_hash=row["input_hash"])
        for mode_index, mode in enumerate(modes):
            ordered = (
                profiles
                if (row_index + mode_index) % 2 == 0
                else tuple(reversed(profiles))
            )
            for profile_name, profile in ordered:
                profile_root = output / profile_name
                ledger = OutcomeLedger(profile_root / "outcomes")
                existing = {
                    (item.instance_id, item.mode): item
                    for item in ledger.collect(protocol_hash=digest)
                }
                previous = existing.get((row["instance_id"], mode))
                if previous is not None:
                    if previous.input_hash != row["input_hash"]:
                        raise ValueError("resume input hash mismatch")
                    continue
                run_root = profile_root / mode / row["instance_id"]
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
                    continue
                run_snapshot(
                    snapshot_path,
                    row["input_hash"],
                    mode,
                    profile_root,
                    digest,
                    key=key,
                    transport=transport,
                    memory_source=_history(mode, bank, snapshot, excluded),
                    profile=profile,
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--simulated-history-bank", type=Path, required=True)
    args = parser.parse_args()
    run_pair(
        args.dataset,
        args.plan,
        args.output,
        args.simulated_history_bank,
        key=os.environ.get("DEEPSEEK_API_KEY", ""),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
