"""Explicit experimental controls derived from unchanged normal snapshot telemetry."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from evaluation.observation_snapshot import load_snapshot, write_snapshot


def derive_control(
    parent_path: Path,
    expected_hash: str,
    destination: Path,
    *,
    kind: Literal["insufficient-evidence", "counter-evidence"],
) -> dict[str, str]:
    parent = load_snapshot(parent_path, expected_hash=expected_hash)
    if kind not in ("insufficient-evidence", "counter-evidence"):
        raise ValueError("unknown control transform")
    identity = "instance-" + uuid4().hex[:16]
    reads = parent["reads"]
    if kind == "insufficient-evidence":
        reads = {
            key: {"status": "FAILED", "error_code": "CONTROL_SOURCE_WITHHELD"} for key in reads
        }
        alert = "A checkout incident was reported; investigate using available current evidence."
    else:
        alert = (
            "Unverified operator hypothesis: a faulty service deployment caused checkout errors. "
            "Investigate using current telemetry; this hypothesis is not verified evidence."
        )
    digest = write_snapshot(
        destination,
        identity,
        datetime.fromisoformat(parent["window_start"]),
        datetime.fromisoformat(parent["window_end"]),
        reads,
        alert,
    )
    manifest = {
        "instance_id": identity,
        "stratum": kind,
        "input_hash": digest,
        "parent_input_hash": expected_hash,
        "transform_version": "controls/1.0.0",
        "origin": "DERIVED_EXPERIMENTAL_CONTROL_NOT_LIVE_FAULT",
    }
    with destination.with_suffix(".control.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, sort_keys=True)
    return manifest
