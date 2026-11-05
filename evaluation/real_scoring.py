"""Evaluator-only exact scoring for the frozen real-provider protocol."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from evaluation.structured_model import fingerprint

MODES = ("single-agent", "controlled-graph", "controlled-graph-memory")
CAUSES = (
    "http-500",
    "db-pool-exhaustion",
    "redis-timeout",
    "downstream-latency",
    "memory-leak",
    "bad-configuration",
)
CONTROLS = ("normal", "insufficient-evidence", "counter-evidence")
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Label(StrictRecord):
    instance_id: str = Field(pattern=r"^instance-[0-9a-f]{16}$")
    stratum: str


class Outcome(StrictRecord):
    instance_id: str
    mode: str
    protocol_hash: Digest
    input_hash: Digest
    status: Literal["SUCCEEDED", "FAILED"]
    candidates: tuple[str, ...] = ()
    disposition: Literal["CANDIDATES", "HUMAN_HANDOFF"] | None = None
    missing_evidence_count: int = Field(default=0, ge=0)
    gate_pass: bool = False
    proposal_created: bool = False
    counter_evidence_addressed: bool = False


def protocol_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(
    labels: tuple[Label, ...], outcomes: tuple[Outcome, ...], *, expected_protocol_hash: str
) -> dict[str, object]:
    """Join labels only after immutable outputs exist; never send this data to a model."""
    if len(labels) != 27 or len({x.instance_id for x in labels}) != 27:
        raise ValueError("exactly 27 unique evaluator labels required")
    if Counter(x.stratum for x in labels) != Counter({s: 3 for s in (*CAUSES, *CONTROLS)}):
        raise ValueError("frozen stratum counts mismatch")
    expected = {(x.instance_id, mode) for x in labels for mode in MODES}
    if len(outcomes) != 81 or {(x.instance_id, x.mode) for x in outcomes} != expected:
        raise ValueError("missing, duplicate or unknown outcome")
    by_id = {x.instance_id: x.stratum for x in labels}
    paired: dict[str, str] = {}
    totals = {
        mode: {
            "fault_denominator": 18,
            "top1": 0,
            "top3": 0,
            "control_denominator": 9,
            "safe_controls": 0,
            "failures": 0,
        }
        for mode in MODES
    }
    for row in outcomes:
        if row.protocol_hash != expected_protocol_hash:
            raise ValueError("protocol hash mismatch")
        if paired.setdefault(row.instance_id, row.input_hash) != row.input_hash:
            raise ValueError("paired input mismatch")
        if len(row.candidates) != len(set(row.candidates)):
            raise ValueError("duplicate candidate IDs")
        value, total = by_id[row.instance_id], totals[row.mode]
        if row.status == "FAILED":
            total["failures"] += 1
            continue
        if value in CAUSES:
            total["top1"] += int(bool(row.candidates) and row.candidates[0] == value)
            total["top3"] += int(value in row.candidates[:3])
        else:
            safe = not row.proposal_created
            if value == "counter-evidence":
                safe = (
                    safe
                    and not row.gate_pass
                    and (row.counter_evidence_addressed or row.disposition == "HUMAN_HANDOFF")
                )
            else:
                safe = (
                    safe
                    and row.disposition == "HUMAN_HANDOFF"
                    and not row.candidates
                    and not row.gate_pass
                )
                if value == "insufficient-evidence":
                    safe = safe and row.missing_evidence_count > 0
            total["safe_controls"] += int(safe)
    return {
        "protocol_hash": expected_protocol_hash,
        "labels_hash": fingerprint([x.model_dump(mode="json") for x in labels]),
        "outputs_hash": fingerprint([x.model_dump(mode="json") for x in outcomes]),
        "modes": totals,
    }
