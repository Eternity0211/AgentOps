"""Run bounded real-provider calls over synthetic summaries; no runtime or write access."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation.deepseek_provider import PROMPT_VERSION, DeepSeekEvaluationProvider, digest

ROOT = Path(__file__).resolve().parents[1]


def run(output: Path, *, limit: int = 6) -> dict[str, Any]:
    if not 1 <= limit <= 6:
        raise ValueError("limit must be between 1 and 6")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required")
    output.mkdir(parents=True, exist_ok=False)
    dataset = json.loads((ROOT / "evaluation/datasets/v1/dataset.json").read_text())
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()
    started = datetime.now(UTC).isoformat()

    def journal(event: dict[str, Any]) -> None:
        with (output / "calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), **event}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    provider = DeepSeekEvaluationProvider(key, journal)
    results = []
    for index, case in enumerate(dataset["cases"][:limit], 1):
        # Never send scenario/case IDs, labels or evaluator metadata to the model.
        observations = [
            {
                "id": f"observation-{number}",
                "source": signal["source"],
                "summary": signal["summary"],
            }
            for number, signal in enumerate(case["observation"]["signals"], 1)
        ]
        result = provider.diagnose(f"incident-{index}", observations)
        results.append({"case_id": case["case_id"], **result})
        print(f"case {index}/{limit}: {result['status']}", flush=True)
    # Evaluator labels are loaded only after every provider call has finished.
    policy = json.loads((ROOT / "evaluation/metrics/v1/policy.json").read_text())
    top1 = top3 = 0
    for result, case in zip(results, dataset["cases"][:limit], strict=True):
        accepted = policy["accepted_root_causes"][case["scenario_id"]]
        candidates = result.get("candidate_ids", [])
        result["top1_correct"] = bool(candidates and candidates[0] in accepted)
        result["top3_correct"] = bool(set(candidates[:3]) & set(accepted))
        top1 += result["top1_correct"]
        top3 += result["top3_correct"]
    document = {
        "schema_version": "real-provider-smoke/1.0.0",
        "started_at": started,
        "code_revision": revision,
        "source_hashes": {
            name: digest((ROOT / name).read_text(encoding="utf-8"))
            for name in ("evaluation/deepseek_provider.py", "evaluation/run_deepseek_smoke.py")
        },
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dataset_hash": digest(dataset),
        "policy_hash": digest(policy),
        "prompt_version": PROMPT_VERSION,
        "limits": {
            "calls": limit,
            "max_output_tokens_per_call": 2048,
            "timeout_seconds": 60,
            "retries": 0,
            "concurrency": 1,
        },
        "summary": {
            "cases": limit,
            "validated": sum(r["status"] == "validated" for r in results),
            "top1_correct": top1,
            "top3_correct": top3,
        },
        "limitations": [
            "Synthetic summary replay, not live fault injection",
            "Fixture IDs are not persisted Evidence Store records",
            "No runtime Gate, tools, approvals, execution or recovery exercised",
            "No human baseline or causal efficiency claim",
            "Costs unavailable; never interpreted as zero",
            "Candidate labels scored by exact existing policy, not semantic judging",
        ],
        "results": results,
    }
    with (output / "results.json").open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2)
        stream.write("\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()
    run(args.output_dir, limit=args.limit)


if __name__ == "__main__":  # pragma: no cover
    main()
