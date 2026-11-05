"""Published real-provider outcomes and hashes reproduce the reported counts."""

import hashlib
import json
from pathlib import Path

import pytest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import Label, protocol_hash, score
from pydantic import TypeAdapter


@pytest.mark.parametrize(
    "folder,modes,count",
    [
        ("real-comparison", ("single-agent", "controlled-graph"), 54),
        ("simulated-memory", ("controlled-graph-simulated-memory",), 27),
    ],
)
def test_published_partial_comparison_reproduces_from_raw_artifacts(
    folder: str, modes: tuple[str, ...], count: int
) -> None:
    root = Path(f"evaluation/results/{folder}/v1/run-001")
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
        evaluated_modes=modes,
    )
    assert json.loads((root / "score.json").read_text()) == json.loads(json.dumps(computed))
    assert len(rows) == count and computed["comparison_complete"] is False
