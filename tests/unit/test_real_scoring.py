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


def test_wilson_and_missing_resource_values() -> None:
    from evaluation.real_scoring import distribution, wilson

    assert wilson(0, 18)[0] == 0
    assert wilson(18, 18)[1] == 1
    lower, upper = wilson(9, 18)
    assert lower == pytest.approx(1 - upper)
    assert distribution([None, 0, 10, 20]) == {
        "known": 3,
        "missing": 1,
        "raw": [0, 10, 20],
        "median": 10,
        "p95_nearest_rank": 20,
    }
    assert distribution([None])["median"] is None
    with pytest.raises(ValueError):
        wilson(1, 0)


def test_score_files_verifies_original_bytes(tmp_path: Any) -> None:
    import hashlib
    import json

    from evaluation.real_scoring import score_files

    labels, rows = fixture()
    protocol = tmp_path / "protocol.json"
    protocol.write_bytes(b"{}")
    digest = hashlib.sha256(b"{}").hexdigest()
    rows = tuple(row.model_copy(update={"protocol_hash": digest}) for row in rows)
    label_path, output_path = tmp_path / "labels.json", tmp_path / "outputs.json"
    label_path.write_text(json.dumps([x.model_dump(mode="json") for x in labels]), encoding="utf-8")
    output_path.write_text(json.dumps([x.model_dump(mode="json") for x in rows]), encoding="utf-8")
    label_hash = hashlib.sha256(label_path.read_bytes()).hexdigest()
    output_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    result = score_files(
        label_path, output_path, protocol, labels_sha256=label_hash, outcomes_sha256=output_hash
    )
    assert result["raw_outputs_sha256"] == output_hash
    output_path.write_bytes(output_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        score_files(
            label_path, output_path, protocol, labels_sha256=label_hash, outcomes_sha256=output_hash
        )


def test_protocol_hash_is_newline_independent(tmp_path: Any) -> None:
    from evaluation.real_scoring import protocol_hash

    one, two = tmp_path / "lf.json", tmp_path / "crlf.json"
    one.write_bytes(b'{\n"value":1\n}\n')
    two.write_bytes(b'{\r\n"value":1\r\n}\r\n')
    assert protocol_hash(one) == protocol_hash(two)


def test_partial_modes_are_explicitly_incomplete() -> None:
    labels, rows = fixture()
    modes = ("single-agent", "controlled-graph")
    subset = tuple(r for r in rows if r.mode in modes)
    result = score(labels, subset, expected_protocol_hash="a" * 64, evaluated_modes=modes)
    assert result["comparison_complete"] is False
    assert result["missing_modes"] == ["controlled-graph-memory"]
    with pytest.raises(ValueError):
        score(labels, subset, expected_protocol_hash="a" * 64)
