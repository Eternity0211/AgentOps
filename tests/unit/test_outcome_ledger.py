from pathlib import Path

import pytest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import Outcome


def test_outcome_ledger_preserves_failures_and_refuses_overwrite(tmp_path: Path) -> None:
    ledger = OutcomeLedger(tmp_path / "rows")
    row = Outcome(
        instance_id="instance-0000000000000001",
        mode="controlled-graph",
        protocol_hash="a" * 64,
        input_hash="b" * 64,
        status="FAILED",
    )
    assert len(ledger.append(row)) == 64
    with pytest.raises(FileExistsError):
        ledger.append(row)
    assert ledger.collect(protocol_hash="a" * 64) == (row,)
    with pytest.raises(ValueError, match="protocol mismatch"):
        ledger.collect(protocol_hash="c" * 64)
    assert len(ledger.export(tmp_path / "all.json", protocol_hash="a" * 64)) == 64
    with pytest.raises(FileExistsError):
        ledger.export(tmp_path / "all.json", protocol_hash="a" * 64)
