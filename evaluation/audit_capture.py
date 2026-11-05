"""Audit capture completeness and source availability before provider evaluation."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation.observation_snapshot import load_snapshot


def audit_capture(root: Path, *, require_complete: bool = False) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in (root / "evaluator-manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    identities = [r["instance_id"] for r in rows]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate capture identities")
    successful: Counter[str] = Counter()
    failed_sources: Counter[str] = Counter()
    failed = []
    for row in rows:
        if row.get("status") != "CAPTURED":
            failed.append(row["instance_id"])
            continue
        if (
            row.get("baseline", {}).get("status") != 200
            or row.get("after_cleanup_status") != 200
            or row.get("cleanup_exit", 0) != 0
            or (row.get("stratum") != "normal" and row.get("cleanup_exit") != 0)
        ):
            raise ValueError("capture baseline/cleanup invalid")
        snapshot = load_snapshot(
            root / f"{row['instance_id']}.json", expected_hash=row["input_hash"]
        )
        for source, value in snapshot["reads"].items():
            if value["status"] != "SUCCEEDED":
                failed_sources[source] += 1
        successful[row["stratum"]] += 1
    if require_complete:
        from evaluation.real_scoring import CAUSES

        if successful != Counter({name: 3 for name in (*CAUSES, "normal")}) or failed:
            raise ValueError("capture dataset is incomplete")
    return {
        "record_count": len(rows),
        "successful_strata": dict(successful),
        "failed_capture_ids": failed,
        "unavailable_sources": dict(failed_sources),
        "product_recovery_credit": False,
    }
