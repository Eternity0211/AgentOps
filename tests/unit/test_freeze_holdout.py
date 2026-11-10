"""Verify the holdout freeze preserves inputs and keeps labels isolated."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from evaluation.freeze_holdout import PLAN, PROBE_PREFIX, freeze
from evaluation.real_scoring import CAUSES
from evaluation.run_real_batch import preflight


def test_freeze_holdout_checks_plan_and_separates_labels(tmp_path: Path) -> None:
    source = next(Path("evaluation/datasets/real-v1/inputs").glob("*.json"))
    template = json.loads(source.read_bytes())
    capture = tmp_path / "capture"
    capture.mkdir()
    rows = []
    for index, (stratum, count) in enumerate(
        (stratum, count) for stratum in (*CAUSES, "normal") for count in (4, 8, 12)
    ):
        identity = f"instance-{index:016x}"
        raw = json.dumps(
            {
                **template,
                "instance_id": identity,
                "alert": PROBE_PREFIX + json.dumps([{"status": 200}] * count),
            }
        ).encode()
        (capture / f"{identity}.json").write_bytes(raw)
        rows.append(
            {
                "instance_id": identity,
                "stratum": stratum,
                "planned_probe_count": count,
                "revision": "fixture",
                "protocol_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
                "input_hash": hashlib.sha256(raw).hexdigest(),
                "status": "CAPTURED",
                "baseline": {"status": 200},
                "after_cleanup_status": 200,
                "cleanup_exit": 0,
            }
        )
    manifest = capture / "evaluator-manifest.jsonl"
    manifest.write_text(json.dumps(rows[0]), encoding="utf-8")
    dataset, evaluator = tmp_path / "dataset", tmp_path / "evaluator"
    with pytest.raises(ValueError, match="schedule"):
        freeze(capture, dataset, evaluator)
    assert not dataset.exists() and not evaluator.exists()

    manifest.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    freeze(capture, dataset, evaluator)
    inputs = preflight(dataset)
    labels = json.loads((evaluator / "labels.json").read_bytes())
    assert {row["instance_id"] for row in inputs} == {row["instance_id"] for row in labels}
    assert Counter(row["stratum"] for row in labels) == Counter(
        {stratum: 3 for stratum in (*CAUSES, "normal", "counter-evidence", "insufficient-evidence")}
    )
    assert {path.name for path in dataset.iterdir()} == {"inputs", "index.json"}
    assert len(list(evaluator.glob("instance-*.json"))) == 6
