"""Label-free execution of the frozen conservative rules snapshot supplement."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from evaluation.baselines.rules import RulesDiagnosisSystem
from evaluation.contracts import EvaluationCase, EvaluationObservation, ObservationSignal
from evaluation.fairness import AggregateBudget, BaselineProfile, CandidateExecutionConfig
from evaluation.observation_snapshot import load_snapshot
from evaluation.real_scoring import RULES_MODE, Outcome, protocol_hash
from evaluation.run_real_batch import preflight

ROOT = Path(__file__).resolve().parents[1]


def run(dataset: Path, protocol: Path, output: Path) -> tuple[Outcome, ...]:
    plan = json.loads(protocol.read_text(encoding="utf-8"))
    for path, key in [
        (dataset / "index.json", "dataset_index_sha256"),
        (ROOT / "evaluation/baselines/rules.py", "rules_source_sha256"),
    ]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != plan[key]:
            raise ValueError("rules supplement frozen input mismatch")
    queries = plan["queries"]
    if len(queries) != 12 or plan["query_limit"] != 12 or plan["retry_limit"] != 0:
        raise ValueError("rules supplement query budget mismatch")
    rows = preflight(dataset)
    digest = protocol_hash(protocol)
    output.mkdir(parents=True, exist_ok=False)
    configuration = CandidateExecutionConfig(
        BaselineProfile(
            "rules-only",
            "1.0.0",
            "rules",
            "deterministic",
            False,
            None,
            None,
            "none",
            AggregateBudget(64000, 0, 12, 0, 60000, 0),
        ),
        (),
    )
    outcomes = []
    for row in rows:
        started = time.monotonic_ns()
        snapshot = load_snapshot(
            dataset / "inputs" / f"{row['instance_id']}.json", expected_hash=row["input_hash"]
        )
        signals, reads = [], []
        for query in queries:
            key = query["tool"] + ":" + query["service"]
            record = snapshot["reads"][key]
            reads.append({"key": key, "status": record["status"]})
            if record["status"] == "SUCCEEDED":
                data = record["output"]
                signals.append(
                    ObservationSignal(
                        data["source"], data["summary"][: plan["summary_char_limit_per_query"]]
                    )
                )
        failed = any(r["status"] != "SUCCEEDED" for r in reads)
        result: dict[str, Any] = {}
        if not failed:
            case = EvaluationCase(
                row["instance_id"],
                "opaque-snapshot",
                "evaluation",
                EvaluationObservation(snapshot["alert"], 1, tuple(signals), ()),
            )
            result = dict(RulesDiagnosisSystem().evaluate(case, configuration))
        outcome = Outcome(
            instance_id=row["instance_id"],
            mode=RULES_MODE,
            protocol_hash=digest,
            input_hash=row["input_hash"],
            status="FAILED" if failed else "SUCCEEDED",
            disposition=None if failed else "HUMAN_HANDOFF",
            candidates=tuple(result.get("diagnosis_top3", [])),
            missing_evidence_count=int(
                result.get("outcome_reason_code") == "EVIDENCE_INSUFFICIENT"
            ),
            duration_ms=(time.monotonic_ns() - started) // 1000000,
            input_tokens=0,
            output_tokens=0,
            cost_upper_bound_nanousd=0,
        )
        outcomes.append(outcome)
        with (output / f"{row['instance_id']}.json").open("x", encoding="utf-8") as stream:
            json.dump(
                {
                    "outcome": outcome.model_dump(mode="json"),
                    "rules_result": result,
                    "snapshot_reads": reads,
                },
                stream,
                indent=2,
            )
    metadata = {
        "protocol_hash": digest,
        "python": platform.python_version(),
        "platform": platform.system(),
        "concurrency": 1,
        "model_calls": 0,
        "snapshot_reads": len(outcomes) * 12,
        "live_tool_calls": 0,
        "source_revision": subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_hashes": {
            str(p.relative_to(ROOT).as_posix()): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                ROOT / "evaluation/baselines/rules.py",
                ROOT / "evaluation/real_scoring.py",
            ]
        },
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return tuple(outcomes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/datasets/real-v1"))
    parser.add_argument(
        "--protocol", type=Path, default=Path("evaluation/real_protocol/rules-v1/plan.json")
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.dataset, args.protocol, args.output)


if __name__ == "__main__":
    main()
