"""Published real-provider outcomes and hashes reproduce the reported counts."""

import hashlib
import json
from pathlib import Path

from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import Label, protocol_hash, score
from pydantic import TypeAdapter


def test_published_partial_comparison_reproduces_from_raw_artifacts() -> None:
    root = Path("evaluation/results/real-comparison/v1/run-001")
    hashes = json.loads((root / "file-hashes.json").read_text(encoding="utf-8"))
    for name, digest in hashes.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    digest = protocol_hash(Path("evaluation/real_protocol/v1/plan.json"))
    rows = OutcomeLedger(root / "outcomes").collect(protocol_hash=digest)
    labels = TypeAdapter(tuple[Label, ...]).validate_json(
        Path("evaluation/real_protocol/v1/evaluator_only/labels.json").read_bytes()
    )
    computed = score(
        labels,
        rows,
        expected_protocol_hash=digest,
        evaluated_modes=("single-agent", "controlled-graph"),
    )
    assert json.loads((root / "score.json").read_text()) == json.loads(json.dumps(computed))
    assert len(rows) == 54 and computed["comparison_complete"] is False
