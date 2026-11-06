"""Frozen rules supplement preserves hash failures, read failures and separate scoring."""

import json
from pathlib import Path
from typing import Any

import pytest
from evaluation.real_scoring import RULES_MODE, Label, score
from evaluation.run_rules_snapshots import run

DATASET = Path("evaluation/datasets/real-v1")
PROTOCOL = Path("evaluation/real_protocol/rules-v1/plan.json")


def test_rules_same_inputs_raw_results_and_original_score_conditions(tmp_path: Path) -> None:
    outputs = run(DATASET, PROTOCOL, tmp_path / "run")
    assert len(outputs) == 27 and all(o.mode == RULES_MODE for o in outputs)
    assert all(
        o.input_tokens == o.output_tokens == o.cost_upper_bound_nanousd == 0 for o in outputs
    )
    for output in outputs:
        raw = json.loads(
            (tmp_path / "run" / f"{output.instance_id}.json").read_text(encoding="utf-8")
        )
        assert len(raw["snapshot_reads"]) == 12
        assert output.candidates == () and not output.proposal_created and not output.gate_pass
    # Labels enter only after run() returned and all immutable per-instance outputs exist.
    labels = tuple(
        Label.model_validate(v)
        for v in json.loads(
            Path("evaluation/real_protocol/v1/evaluator_only/labels.json").read_text(
                encoding="utf-8"
            )
        )
    )
    result: Any = score(
        labels,
        outputs,
        expected_protocol_hash=outputs[0].protocol_hash,
        evaluated_modes=(RULES_MODE,),
    )
    assert result["comparison_complete"] is False
    assert result["modes"][RULES_MODE]["fault_denominator"] == 18
    assert result["modes"][RULES_MODE]["top1"] == 0
    assert result["modes"][RULES_MODE]["control_denominator"] == 9


def test_rules_rejects_changed_frozen_index_before_creating_outputs(tmp_path: Path) -> None:
    plan = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    plan["dataset_index_sha256"] = "0" * 64
    protocol = tmp_path / "changed.json"
    protocol.write_text(json.dumps(plan), encoding="utf-8")
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="frozen input mismatch"):
        run(DATASET, protocol, output)
    assert not output.exists()


def test_rules_unavailable_snapshot_source_stays_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evaluation.run_rules_snapshots as runner
    from evaluation.observation_snapshot import load_snapshot

    original = load_snapshot

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        snapshot = original(*args, **kwargs)
        snapshot["reads"]["query_metrics:gateway"] = {"status": "FAILED"}
        return snapshot

    monkeypatch.setattr(runner, "load_snapshot", unavailable)
    outputs = runner.run(DATASET, PROTOCOL, tmp_path / "run")
    assert len(outputs) == 27 and all(o.status == "FAILED" for o in outputs)
    assert all(o.disposition is None for o in outputs)
