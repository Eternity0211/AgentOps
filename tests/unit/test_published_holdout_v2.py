"""Recompute frozen holdout scores and verify the archived inputs."""

import hashlib
import json
from pathlib import Path

import pytest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import RULES_MODE, Label, Outcome, protocol_hash, score
from evaluation.run_real_batch import preflight


@pytest.mark.parametrize("rules", [False, True])
def test_v2_holdout_publication_recomputes(rules: bool) -> None:
    root = Path("evaluation/results") / ("rules-snapshots" if rules else "real-holdout")
    root = root / "v2/run-001"
    for name, digest in json.loads((root / "file-hashes.json").read_bytes()).items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    evaluator = Path("evaluation/real_protocol/v2/evaluator_only")
    for name, digest in json.loads((evaluator / "freeze-hashes.json").read_bytes()).items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
    labels = tuple(
        Label.model_validate(x) for x in json.loads((evaluator / "labels.json").read_bytes())
    )
    if rules:
        plan = Path("evaluation/real_protocol/rules-v2/plan.json")
        outcomes = tuple(
            Outcome.model_validate_json(json.dumps(json.loads(p.read_bytes())["outcome"]))
            for p in sorted(root.glob("instance-*.json"))
        )
        modes: tuple[str, ...] = (RULES_MODE,)
    else:
        plan = Path("evaluation/real_protocol/v1/plan.json")
        outcomes = OutcomeLedger(root / "outcomes").collect(protocol_hash=protocol_hash(plan))
        modes = ("single-agent", "controlled-graph")
        revisions = {
            json.loads(p.read_bytes())["code_revision"] for p in root.rglob("runtime.json")
        }
        assert revisions == {"6a9ea91854e5e65b602f348c81bc4cffe8848fbb"}
    index = {
        row["instance_id"]: row["input_hash"]
        for row in preflight(Path("evaluation/datasets/real-v2"))
    }
    assert all(outcome.input_hash == index[outcome.instance_id] for outcome in outcomes)
    computed = score(
        labels, outcomes, expected_protocol_hash=protocol_hash(plan), evaluated_modes=modes
    )
    # Canonicalize tuples to JSON lists before comparing the archived representation.
    assert json.loads(json.dumps(computed)) == json.loads((root / "score.json").read_bytes())
