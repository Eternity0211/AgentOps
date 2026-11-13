"""Run a label-free paired real-model comparison of baseline and GC-aware contexts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from evaluation.autonomous_diagnosis import (
    build_candidate_diagnosis_context,
    build_diagnosis_context,
)
from evaluation.structured_model import (
    ModelPurpose,
    StructuredEvaluationModel,
    StructuredModelFailure,
    StructuredTransportProfile,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observations(case: dict[str, Any], limit: int) -> list[dict[str, str]]:
    evidence_id = f"evidence-{case['case_id']}-memory"
    spans = []
    for row in case["samples"]:
        attributes = [
            {"key": "process.memory.retained_bytes", "value": {"intValue": str(row[1])}},
            {
                "key": "process.memory.retention_limit_bytes",
                "value": {"intValue": str(limit)},
            },
            {
                "key": "process.memory.retention_allocations",
                "value": {"intValue": str(row[2])},
            },
            {
                "key": "process.memory.retention_releases",
                "value": {"intValue": str(row[3])},
            },
        ]
        if row[4] is not None:
            attributes.extend(
                [
                    {"key": "process.memory.gc.cycle", "value": {"intValue": str(row[4])}},
                    {"key": "process.memory.gc.phase", "value": {"stringValue": row[5]}},
                ]
            )
        spans.append(
            {
                "service": case["service"],
                "start": str(row[0] * 1_000_000_000 - 1),
                "end": str(row[0] * 1_000_000_000),
                "attributes": attributes,
            }
        )
    observations = [{"id": evidence_id, "source": "traces", "summary": json.dumps(spans)}]
    if case["deployment"] is not None:
        observations.append(
            {
                "id": f"evidence-{case['case_id']}-deployment",
                "source": "deployments",
                "summary": json.dumps([{"service": case["service"], **case["deployment"]}]),
            }
        )
    return observations


def run_pair(inputs_path: Path, plan_path: Path, output: Path, *, key: str) -> None:
    if output.exists():
        raise FileExistsError("memory-context pair output already exists")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required")
    plan = json.loads(plan_path.read_text("utf-8"))
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
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
    if _sha256(inputs_path) != plan["inputs_sha256"]:
        raise ValueError("memory-context input hash mismatch")
    source_root = Path(__file__).resolve().parents[1]
    required_sources = {
        "evaluation/run_memory_context_pair.py",
        "evaluation/score_memory_context_pair.py",
        "evaluation/autonomous_diagnosis.py",
        "evaluation/memory_evidence.py",
        "evaluation/structured_model.py",
    }
    if set(plan.get("source_hashes", {})) != required_sources or any(
        _sha256(source_root / name) != digest
        for name, digest in plan["source_hashes"].items()
    ):
        raise ValueError("memory-context source hash mismatch")
    inputs = json.loads(inputs_path.read_text("utf-8"))
    digest = _sha256(plan_path)
    builders = (
        ("baseline-context", build_diagnosis_context),
        ("candidate-context", build_candidate_diagnosis_context),
    )
    for index, case in enumerate(inputs["cases"]):
        observations = _observations(case, inputs["retention_limit_bytes"])
        ordered = builders if index % 2 == 0 else tuple(reversed(builders))
        for arm, builder in ordered:
            events: list[dict[str, Any]] = []
            context = builder(observations, {})
            context["incident_id"] = case["case_id"]
            model = StructuredEvaluationModel(
                key,
                events.append,
                max_calls=2,
                profile=StructuredTransportProfile.CANDIDATE_1_8,
            )
            try:
                result = model.invoke(ModelPurpose.DIAGNOSE, context)
                row = {
                    "status": "SUCCEEDED",
                    "report": result.output.model_dump(mode="json"),
                    "duration_ms": result.duration_ms,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost_upper_bound_nanousd": result.cost_upper_bound_nanousd,
                }
            except StructuredModelFailure as error:
                row = {
                    "status": "FAILED",
                    "error_code": str(error),
                    "report": None,
                    "duration_ms": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "cost_upper_bound_nanousd": None,
                }
            root = output / arm / case["case_id"]
            root.mkdir(parents=True)
            (root / "result.json").write_text(
                json.dumps(
                    {
                        "protocol_sha256": digest,
                        "context_sha256": hashlib.sha256(
                            json.dumps(context, sort_keys=True).encode()
                        ).hexdigest(),
                        **row,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "events.jsonl").write_text(
                "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
                encoding="utf-8",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_pair(args.inputs, args.plan, args.output, key=os.environ.get("DEEPSEEK_API_KEY", ""))


if __name__ == "__main__":  # pragma: no cover
    main()
