"""Run the frozen, label-free FC4 evidence-strategy development pair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from evaluation.autonomous_diagnosis import EvidenceStrategy
from evaluation.observation_snapshot import load_snapshot
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import Outcome
from evaluation.run_real_batch import preflight
from evaluation.run_snapshot_comparison import run_snapshot
from evaluation.structured_model import StructuredTransportProfile

BOUND_SOURCES = {
    "evaluation/autonomous_diagnosis.py",
    "evaluation/run_evidence_strategy_pair.py",
    "evaluation/run_snapshot_comparison.py",
    "evaluation/score_transport_pair.py",
    "evaluation/structured_model.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _arms(
    plan: dict[str, Any],
) -> tuple[tuple[str, StructuredTransportProfile, EvidenceStrategy], ...]:
    try:
        arms = tuple(
            (
                name,
                StructuredTransportProfile(config["transport_profile"]),
                EvidenceStrategy(config["evidence_strategy"]),
            )
            for name, config in plan["arms"].items()
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("evidence-strategy arm binding mismatch") from error
    if len(arms) != 2 or len({name for name, _profile, _strategy in arms}) != 2:
        raise ValueError("evidence-strategy arm binding mismatch")
    if len({profile for _name, profile, _strategy in arms}) != 1:
        raise ValueError("transport profile must be held constant")
    return arms


def check_plan(
    plan: dict[str, Any], revision: str, dataset: Path
) -> tuple[tuple[str, StructuredTransportProfile, EvidenceStrategy], ...]:
    if plan.get("schema_version") != "evidence-strategy-pair/1.0.0":
        raise ValueError("unknown evidence-strategy pair plan")
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
    source_root = Path(__file__).resolve().parents[1]
    if set(plan.get("source_hashes", {})) != BOUND_SOURCES or any(
        _sha256(source_root / name) != digest for name, digest in plan["source_hashes"].items()
    ):
        raise ValueError("evidence-strategy source hash mismatch")
    if plan.get("modes") != ["controlled-graph"] or plan.get("model_provider_call_ceiling") != 6:
        raise ValueError("evidence-strategy budget or mode mismatch")
    return _arms(plan)


def run_pair(
    dataset: Path,
    plan_path: Path,
    output: Path,
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
    arms = check_plan(plan, revision, dataset)
    rows = preflight(dataset)
    digest = hashlib.sha256(plan_bytes).hexdigest()
    ceiling = plan["model_provider_call_ceiling"]
    for row_index, row in enumerate(rows):
        snapshot_path = dataset / "inputs" / f"{row['instance_id']}.json"
        load_snapshot(snapshot_path, expected_hash=row["input_hash"])
        ordered = arms if row_index % 2 == 0 else tuple(reversed(arms))
        for arm_name, profile, strategy in ordered:
            arm_root = output / arm_name
            ledger = OutcomeLedger(arm_root / "outcomes")
            existing = {item.instance_id: item for item in ledger.collect(protocol_hash=digest)}
            previous = existing.get(row["instance_id"])
            if previous is not None:
                if previous.input_hash != row["input_hash"]:
                    raise ValueError("resume input hash mismatch")
                continue
            run_root = arm_root / "controlled-graph" / row["instance_id"]
            if run_root.exists():
                ledger.append(
                    Outcome(
                        instance_id=row["instance_id"],
                        mode="controlled-graph",
                        protocol_hash=digest,
                        input_hash=row["input_hash"],
                        status="FAILED",
                    )
                )
                continue
            run_snapshot(
                snapshot_path,
                row["input_hash"],
                "controlled-graph",
                arm_root,
                digest,
                key=key,
                transport=transport,
                profile=profile,
                evidence_strategy=strategy,
                model_max_calls=ceiling,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_pair(
        args.dataset,
        args.plan,
        args.output,
        key=os.environ.get("DEEPSEEK_API_KEY", ""),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
