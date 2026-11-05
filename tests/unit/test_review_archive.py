"""Archived real-provider reports can be checked without inventing missing records."""

import json
import shutil
from pathlib import Path

from evaluation.observation_snapshot import load_snapshot
from evaluation.review_archive import review_archive


def test_archive_review_checks_real_report_and_refuses_tampering(tmp_path: Path) -> None:
    archive = Path("evaluation/results/real-comparison/v1/run-001")
    files = [
        p
        for p in archive.rglob("diagnosis-report.json")
        if json.loads(p.read_text(encoding="utf-8"))["report"]["candidates"]
    ]
    assert files
    original = files[0].parent
    index = json.loads(Path("evaluation/datasets/real-v1/index.json").read_text(encoding="utf-8"))
    row = next(x for x in index if x["instance_id"] == original.name)
    snapshot = load_snapshot(
        Path("evaluation/datasets/real-v1/inputs") / f"{original.name}.json",
        expected_hash=row["input_hash"],
    )
    root = tmp_path / "review"
    shutil.copytree(original, root)
    result = review_archive(root, snapshot)
    assert result["task_successes"] == result["required_tasks"]
    assert result["declared_citations"] > 0 and result["unresolved_citations"] == 0
    manifests = list((root / "evidence").glob("evidence-records*.json"))
    originals = {path: path.read_bytes() for path in manifests}
    for path in manifests:
        records = json.loads(path.read_text(encoding="utf-8"))
        for entry in records:
            entry["evidence"]["tenant_id"]["value"] = "other-tenant"
        path.write_text(json.dumps(records), encoding="utf-8")
    assert review_archive(root, snapshot)["unresolved_citations"] > 0
    for path, content in originals.items():
        path.write_bytes(content)
    document = json.loads((root / "diagnosis-report.json").read_text(encoding="utf-8"))
    document["stored_report_hash"] = "0" * 64
    (root / "diagnosis-report.json").write_text(json.dumps(document), encoding="utf-8")
    assert review_archive(root, snapshot)["failure_type"] == "ValueError"
    assert review_archive(tmp_path / "missing", snapshot)["failure_type"] == "FileNotFoundError"
