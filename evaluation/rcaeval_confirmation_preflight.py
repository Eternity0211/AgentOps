"""Fail-closed readiness audit for the frozen RCAEval confirmation."""

from __future__ import annotations

import argparse
import hashlib
import os
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from evaluation.rcaeval_contract import TaskIndex, load_protocol, protocol_sha256


class Status(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class Blocker(StrEnum):
    SOURCE_INDEX_MISSING = "SOURCE_INDEX_MISSING"
    SOURCE_INDEX_HASH_MISMATCH = "SOURCE_INDEX_HASH_MISMATCH"
    TELEMETRY_ROOT_MISSING = "TELEMETRY_ROOT_MISSING"
    TASK_EXPORT_MISSING = "TASK_EXPORT_MISSING"
    TASK_EXPORT_INVALID = "TASK_EXPORT_INVALID"
    PROVIDER_CREDENTIAL_MISSING = "PROVIDER_CREDENTIAL_MISSING"


class PreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["rcaeval-confirmation-preflight/1.0.0"]
    status: Status
    protocol_sha256: str
    source_revision: str
    blockers: tuple[Blocker, ...]
    source_index_present: bool
    source_index_hash_matches: bool | None
    telemetry_root_present: bool
    task_export_present: bool
    task_export_case_count: int | None
    provider_credential_present: bool
    old_confirmation_outcomes_touched: Literal[False] = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(
    *, protocol_path: Path, source_index: Path, telemetry_root: Path, task_export: Path
) -> PreflightReport:
    protocol = load_protocol(protocol_path)
    blockers: list[Blocker] = []
    source_present = source_index.is_file()
    source_matches: bool | None = None
    if not source_present:
        blockers.append(Blocker.SOURCE_INDEX_MISSING)
    else:
        source_matches = _sha256(source_index) == protocol.source.index_sha256
        if not source_matches:
            blockers.append(Blocker.SOURCE_INDEX_HASH_MISMATCH)
    telemetry_present = telemetry_root.is_dir()
    if not telemetry_present:
        blockers.append(Blocker.TELEMETRY_ROOT_MISSING)
    export_index = task_export / "task-index.json"
    export_present = export_index.is_file()
    case_count: int | None = None
    if not export_present:
        blockers.append(Blocker.TASK_EXPORT_MISSING)
    else:
        try:
            index = TaskIndex.model_validate_json(export_index.read_bytes())
            case_count = len(index.tasks)
            if index.protocol_sha256 != protocol_sha256(protocol) or case_count != 180:
                blockers.append(Blocker.TASK_EXPORT_INVALID)
        except (OSError, ValueError):
            blockers.append(Blocker.TASK_EXPORT_INVALID)
    credential_present = bool(os.environ.get("DEEPSEEK_API_KEY", ""))
    if not credential_present:
        blockers.append(Blocker.PROVIDER_CREDENTIAL_MISSING)
    return PreflightReport(
        schema_version="rcaeval-confirmation-preflight/1.0.0",
        status=Status.READY if not blockers else Status.BLOCKED,
        protocol_sha256=protocol_sha256(protocol),
        source_revision=protocol.source.revision,
        blockers=tuple(dict.fromkeys(blockers)),
        source_index_present=source_present,
        source_index_hash_matches=source_matches,
        telemetry_root_present=telemetry_present,
        task_export_present=export_present,
        task_export_case_count=case_count,
        provider_credential_present=credential_present,
        old_confirmation_outcomes_touched=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--telemetry-root", type=Path, required=True)
    parser.add_argument("--task-export", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("preflight report already exists")
    report = audit(
        protocol_path=args.protocol,
        source_index=args.source_index,
        telemetry_root=args.telemetry_root,
        task_export=args.task_export,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", "utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
