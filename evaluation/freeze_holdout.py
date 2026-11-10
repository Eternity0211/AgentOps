"""Freeze an audited holdout with separate runtime inputs and evaluator labels."""

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from evaluation.audit_capture import audit_capture
from evaluation.derived_controls import derive_control
from evaluation.observation_snapshot import load_snapshot
from evaluation.real_scoring import CAUSES
from evaluation.run_real_batch import preflight

PLAN = Path(__file__).parent / "real_protocol/v2/capture-plan.json"
PROBE_PREFIX = "Gateway checkout observations: "


def freeze(capture: Path, dataset: Path, evaluator: Path) -> None:
    dataset, evaluator = dataset.resolve(), evaluator.resolve()
    if (
        dataset.exists()
        or evaluator.exists()
        or (dataset == evaluator or dataset in evaluator.parents or evaluator in dataset.parents)
    ):
        raise ValueError("freeze requires new separate output directories")
    digest = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    rows = [
        json.loads(line)
        for line in (capture / "evaluator-manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    expected = Counter((name, count) for name in (*CAUSES, "normal") for count in (4, 8, 12))
    if Counter((r["stratum"], r["planned_probe_count"]) for r in rows) != expected:
        raise ValueError("holdout schedule mismatch")
    if any(r["protocol_sha256"] != digest for r in rows):
        raise ValueError("holdout protocol binding mismatch")
    if len({r["revision"] for r in rows}) != 1:
        raise ValueError("holdout capture revision mismatch")
    for row in rows:
        identity = row["instance_id"]
        if not isinstance(identity, str) or not re.fullmatch(r"instance-[0-9a-f]{16}", identity):
            raise ValueError("invalid capture identity")
    audited = audit_capture(capture, require_complete=True)
    for row in rows:
        identity = row["instance_id"]
        snapshot = load_snapshot(capture / f"{identity}.json", expected_hash=row["input_hash"])
        alert = snapshot["alert"]
        if (
            snapshot["instance_id"] != identity
            or not alert.startswith(PROBE_PREFIX)
            or len(json.loads(alert[len(PROBE_PREFIX) :])) != row["planned_probe_count"]
        ):
            raise ValueError("holdout observation binding mismatch")

    inputs = dataset / "inputs"
    inputs.mkdir(parents=True, exist_ok=False)
    evaluator.mkdir(parents=True, exist_ok=False)
    index, labels = [], []
    for row in sorted(rows, key=lambda row: row["instance_id"]):
        identity, source_hash = row["instance_id"], row["input_hash"]
        source = capture / f"{identity}.json"
        shutil.copyfile(source, inputs / source.name)
        index.append({"instance_id": identity, "input_hash": source_hash})
        labels.append({"instance_id": identity, "stratum": row["stratum"]})
        if row["stratum"] == "normal":
            for kind in ("insufficient-evidence", "counter-evidence"):
                temporary = inputs / f"{identity}-{kind}.json"
                control = derive_control(
                    source,
                    source_hash,
                    temporary,
                    kind=kind,
                    manifest_path=evaluator / f"{identity}-{kind}.json",
                )
                control_id = control["instance_id"]
                temporary.rename(inputs / f"{control_id}.json")
                index.append({"instance_id": control_id, "input_hash": control["input_hash"]})
                labels.append({"instance_id": control_id, "stratum": kind})
    for path, content in (
        (dataset / "index.json", sorted(index, key=lambda row: row["instance_id"])),
        (evaluator / "labels.json", sorted(labels, key=lambda row: row["instance_id"])),
        (evaluator / "capture-audit.json", audited),
    ):
        with path.open("x", encoding="utf-8") as stream:
            json.dump(content, stream, indent=2)
            stream.write("\n")
    preflight(dataset)
    shutil.copyfile(capture / "evaluator-manifest.jsonl", evaluator / "evaluator-manifest.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("evaluator", type=Path)
    args = parser.parse_args()
    freeze(args.capture, args.dataset, args.evaluator)


if __name__ == "__main__":
    main()
