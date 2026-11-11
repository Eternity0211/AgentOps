"""Run frozen, label-isolated diagnosis-context generalization cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from evaluation.autonomous_diagnosis import build_diagnosis_context
from evaluation.real_scoring import CAUSES
from evaluation.structured_model import (
    ModelPurpose,
    StructuredEvaluationModel,
    StructuredModelFailure,
    fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_observations(case: dict[str, Any]) -> list[dict[str, str]]:
    archive = ROOT / case["archive_root"]
    observations: list[dict[str, str]] = []
    for binding in case["manifests"]:
        manifest_path = archive / binding["path"]
        if _sha256(manifest_path) != binding["sha256"]:
            raise ValueError("archive manifest hash mismatch")
        for item in json.loads(manifest_path.read_text(encoding="utf-8")):
            evidence = item["evidence"]
            if evidence["incident_id"]["value"] != case["incident_id"]:
                raise ValueError("archive incident mismatch")
            content_hash = evidence["content_hash"]["value"]
            blob = archive / "blobs" / content_hash[:2] / content_hash
            if _sha256(blob) != content_hash:
                raise ValueError("archive artifact hash mismatch")
            payload = json.loads(blob.read_text(encoding="utf-8"))
            parameters = evidence["normalized_query"]["parameters"]
            source = next(p["value"] for p in parameters if p["name"] == "source")
            observations.append(
                {
                    "id": evidence["id"]["value"],
                    "source": source,
                    "summary": payload["summary"],
                }
            )
    return observations


def _memory_span(timestamp: int, retained: int) -> dict[str, Any]:
    return {
        "service": "order",
        "end": timestamp,
        "attributes": [
            {"key": "process.memory.retained_bytes", "value": {"intValue": retained}},
            {
                "key": "process.memory.retention_limit_bytes",
                "value": {"intValue": 67_108_864},
            },
        ],
    }


def _synthetic_observations(case: dict[str, Any]) -> list[dict[str, str]]:
    identity = case["case_id"]
    observations = [
        {
            "id": f"evidence-{identity}-trace",
            "source": "traces",
            "summary": json.dumps(
                [
                    _memory_span(index * 10, value)
                    for index, value in enumerate(case["retained_bytes"], 1)
                ]
            ),
        }
    ]
    if case["deployment"]:
        observations.append(
            {
                "id": f"evidence-{identity}-deployment",
                "source": "deployments",
                "summary": json.dumps(
                    [{"service": "order", "version": "2.0.0", "previous_version": "1.0.0"}]
                ),
            }
        )
    return observations


def run(plan_path: Path, output: Path, *, key: str) -> None:
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
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
    output.mkdir(parents=True, exist_ok=False)
    outcomes: list[dict[str, Any]] = []
    for case in plan["cases"]:
        case_started = time.monotonic_ns()
        events: list[dict[str, Any]] = []
        observations = (
            _archive_observations(case)
            if case["source"] == "ARCHIVED_EVIDENCE"
            else _synthetic_observations(case)
        )
        observations_loaded = time.monotonic_ns()
        context = build_diagnosis_context(observations, {})
        context.update(
            incident_id=case["incident_id"],
            alert=case["alert"],
            public_cause_taxonomy=list(CAUSES),
            candidate_id_rule=(
                "Use exact public cause IDs for root-cause candidates. If unsupported, "
                "hand off with missing evidence."
            ),
        )
        context_built = time.monotonic_ns()
        def journal(event: dict[str, Any], target: list[dict[str, Any]] = events) -> None:
            target.append(dict(event))

        model = StructuredEvaluationModel(key, journal, max_calls=1)
        try:
            result = model.invoke(ModelPurpose.DIAGNOSE, context)
            report = result.output
            status = "SUCCEEDED"
            report_data: dict[str, Any] | None = report.model_dump(mode="json")
            error_code = None
        except StructuredModelFailure as error:
            status = "FAILED"
            report_data = None
            error_code = str(error)
        finished = time.monotonic_ns()
        outcome = {
            "case_id": case["case_id"],
            "source": case["source"],
            "status": status,
            "error_code": error_code,
            "input_hash": fingerprint({"case": case, "observations": observations}),
            "context_hash": fingerprint(context),
            "duration_ms": (finished - case_started) // 1_000_000,
            "stage_timing_ms": {
                "evidence_load": (observations_loaded - case_started) // 1_000_000,
                "context_build": (context_built - observations_loaded) // 1_000_000,
                "model_invoke": (finished - context_built) // 1_000_000,
            },
            "report": report_data,
            "events": events,
        }
        outcomes.append(outcome)
        with (output / "outcomes.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(outcome, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    document = {
        "schema_version": "diagnosis-generalization-result/1.0.0",
        "implementation_commit": revision,
        "plan_hash": hashlib.sha256(plan_bytes).hexdigest(),
        "labels_loaded": False,
        "provider": plan["provider"],
        "outcomes": outcomes,
    }
    (output / "results.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required")
    run(args.plan, args.output, key=key)


if __name__ == "__main__":  # pragma: no cover
    main()
