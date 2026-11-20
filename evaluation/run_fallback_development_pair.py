"""Run the frozen, label-free FC4f transport fallback development pair."""

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

BOUND_SOURCES = frozenset(
    {
        "evaluation/autonomous_diagnosis.py",
        "evaluation/live_evidence.py",
        "evaluation/live_gateway.py",
        "evaluation/observation_snapshot.py",
        "evaluation/outcome_ledger.py",
        "evaluation/paired_comparison.py",
        "evaluation/real_scoring.py",
        "evaluation/run_fallback_development_pair.py",
        "evaluation/run_real_batch.py",
        "evaluation/run_snapshot_comparison.py",
        "evaluation/score_transport_pair.py",
        "evaluation/structured_model.py",
    }
)
PROFILES = (
    ("baseline-1.11", StructuredTransportProfile.CANDIDATE_1_11),
    ("candidate-1.12", StructuredTransportProfile.CANDIDATE_1_12),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_plan(plan: dict[str, Any], revision: str, dataset: Path) -> None:
    if plan.get("schema_version") != "diagnosis-fallback-development-pair/1.0.0":
        raise ValueError("unknown fallback development protocol")
    if tuple(plan.get("profiles", {}).items()) != tuple(
        (name, profile.value) for name, profile in PROFILES
    ):
        raise ValueError("fallback profile pair mismatch")
    if (
        plan.get("modes") != ["controlled-graph"]
        or plan.get("model_provider_call_ceiling") != 6
        or plan.get("graph_model_call_ceiling") != 4
        or plan.get("tool_call_ceiling") != 12
        or plan.get("evidence_strategy") != EvidenceStrategy.GC_AWARE_CAUSAL_SCOPE.value
        or plan.get("expected_cases") != 27
        or plan.get("selective_reruns_allowed") is not False
        or plan.get("runtime_label_isolation") is not True
    ):
        raise ValueError("fallback development budget or isolation mismatch")
    if _sha256(dataset / "index.json") != plan.get("dataset_index_sha256"):
        raise ValueError("fallback development dataset drift")
    if (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", plan["implementation_commit"], revision],
            check=False,
            capture_output=True,
        ).returncode
        != 0
    ):
        raise ValueError("fallback implementation commit mismatch")
    hashes = plan.get("source_hashes", {})
    root = Path(__file__).resolve().parents[1]
    if set(hashes) != BOUND_SOURCES or any(
        _sha256(root / path) != digest for path, digest in hashes.items()
    ):
        raise ValueError("fallback development source drift")


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
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    check_plan(plan, revision, dataset)
    rows = preflight(dataset, expected_cases=27)
    protocol_hash = hashlib.sha256(plan_bytes).hexdigest()
    for index, row in enumerate(rows):
        snapshot_path = dataset / "inputs" / f"{row['instance_id']}.json"
        load_snapshot(snapshot_path, expected_hash=row["input_hash"])
        ordered = PROFILES if index % 2 == 0 else tuple(reversed(PROFILES))
        for name, profile in ordered:
            arm_root = output / name
            ledger = OutcomeLedger(arm_root / "outcomes")
            existing = {
                item.instance_id: item for item in ledger.collect(protocol_hash=protocol_hash)
            }
            previous = existing.get(row["instance_id"])
            if previous is not None:
                if previous.input_hash != row["input_hash"] or previous.mode != "controlled-graph":
                    raise ValueError("fallback pair resume binding mismatch")
                continue
            run_root = arm_root / "controlled-graph" / row["instance_id"]
            if run_root.exists():
                ledger.append(
                    Outcome(
                        instance_id=row["instance_id"],
                        mode="controlled-graph",
                        protocol_hash=protocol_hash,
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
                protocol_hash,
                key=key,
                transport=transport,
                profile=profile,
                evidence_strategy=EvidenceStrategy.GC_AWARE_CAUSAL_SCOPE,
                model_max_calls=6,
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
