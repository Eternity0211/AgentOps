"""Concurrent archive ownership is independently checked, including tampered negative fixtures."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from evaluation.verify_concurrent_records import verify

ROOT = Path("evaluation/results/concurrent-registered/v1/run-001")


def test_actual_concurrent_archive_counts_peaks_and_ownership() -> None:
    for name, digest in json.loads((ROOT / "file-hashes.json").read_text(encoding="utf-8")).items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    verified = verify(ROOT)
    assert verified["reports_bound"] == 9 and verified["evidence_artifacts_verified"] == 36
    assert verified["citation_occurrences_verified"] == 17 and verified["jobs_completed_once"] == 6
    assert verified["approvals"] == verified["executions"] == 0
    for size in (2, 4):
        batch = json.loads((ROOT / f"batch-{size}.json").read_text(encoding="utf-8"))
        assert batch["peak_investigation_handlers"] == batch["completed_jobs"] == size
        assert batch["batch_error_type"] is None and len(batch["cases"]) == size
        assert (
            batch["capture_sha256"]
            == hashlib.sha256((ROOT / f"capture-{size}.json").read_bytes()).hexdigest()
        )
    summary = json.loads((ROOT / "summary.json").read_text(encoding="utf-8"))
    assert summary["provider_starts"] == 21 and summary["cases"] == 6


@pytest.mark.parametrize(
    "tamper", ["report_owner", "evidence_owner", "report_bytes", "artifact_bytes", "trace_owner"]
)
def test_concurrent_archive_rejects_cross_scope_or_changed_content(
    tmp_path: Path, tamper: str
) -> None:
    root = tmp_path / "fixture"
    shutil.copytree(ROOT, root)
    sql = root / "sql-records.json"
    rows = json.loads(sql.read_text(encoding="utf-8"))
    report = rows["diagnosis_reports"][0]
    other = next(
        j["incident_id"] for j in rows["jobs"] if j["incident_id"] != report["incident_id"]
    )
    if tamper == "report_owner":
        report["incident_id"] = other
    elif tamper == "evidence_owner":
        e = rows["evidence"][0]
        e["incident_id"] = next(
            j["incident_id"] for j in rows["jobs"] if j["incident_id"] != e["incident_id"]
        )
    elif tamper == "report_bytes":
        report["report"]["explanation"] = "changed fixture"
    elif tamper == "trace_owner":
        next(t for t in rows["model_call_traces"] if t["id"] == report["model_call_id"])[
            "incident_id"
        ] = other
    else:
        e = rows["evidence"][0]
        blob = (
            root
            / "cases"
            / e["incident_id"]
            / "evidence/blobs"
            / e["content_hash"][:2]
            / e["content_hash"]
        )
        blob.write_bytes(blob.read_bytes() + b"changed fixture")
    sql.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(ValueError, match="CONCURRENT_"):
        verify(root)
