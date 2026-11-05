"""Capture audit refuses missing cleanup and preserves failed attempts."""

import json
from pathlib import Path
from typing import Any

import pytest
from evaluation.audit_capture import audit_capture


@pytest.mark.parametrize("mode", ["failure", "duplicate", "cleanup"])
def test_capture_audit_negative_records(tmp_path: Path, mode: str) -> None:
    row: dict[str, Any] = {"instance_id": "instance-0000000000000001", "status": "FAILED"}
    rows = [row, row] if mode == "duplicate" else [row]
    if mode == "cleanup":
        rows = [
            {
                "instance_id": row["instance_id"],
                "status": "CAPTURED",
                "stratum": "http-500",
                "baseline": {"status": 200},
                "after_cleanup_status": 200,
            }
        ]
    (tmp_path / "evaluator-manifest.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    if mode == "failure":
        assert audit_capture(tmp_path)["failed_capture_ids"] == [row["instance_id"]]
        with pytest.raises(ValueError, match="incomplete"):
            audit_capture(tmp_path, require_complete=True)
    else:
        with pytest.raises(ValueError, match=r"duplicate|cleanup"):
            audit_capture(tmp_path)
