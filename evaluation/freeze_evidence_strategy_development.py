"""Freeze a label-isolated development set for the FC4 evidence-strategy pilot."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from evaluation.freeze_lab_holdout import FAULT_TARGETS, _reads
from evaluation.observation_snapshot import load_snapshot, write_snapshot
from evaluation.real_scoring import CAUSES, CONTROLS

GENERATOR = Path(__file__)
NAMESPACE = "fc4-evidence-strategy-development-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(key: str) -> str:
    return f"instance-{hashlib.sha256(f'{NAMESPACE}:{key}'.encode()).hexdigest()[:16]}"


def _memory_spans(case_number: int) -> list[dict[str, Any]]:
    base = 48_000_000 + case_number * 100_000
    spans = []
    for index in range(5):
        attributes: list[dict[str, Any]] = [
            {
                "key": "process.memory.retained_bytes",
                "value": {"intValue": base + index * 8_000_000},
            },
            {
                "key": "process.memory.retention_limit_bytes",
                "value": {"intValue": 160_000_000},
            },
            {
                "key": "process.memory.retention_allocations",
                "value": {"intValue": 1_000 + index * 500},
            },
            {
                "key": "process.memory.retention_releases",
                "value": {"intValue": 200 + index * 50},
            },
        ]
        if index in (2, 3):
            attributes.extend(
                [
                    {
                        "key": "process.memory.gc.cycle",
                        "value": {"intValue": 7 + case_number},
                    },
                    {
                        "key": "process.memory.gc.phase",
                        "value": {"stringValue": "BEFORE" if index == 2 else "AFTER"},
                    },
                ]
            )
        spans.append(
            {
                "service": FAULT_TARGETS["memory-leak"],
                "start": str(1_000_000_000 + index * 10_000_000_000),
                "end": str(1_100_000_000 + index * 10_000_000_000),
                "attributes": attributes,
                "status": {},
            }
        )
    return spans


def _case_reads(
    role: str,
    case_number: int,
    start: datetime,
    end: datetime,
    *,
    cause: str | None,
) -> dict[str, Any]:
    dependency_scope = (
        "cross-service"
        if cause == "bad-configuration"
        else ("cross-service" if case_number % 2 else "direct")
    )
    reads = _reads(
        role,  # type: ignore[arg-type]
        case_number,
        start,
        end,
        cause=cause,
        dependency_scope=dependency_scope,
        deployment_timing=("recent-correlated" if case_number % 3 == 0 else "old-uncorrelated"),
        signal_strength=("bounded-medium" if case_number % 2 else "bounded-high"),
    )
    if cause == "memory-leak":
        trace = reads[f"query_traces:{FAULT_TARGETS[cause]}"]["output"]
        trace["summary"] = json.dumps(_memory_spans(case_number), separators=(",", ":"))
        trace["records_seen"] = 5
    return reads


def freeze(plan_path: Path, dataset: Path, evaluator: Path) -> None:
    dataset, evaluator = dataset.resolve(), evaluator.resolve()
    if dataset.exists() or evaluator.exists() or dataset == evaluator:
        raise ValueError("development freeze requires new separate outputs")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if (
        plan.get("schema_version") != "evidence-strategy-development-plan/1.0.0"
        or tuple(plan.get("fault_families", ())) != CAUSES
        or tuple(plan.get("control_strata", ())) != CONTROLS
        or plan.get("cases_per_stratum") != 3
        or plan.get("total_cases") != 27
    ):
        raise ValueError("development plan mismatch")

    inputs = dataset / "inputs"
    inputs.mkdir(parents=True)
    evaluator.mkdir(parents=True)
    attributes = "*.json -text whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\n"
    (dataset / ".gitattributes").write_text(attributes, encoding="utf-8")
    (evaluator / ".gitattributes").write_text(attributes, encoding="utf-8")
    index: list[dict[str, str]] = []
    labels: list[dict[str, str]] = []
    case_number = 0
    for stratum in (*CAUSES, *CONTROLS):
        for offset in range(3):
            identity = _identity(f"{stratum}:{offset}")
            start = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(minutes=case_number * 11)
            end = start + timedelta(minutes=5)
            cause = stratum if stratum in CAUSES else None
            role = "fault" if cause is not None else stratum
            alert = (
                "Checkout health degraded. Use current read-only telemetry to identify only "
                "an evidence-supported root cause."
            )
            digest = write_snapshot(
                inputs / f"{identity}.json",
                identity,
                start,
                end,
                _case_reads(role, case_number, start, end, cause=cause),
                alert,
            )
            index.append({"instance_id": identity, "input_hash": digest})
            labels.append({"instance_id": identity, "stratum": stratum})
            case_number += 1

    index.sort(key=lambda item: item["instance_id"])
    labels.sort(key=lambda item: item["instance_id"])
    (dataset / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    (evaluator / "labels.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
    for row in index:
        load_snapshot(inputs / f"{row['instance_id']}.json", expected_hash=row["input_hash"])

    files = [
        dataset / ".gitattributes",
        dataset / "index.json",
        *sorted(inputs.glob("*.json")),
        evaluator / ".gitattributes",
        evaluator / "labels.json",
    ]
    hashes = {
        ("dataset/" + path.relative_to(dataset).as_posix())
        if path.is_relative_to(dataset)
        else ("evaluator/" + path.relative_to(evaluator).as_posix()): _sha256(path)
        for path in files
    }
    manifest = {
        "schema_version": "evidence-strategy-development-freeze/1.0.0",
        "namespace": NAMESPACE,
        "case_count": len(index),
        "plan_sha256": _sha256(plan_path),
        "generator_sha256": _sha256(GENERATOR),
        "fixture_generator_sha256": _sha256(Path("evaluation/freeze_lab_holdout.py")),
        "files": hashes,
    }
    (evaluator / "freeze-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    args = parser.parse_args()
    freeze(args.plan, args.dataset, args.evaluator)


if __name__ == "__main__":
    main()
