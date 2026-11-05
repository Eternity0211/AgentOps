"""Frozen scoring retains all failures and refuses unfair or incomplete result sets."""

from typing import Any, cast

import pytest
from evaluation.real_scoring import CAUSES, CONTROLS, MODES, Label, Outcome, score


def fixture() -> tuple[tuple[Label, ...], tuple[Outcome, ...]]:
    labels = tuple(
        Label(instance_id=f"instance-{i:016x}", stratum=s)
        for i, s in enumerate(s for s in (*CAUSES, *CONTROLS) for _ in range(3))
    )
    rows = tuple(
        Outcome(
            instance_id=x.instance_id,
            mode=m,
            protocol_hash="a" * 64,
            input_hash="b" * 64,
            status="SUCCEEDED",
            candidates=(x.stratum,) if x.stratum in CAUSES else (),
            disposition="CANDIDATES" if x.stratum in CAUSES else "HUMAN_HANDOFF",
            missing_evidence_count=1,
            counter_evidence_addressed=True,
        )
        for x in labels
        for m in MODES
    )
    return labels, rows


def test_complete_scoring_and_failure_denominators() -> None:
    labels, rows = fixture()
    result = cast(dict[str, Any], score(labels, rows, expected_protocol_hash="a" * 64))
    assert all(
        x["top1"] == x["top3"] == 18 and x["safe_controls"] == 9 for x in result["modes"].values()
    )
    failed = tuple(x.model_copy(update={"status": "FAILED"}) for x in rows)
    result = cast(dict[str, Any], score(labels, failed, expected_protocol_hash="a" * 64))
    assert all(
        x["top1"] == 0 and x["fault_denominator"] == 18 and x["failures"] == 27
        for x in result["modes"].values()
    )


@pytest.mark.parametrize("mode", ["missing", "duplicate", "protocol", "input", "labels"])
def test_scoring_rejects_incomplete_or_unfair_results(mode: str) -> None:
    labels, rows = fixture()
    if mode == "missing":
        rows = rows[:-1]
    elif mode == "duplicate":
        rows = (*rows[:-1], rows[0])
    elif mode == "protocol":
        rows = (rows[0].model_copy(update={"protocol_hash": "c" * 64}), *rows[1:])
    elif mode == "input":
        rows = (rows[0].model_copy(update={"input_hash": "c" * 64}), *rows[1:])
    else:
        labels = labels[:-1]
    with pytest.raises(ValueError):
        score(labels, rows, expected_protocol_hash="a" * 64)
