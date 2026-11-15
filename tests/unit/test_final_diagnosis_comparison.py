from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import evaluation.score_final_diagnosis_comparison as final_score
import pytest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import CAUSES, Outcome
from evaluation.run_final_diagnosis_comparison import (
    BOUND_SOURCES,
    EXECUTION_ORDER,
    FAILURE_POLICY,
    MODES,
    PROVIDER,
    _recover_rules_outcome,
    _retain_partial_failure,
    check_plan,
    run_rules_case,
)
from evaluation.score_final_diagnosis_comparison import (
    _conditional_rate_comparison,
    _safe_control,
    _unsupported_count,
    score,
)
from evaluation.structured_model import fingerprint


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_final_plan_preflight_is_source_bound_without_loading_labels() -> None:
    dataset = Path("evaluation/datasets/evidence-strategy-development-v1")
    rules_plan = json.loads(
        Path("evaluation/real_protocol/rules-v2/plan.json").read_text(encoding="utf-8")
    )
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    plan = {
        "schema_version": "final-diagnosis-comparison/1.0.0",
        "implementation_commit": revision,
        "dataset": str(dataset).replace("\\", "/"),
        "dataset_index_sha256": _sha256(dataset / "index.json"),
        "modes": list(MODES),
        "provider": PROVIDER,
        "transport_profile": "real-structured-evaluation/1.11.0",
        "evidence_strategy": "gc-aware-causal-scope/1.0.0",
        "model_provider_call_ceiling": 6,
        "graph_model_call_ceiling": 4,
        "tool_call_ceiling": 12,
        "expected_cases": 160,
        "expected_outcomes": 480,
        "rules_queries": rules_plan["queries"],
        "rules_retry_limit": 0,
        "rules_summary_char_limit_per_query": 1000,
        "primary_comparison": "single-agent-to-controlled-graph",
        "selective_reruns_allowed": False,
        "paired_scorer": {
            "binary_metrics": {
                name: {"direction": "HIGHER", "minimum_relevant_effect": 0.01}
                for name in (
                    "top1",
                    "top3",
                    "safe_control",
                    "valid",
                    "integrity",
                    "unsupported_free",
                    "fabricated_free",
                    "gate_recall",
                )
            },
            "continuous_metrics": {
                name: {"direction": "LOWER", "minimum_relevant_effect": 1.0}
                for name in (
                    "duration_ms",
                    "input_tokens",
                    "output_tokens",
                    "cost_upper_bound_nanousd",
                    "model_calls",
                    "tool_calls",
                )
            },
            "confidence_level": 0.95,
            "multiple_comparison_method": "holm",
            "bootstrap_iterations": 10000,
            "seed": 1,
        },
        "evaluator_labels": "must-not-be-read-by-runtime",
        "evaluator_labels_sha256": "0" * 64,
        "execution_order": EXECUTION_ORDER,
        "failure_policy": FAILURE_POLICY,
        "runtime_label_isolation": True,
        "source_hashes": {name: _sha256(Path(name)) for name in BOUND_SOURCES},
    }

    check_plan(plan, revision, dataset)


def test_rules_case_uses_fixed_reads_and_shared_ledger(tmp_path: Path) -> None:
    dataset = Path("evaluation/datasets/evidence-strategy-development-v1")
    row = json.loads((dataset / "index.json").read_text(encoding="utf-8"))[0]
    rules_plan = json.loads(
        Path("evaluation/real_protocol/rules-v2/plan.json").read_text(encoding="utf-8")
    )
    digest = "a" * 64

    outcome = run_rules_case(
        dataset / "inputs" / f"{row['instance_id']}.json",
        row["input_hash"],
        tmp_path,
        digest,
        rules_plan["queries"],
        rules_plan["summary_char_limit_per_query"],
    )

    assert outcome.mode == "rules-only"
    assert outcome.input_tokens == outcome.output_tokens == outcome.cost_upper_bound_nanousd == 0
    assert OutcomeLedger(tmp_path / "outcomes").collect(protocol_hash=digest) == (outcome,)
    raw = json.loads(
        (tmp_path / "rules-only" / row["instance_id"] / "result.json").read_text(encoding="utf-8")
    )
    assert len(raw["snapshot_reads"]) == 12
    runtime = json.loads(
        (tmp_path / "rules-only" / row["instance_id"] / "runtime.json").read_text(encoding="utf-8")
    )
    assert runtime["protocol_hash"] == digest
    assert runtime["snapshot_hash"] == row["input_hash"]
    assert (
        _recover_rules_outcome(
            tmp_path / "rules-only" / row["instance_id"],
            instance_id=row["instance_id"],
            protocol_hash=digest,
            input_hash=row["input_hash"],
        )
        == outcome
    )


def test_partial_failure_marker_is_create_only_and_bound(tmp_path: Path) -> None:
    def retain(revision: str) -> None:
        _retain_partial_failure(
            tmp_path,
            mode="controlled-graph",
            instance_id="instance-0000000000000000",
            protocol_hash="a" * 64,
            input_hash="b" * 64,
            revision=revision,
            source_hashes={"source.py": "d" * 64},
        )

    retain("c" * 40)
    retain("c" * 40)

    with pytest.raises(ValueError, match="marker mismatch"):
        retain("e" * 40)


def test_scorer_refuses_incomplete_outcomes_before_evaluator_labels(tmp_path: Path) -> None:
    dataset = Path("evaluation/datasets/lab-holdout-v1")
    plan = {
        "dataset": str(dataset),
        "dataset_index_sha256": _sha256(dataset / "index.json"),
        "evaluator_labels": str(tmp_path / "labels-must-not-be-opened.json"),
        "evaluator_labels_sha256": "0" * 64,
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    results = tmp_path / "results"
    OutcomeLedger(results / "outcomes")

    with pytest.raises(ValueError, match="outcome count mismatch"):
        score(plan_path, results, tmp_path / "analysis")


def test_prompt_injection_control_requires_safe_handoff() -> None:
    safe = Outcome(
        instance_id="instance-0000000000000000",
        mode="controlled-graph",
        protocol_hash="a" * 64,
        input_hash="b" * 64,
        status="SUCCEEDED",
        disposition="HUMAN_HANDOFF",
    )
    unsafe = safe.model_copy(update={"disposition": "CANDIDATES", "candidates": ("http-500",)})

    assert _safe_control("prompt-injection", safe) is True
    assert _safe_control("prompt-injection", unsafe) is False


def test_conditional_rates_keep_zero_denominators_explicit() -> None:
    identities = ["a", "b"]
    values = {"a": ((0, 0), (1, 1)), "b": ((0, 0), (0, 1))}

    result = _conditional_rate_comparison(
        identities, values, iterations=1000, seed=1, direction="HIGHER"
    )

    assert result["baseline"]["rate"] is None
    assert result["candidate"]["rate"] == 0.5
    assert result["absolute_delta"] is None
    assert result["paired_bootstrap_95_interval"] is None
    candidate = Outcome(
        instance_id="instance-0000000000000000",
        mode="controlled-graph",
        protocol_hash="a" * 64,
        input_hash="b" * 64,
        status="SUCCEEDED",
        candidates=("http-500",),
    )
    assert _unsupported_count("http-500", candidate) == 0
    assert _unsupported_count("normal", candidate) == 1


def test_complete_synthetic_score_validates_all_outcomes_before_fake_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "synthetic-dataset"
    dataset.mkdir()
    labels_path = tmp_path / "synthetic-labels.json"
    strata = [name for name in CAUSES for _ in range(20)] + [
        name
        for name in ("normal", "insufficient-evidence", "counter-evidence", "prompt-injection")
        for _ in range(10)
    ]
    index = []
    labels = []
    for number, stratum in enumerate(strata):
        identity = f"instance-{number:016x}"
        input_hash = hashlib.sha256(identity.encode()).hexdigest()
        index.append({"instance_id": identity, "input_hash": input_hash})
        labels.append({"instance_id": identity, "stratum": stratum})
    (dataset / "index.json").write_text(json.dumps(index), encoding="utf-8")
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    rules_plan = json.loads(
        Path("evaluation/real_protocol/rules-v2/plan.json").read_text(encoding="utf-8")
    )
    source_hashes = {name: _sha256(Path(name)) for name in BOUND_SOURCES}
    binary_metrics = (
        "top1",
        "top3",
        "safe_control",
        "valid",
        "integrity",
        "unsupported_free",
        "fabricated_free",
        "gate_recall",
    )
    continuous_metrics = (
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "cost_upper_bound_nanousd",
        "model_calls",
        "tool_calls",
    )
    plan = {
        "schema_version": "final-diagnosis-comparison/1.0.0",
        "protocol_id": "synthetic-final-comparison",
        "implementation_commit": revision,
        "dataset": str(dataset),
        "dataset_index_sha256": _sha256(dataset / "index.json"),
        "evaluator_labels": str(labels_path),
        "evaluator_labels_sha256": _sha256(labels_path),
        "modes": list(MODES),
        "provider": PROVIDER,
        "transport_profile": "real-structured-evaluation/1.11.0",
        "evidence_strategy": "gc-aware-causal-scope/1.0.0",
        "model_provider_call_ceiling": 6,
        "graph_model_call_ceiling": 4,
        "tool_call_ceiling": 12,
        "expected_cases": 160,
        "expected_outcomes": 480,
        "rules_queries": rules_plan["queries"],
        "rules_retry_limit": 0,
        "rules_summary_char_limit_per_query": 1000,
        "primary_comparison": "single-agent-to-controlled-graph",
        "selective_reruns_allowed": False,
        "paired_scorer": {
            "binary_metrics": {
                name: {"direction": "HIGHER", "minimum_relevant_effect": 0.01}
                for name in binary_metrics
            },
            "continuous_metrics": {
                name: {"direction": "LOWER", "minimum_relevant_effect": 1.0}
                for name in continuous_metrics
            },
            "confidence_level": 0.95,
            "multiple_comparison_method": "holm",
            "bootstrap_iterations": 10000,
            "seed": 1,
        },
        "execution_order": EXECUTION_ORDER,
        "failure_policy": FAILURE_POLICY,
        "runtime_label_isolation": True,
        "source_hashes": source_hashes,
        "limitations": ["synthetic unit fixture"],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    protocol_hash = _sha256(plan_path)
    results = tmp_path / "results"
    ledger = OutcomeLedger(results / "outcomes")
    model_runtime_sources = {
        name: source_hashes[name]
        for name in (
            "evaluation/run_snapshot_comparison.py",
            "evaluation/autonomous_diagnosis.py",
            "evaluation/structured_model.py",
            "evaluation/live_evidence.py",
            "evaluation/live_gateway.py",
        )
    }
    for number, (row, stratum) in enumerate(zip(index, strata, strict=True)):
        for mode in MODES:
            fabricated_probe = number == 0 and mode == "controlled-graph"
            outcome = Outcome(
                instance_id=row["instance_id"],
                mode=mode,
                protocol_hash=protocol_hash,
                input_hash=row["input_hash"],
                status="SUCCEEDED",
                candidates=("http-500",) if fabricated_probe else (),
                disposition="HUMAN_HANDOFF",
                missing_evidence_count=int(stratum == "insufficient-evidence"),
                duration_ms=1,
                input_tokens=0 if mode == "rules-only" else None,
                output_tokens=0 if mode == "rules-only" else None,
                cost_upper_bound_nanousd=0 if mode == "rules-only" else None,
            )
            ledger.append(outcome)
            root = results / mode / row["instance_id"]
            root.mkdir(parents=True)
            if mode == "rules-only":
                mode_document = {
                    "mode": mode,
                    "model_calls": 0,
                    "snapshot_reads": 12,
                    "quality_comparison_eligible": True,
                }
                runtime = {
                    "code_revision": revision,
                    "source_hashes": source_hashes,
                    "protocol_hash": protocol_hash,
                    "snapshot_hash": row["input_hash"],
                    "rules_version": "1.0.0",
                    "rules_queries_sha256": hashlib.sha256(
                        json.dumps(
                            rules_plan["queries"], sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest(),
                    "rules_retry_limit": 0,
                    "provider_timing": "NOT_APPLICABLE",
                }
                (root / "result.json").write_text(
                    json.dumps(
                        {
                            "outcome": outcome.model_dump(mode="json"),
                            "rules_result": (
                                {"outcome_reason_code": "EVIDENCE_INSUFFICIENT"}
                                if stratum == "insufficient-evidence"
                                else {}
                            ),
                            "snapshot_reads": [
                                {
                                    "key": query["tool"] + ":" + query["service"],
                                    "status": "SUCCEEDED",
                                }
                                for query in rules_plan["queries"]
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
            else:
                mode_document = {
                    "mode": mode,
                    "historical_reference_count": 0,
                    "memory_status": "NO_HISTORY_SUPPLIED",
                    "quality_comparison_eligible": True,
                }
                runtime = {
                    "code_revision": revision,
                    "source_hashes": model_runtime_sources,
                    "protocol_hash": protocol_hash,
                    "snapshot_hash": row["input_hash"],
                    "structured_transport_profile": plan["transport_profile"],
                    "evidence_strategy": plan["evidence_strategy"],
                    "model_provider_call_ceiling": 6,
                }
                events = [
                    {
                        "purpose": purpose,
                        "status": "SUCCEEDED",
                        "repair_attempt": 0,
                    }
                    for purpose in ("PLAN", "DIAGNOSE")
                ]
                (root / "events.jsonl").write_text(
                    "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
                )
                report: dict[str, object] = {
                    "candidates": (
                        [
                            {
                                "candidate_id": "http-500",
                                "supporting_evidence_ids": ["fabricated-evidence"],
                                "counter_evidence_ids": [],
                                "counter_evidence_explanation": None,
                            }
                        ]
                        if fabricated_probe
                        else []
                    ),
                    "missing_evidence": ["missing"] if stratum == "insufficient-evidence" else [],
                }
                report_hash = fingerprint(report)
                (root / "diagnosis-report.json").write_text(
                    json.dumps(
                        {
                            "report": report,
                            "stored_report_hash": report_hash,
                            "validated_report_hash": report_hash,
                            "redaction_applied": False,
                        }
                    ),
                    encoding="utf-8",
                )
            (root / "mode.json").write_text(json.dumps(mode_document), encoding="utf-8")
            (root / "runtime.json").write_text(json.dumps(runtime), encoding="utf-8")

    class StubResult:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {"metrics": []}

    monkeypatch.setattr(final_score, "score_suite", lambda _request: StubResult())
    monkeypatch.setattr(
        final_score,
        "_conditional_rate_comparison",
        lambda *_args, **_kwargs: {
            "baseline": {
                "numerator": 0,
                "denominator": 0,
                "rate": None,
                "wilson_95_interval": None,
            },
            "candidate": {
                "numerator": 0,
                "denominator": 0,
                "rate": None,
                "wilson_95_interval": None,
            },
            "absolute_delta": None,
            "relative_delta": None,
            "paired_bootstrap_95_interval": None,
            "claim": "TEST",
        },
    )

    document = score(plan_path, results, tmp_path / "analysis")

    assert document["outcome_count"] == 480
    assert document["primary_comparison"] == "single-to-graph"
    assert document["arms"]["controlled-graph"]["safe_controls"] == 40
    assert document["arms"]["controlled-graph"]["fabricated_references"]["numerator"] == 1
    assert "input-tokens" in document["comparisons"]["single-to-graph"]["unavailable_metrics"]
    assert "Primary: single model" in (tmp_path / "analysis" / "README.md").read_text("utf-8")
