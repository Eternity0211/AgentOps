"""Capture new known-family simulator instances without model calls or recovery credit."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from agentops_incident_commander.faults import SCENARIO_TARGETS, clean, inject
from evaluation.observation_snapshot import capture_reads, write_snapshot
from evaluation.run_live_diagnosis import ENVIRONMENT, ROOT, checkout, ready, wait_target


def capture(output: Path, *, smoke: bool = False) -> None:
    output.mkdir(parents=True, exist_ok=False)
    environment = {**os.environ, **ENVIRONMENT}
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    schedule = (
        [(None, "gateway")]
        if smoke
        else [
            (scenario, target)
            for scenario, target in [*SCENARIO_TARGETS.items(), (None, "gateway")]
            for _ in range(3)
        ]
    )
    with httpx.Client(timeout=15, trust_env=False) as client:
        ready(client)
        for scenario, target in schedule:
            identity = "instance-" + uuid4().hex[:16]
            sku = "capture-" + uuid4().hex[:16]
            record = {
                "instance_id": identity,
                "stratum": scenario or "normal",
                "revision": revision,
                "product_recovery_credit": False,
                "protocol_sha256": hashlib.sha256(
                    (ROOT / "evaluation/real_protocol/v1/plan.json").read_bytes()
                ).hexdigest(),
            }
            active = False
            try:
                baseline = checkout(client, sku=sku)
                record["baseline"] = baseline
                if baseline["status"] != 200:
                    raise RuntimeError("capture baseline unavailable")
                if scenario is not None:
                    active = True
                    if inject(scenario, root=ROOT, environment=environment) != 0:
                        raise RuntimeError("capture injection failed")
                    wait_target(target, environment)
                start = datetime.now(UTC)
                probes = [checkout(client, sku=sku) for _ in range(8)]
                time.sleep(20)
                end = datetime.now(UTC)
                reads = asyncio.run(capture_reads(start, end))
                record["input_hash"] = write_snapshot(
                    output / f"{identity}.json",
                    identity,
                    start,
                    end,
                    reads,
                    "Gateway checkout observations: " + json.dumps(probes),
                )
                record["status"] = "CAPTURED"
            except Exception:
                record["status"] = "FAILED"
                raise
            finally:
                try:
                    if active:
                        record["cleanup_exit"] = clean(root=ROOT, environment=environment)
                        wait_target(target, environment)
                    ready(client)
                    record["after_cleanup_status"] = checkout(client, sku=sku)["status"]
                    if record.get("cleanup_exit", 0) != 0 or record["after_cleanup_status"] != 200:
                        raise RuntimeError("capture cleanup verification failed")
                finally:
                    with (output / "evaluator-manifest.jsonl").open(
                        "a", encoding="utf-8"
                    ) as stream:
                        stream.write(json.dumps(record) + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    capture(args.output, smoke=args.smoke)


if __name__ == "__main__":
    main()
