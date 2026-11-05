"""Create-only, hash-bound provider outcomes with no evaluator labels."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from evaluation.real_scoring import MODES, Outcome


class OutcomeLedger:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def append(self, outcome: Outcome) -> str:
        if outcome.mode not in MODES:
            raise ValueError("unknown evaluation mode")
        identity = hashlib.sha256(f"{outcome.instance_id}:{outcome.mode}".encode()).hexdigest()
        encoded = outcome.model_dump_json().encode()
        with (self.root / f"{identity}.json").open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(encoded).hexdigest()

    def collect(self, *, protocol_hash: str) -> tuple[Outcome, ...]:
        records = []
        for path in sorted(self.root.glob("*.json")):
            if path.stat().st_size > 65536:
                raise ValueError("outcome size exceeded")
            record = Outcome.model_validate_json(path.read_bytes())
            identity = hashlib.sha256(f"{record.instance_id}:{record.mode}".encode()).hexdigest()
            if path.stem != identity or record.protocol_hash != protocol_hash:
                raise ValueError("outcome identity/protocol mismatch")
            records.append(record)
        return tuple(records)

    def export(self, destination: Path, *, protocol_hash: str) -> str:
        records = self.collect(protocol_hash=protocol_hash)
        encoded = json.dumps(
            [r.model_dump(mode="json") for r in records],
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        with destination.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(encoded).hexdigest()
