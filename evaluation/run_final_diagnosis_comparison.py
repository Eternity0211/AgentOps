"""Run the frozen, label-isolated FC4 rules/single/graph confirmation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from evaluation.autonomous_diagnosis import EvidenceStrategy
from evaluation.baselines.rules import RulesDiagnosisSystem
from evaluation.contracts import EvaluationCase, EvaluationObservation, ObservationSignal
from evaluation.fairness import AggregateBudget, BaselineProfile, CandidateExecutionConfig
from evaluation.observation_snapshot import load_snapshot
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import RULES_MODE, Outcome
from evaluation.run_real_batch import preflight
from evaluation.run_snapshot_comparison import run_snapshot
from evaluation.structured_model import StructuredTransportProfile

ROOT = Path(__file__).resolve().parents[1]
MODES = (RULES_MODE, "single-agent", "controlled-graph")
BOUND_SOURCES = {
    "evaluation/autonomous_diagnosis.py",
    "evaluation/baselines/rules.py",
    "evaluation/live_evidence.py",
    "evaluation/live_gateway.py",
    "evaluation/observation_snapshot.py",
    "evaluation/outcome_ledger.py",
    "evaluation/paired_comparison.py",
    "evaluation/real_scoring.py",
    "evaluation/run_final_diagnosis_comparison.py",
    "evaluation/run_real_batch.py",
    "evaluation/run_snapshot_comparison.py",
    "evaluation/score_final_diagnosis_comparison.py",
    "evaluation/score_transport_pair.py",
    "evaluation/structured_model.py",
}
MODEL_RUNTIME_SOURCES = {
    "evaluation/run_snapshot_comparison.py",
    "evaluation/autonomous_diagnosis.py",
    "evaluation/structured_model.py",
    "evaluation/live_evidence.py",
    "evaluation/live_gateway.py",
}
RULES_QUERIES = tuple(
    {"tool": tool, "service": service}
    for service in ("gateway", "order", "inventory", "payment")
    for tool in ("query_metrics", "query_logs", "query_deployments")
)
PROVIDER = {
    "name": "deepseek",
    "model": "deepseek-flash",
    "temperature": 0,
    "thinking": "disabled",
    "max_output_tokens": 2048,
}
EXECUTION_ORDER = "ROTATE_LEFT_BY_DATASET_INDEX_MODULO_THREE"
FAILURE_POLICY = {
    "retain_all_outcomes": True,
    "selective_reruns": False,
    "partial_directories": "RETAIN_AS_FAILED",
    "complete_rules_result": "RECOVER_WITHOUT_RERUN",
}
LEGACY_IMPLEMENTATION_COMMIT = "c700481973d3f1ca3239aaa3e1cdf5dc5fd2e6f6"
LEGACY_BOUND_SOURCES = BOUND_SOURCES - {"evaluation/run_real_batch.py"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_plan(plan: dict[str, Any], revision: str, dataset: Path) -> None:
    if plan.get("schema_version") != "final-diagnosis-comparison/1.0.0":
        raise ValueError("unknown final diagnosis comparison plan")
    binding = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=D:/AgentOps",
            "merge-base",
            "--is-ancestor",
            plan["implementation_commit"],
            revision,
        ],
        check=False,
    )
    if binding.returncode != 0:
        raise ValueError("frozen implementation commit is not an ancestor")
    if _sha256(dataset / "index.json") != plan["dataset_index_sha256"]:
        raise ValueError("dataset index hash mismatch")
    if (ROOT / plan.get("dataset", "")).resolve() != dataset.resolve():
        raise ValueError("dataset path mismatch")
    if tuple(plan.get("modes", ())) != MODES:
        raise ValueError("final comparison arm mismatch")
    if (
        plan.get("model_provider_call_ceiling") != 6
        or plan.get("graph_model_call_ceiling") != 4
        or plan.get("tool_call_ceiling") != 12
        or plan.get("expected_cases") != 160
        or plan.get("expected_outcomes") != 480
        or not isinstance(plan.get("evaluator_labels"), str)
        or not isinstance(plan.get("evaluator_labels_sha256"), str)
        or len(plan["evaluator_labels_sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in plan["evaluator_labels_sha256"])
    ):
        raise ValueError("final comparison budget mismatch")
    if (
        tuple(plan.get("rules_queries", ())) != RULES_QUERIES
        or plan.get("rules_retry_limit") != 0
        or plan.get("rules_summary_char_limit_per_query") != 1000
        or plan.get("provider") != PROVIDER
        or plan.get("transport_profile") != StructuredTransportProfile.CANDIDATE_1_11.value
        or plan.get("evidence_strategy") != EvidenceStrategy.GC_AWARE_CAUSAL_SCOPE.value
    ):
        raise ValueError("final comparison configuration mismatch")
    scorer = plan.get("paired_scorer", {})
    binary_metrics = scorer.get("binary_metrics", {})
    continuous_metrics = scorer.get("continuous_metrics", {})
    if (
        not isinstance(binary_metrics, dict)
        or not isinstance(continuous_metrics, dict)
        or set(binary_metrics)
        != {
            "top1",
            "top3",
            "safe_control",
            "valid",
            "integrity",
            "unsupported_free",
            "fabricated_free",
            "gate_recall",
        }
        or set(continuous_metrics)
        != {
            "duration_ms",
            "input_tokens",
            "output_tokens",
            "cost_upper_bound_nanousd",
            "model_calls",
            "tool_calls",
        }
        or scorer.get("confidence_level") != 0.95
        or scorer.get("multiple_comparison_method") != "holm"
        or scorer.get("bootstrap_iterations") != 10000
        or type(scorer.get("seed")) is not int
        or not 0 <= scorer["seed"] <= 2**32 - 1
        or any(
            config.get("direction") != "HIGHER"
            or type(config.get("minimum_relevant_effect")) not in (int, float)
            or config["minimum_relevant_effect"] <= 0
            for config in binary_metrics.values()
        )
        or any(
            config.get("direction") != "LOWER"
            or type(config.get("minimum_relevant_effect")) not in (int, float)
            or config["minimum_relevant_effect"] <= 0
            for config in continuous_metrics.values()
        )
        or plan.get("primary_comparison") != "single-agent-to-controlled-graph"
        or plan.get("selective_reruns_allowed") is not False
        or plan.get("execution_order") != EXECUTION_ORDER
        or plan.get("failure_policy") != FAILURE_POLICY
        or plan.get("runtime_label_isolation") is not True
    ):
        raise ValueError("final comparison scorer mismatch")
    source_hashes = plan.get("source_hashes", {})
    expected_sources = (
        LEGACY_BOUND_SOURCES
        if plan.get("implementation_commit") == LEGACY_IMPLEMENTATION_COMMIT
        else BOUND_SOURCES
    )
    if set(source_hashes) != expected_sources or any(
        _sha256(ROOT / name) != digest for name, digest in source_hashes.items()
    ):
        raise ValueError("final comparison source hash mismatch")


def _rules_configuration() -> CandidateExecutionConfig:
    return CandidateExecutionConfig(
        BaselineProfile(
            "rules-only",
            "1.0.0",
            "rules",
            "deterministic",
            False,
            None,
            None,
            "none",
            AggregateBudget(64000, 0, 12, 0, 60000, 0),
        ),
        (),
    )


def _retain_partial_failure(
    run_root: Path,
    *,
    mode: str,
    instance_id: str,
    protocol_hash: str,
    input_hash: str,
    revision: str,
    source_hashes: dict[str, str],
) -> None:
    marker = {
        "reason": "PREEXISTING_PARTIAL_DIRECTORY",
        "mode": mode,
        "instance_id": instance_id,
        "protocol_hash": protocol_hash,
        "input_hash": input_hash,
        "code_revision": revision,
        "source_hashes": source_hashes,
    }
    path = run_root / "retained-failure.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != marker:
            raise ValueError("partial failure marker mismatch")
        return
    with path.open("x", encoding="utf-8") as stream:
        json.dump(marker, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def _recover_rules_outcome(
    run_root: Path,
    *,
    instance_id: str,
    protocol_hash: str,
    input_hash: str,
) -> Outcome | None:
    path = run_root / "result.json"
    if not path.exists():
        return None
    try:
        outcome = Outcome.model_validate_json(
            json.dumps(json.loads(path.read_text(encoding="utf-8"))["outcome"])
        )
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return None
    if (
        outcome.instance_id != instance_id
        or outcome.mode != RULES_MODE
        or outcome.protocol_hash != protocol_hash
        or outcome.input_hash != input_hash
    ):
        return None
    return outcome


def run_rules_case(
    snapshot_path: Path,
    expected_hash: str,
    output: Path,
    protocol_hash: str,
    queries: list[dict[str, str]],
    summary_limit: int,
    *,
    code_revision: str | None = None,
    source_hashes: dict[str, str] | None = None,
) -> Outcome:
    snapshot = load_snapshot(snapshot_path, expected_hash=expected_hash)
    identity = snapshot["instance_id"]
    run_root = output / RULES_MODE / identity
    run_root.mkdir(parents=True, exist_ok=False)
    revision = (
        code_revision
        or subprocess.check_output(
            ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
        ).strip()
    )
    hashes = source_hashes or {name: _sha256(ROOT / name) for name in BOUND_SOURCES}
    (run_root / "mode.json").write_text(
        json.dumps(
            {
                "mode": RULES_MODE,
                "model_calls": 0,
                "snapshot_reads": len(queries),
                "quality_comparison_eligible": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (run_root / "runtime.json").write_text(
        json.dumps(
            {
                "code_revision": revision,
                "source_hashes": hashes,
                "protocol_hash": protocol_hash,
                "snapshot_hash": expected_hash,
                "rules_version": "1.0.0",
                "rules_queries_sha256": hashlib.sha256(
                    json.dumps(queries, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "rules_retry_limit": 0,
                "provider_timing": "NOT_APPLICABLE",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    started = time.monotonic_ns()
    signals: list[ObservationSignal] = []
    reads: list[dict[str, str]] = []
    for query in queries:
        key = query["tool"] + ":" + query["service"]
        record = snapshot["reads"][key]
        reads.append({"key": key, "status": record["status"]})
        if record["status"] == "SUCCEEDED":
            data = record["output"]
            signals.append(ObservationSignal(data["source"], data["summary"][:summary_limit]))
    failed = any(item["status"] != "SUCCEEDED" for item in reads)
    result: dict[str, Any] = {}
    if not failed:
        case = EvaluationCase(
            identity,
            "opaque-snapshot",
            "evaluation",
            EvaluationObservation(snapshot["alert"], 1, tuple(signals), ()),
        )
        result = dict(RulesDiagnosisSystem().evaluate(case, _rules_configuration()))
    outcome = Outcome(
        instance_id=identity,
        mode=RULES_MODE,
        protocol_hash=protocol_hash,
        input_hash=expected_hash,
        status="FAILED" if failed else "SUCCEEDED",
        disposition=None if failed else "HUMAN_HANDOFF",
        candidates=tuple(result.get("diagnosis_top3", [])),
        missing_evidence_count=int(result.get("outcome_reason_code") == "EVIDENCE_INSUFFICIENT"),
        duration_ms=(time.monotonic_ns() - started) // 1_000_000,
        input_tokens=0,
        output_tokens=0,
        cost_upper_bound_nanousd=0,
    )
    (run_root / "result.json").write_text(
        json.dumps(
            {
                "outcome": outcome.model_dump(mode="json"),
                "rules_result": result,
                "snapshot_reads": reads,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    OutcomeLedger(output / "outcomes").append(outcome)
    return outcome


def run(
    dataset: Path,
    plan_path: Path,
    output: Path,
    *,
    key: str,
    transport: Any = None,
) -> None:
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required before confirmation start")
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    check_plan(plan, revision, dataset)
    rows = preflight(dataset, expected_cases=plan["expected_cases"])
    if len(rows) != plan["expected_cases"]:
        raise ValueError("final comparison case count mismatch")
    digest = hashlib.sha256(plan_bytes).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    ledger = OutcomeLedger(output / "outcomes")
    existing = {
        (item.instance_id, item.mode): item for item in ledger.collect(protocol_hash=digest)
    }
    for row_index, row in enumerate(rows):
        snapshot_path = dataset / "inputs" / f"{row['instance_id']}.json"
        load_snapshot(snapshot_path, expected_hash=row["input_hash"])
        ordered_modes = MODES[row_index % len(MODES) :] + MODES[: row_index % len(MODES)]
        for mode in ordered_modes:
            key_tuple = (row["instance_id"], mode)
            previous = existing.get(key_tuple)
            if previous is not None:
                if previous.input_hash != row["input_hash"]:
                    raise ValueError("resume input hash mismatch")
                continue
            run_root = output / mode / row["instance_id"]
            if run_root.exists():
                recovered = (
                    _recover_rules_outcome(
                        run_root,
                        instance_id=row["instance_id"],
                        protocol_hash=digest,
                        input_hash=row["input_hash"],
                    )
                    if mode == RULES_MODE
                    else None
                )
                if recovered is not None:
                    ledger.append(recovered)
                    existing[key_tuple] = recovered
                    continue
                _retain_partial_failure(
                    run_root,
                    mode=mode,
                    instance_id=row["instance_id"],
                    protocol_hash=digest,
                    input_hash=row["input_hash"],
                    revision=revision,
                    source_hashes=plan["source_hashes"],
                )
                failure = Outcome(
                    instance_id=row["instance_id"],
                    mode=mode,
                    protocol_hash=digest,
                    input_hash=row["input_hash"],
                    status="FAILED",
                )
                ledger.append(failure)
                existing[key_tuple] = failure
                continue
            if mode == RULES_MODE:
                outcome = run_rules_case(
                    snapshot_path,
                    row["input_hash"],
                    output,
                    digest,
                    plan["rules_queries"],
                    plan["rules_summary_char_limit_per_query"],
                    code_revision=revision,
                    source_hashes=plan["source_hashes"],
                )
            else:
                outcome = run_snapshot(
                    snapshot_path,
                    row["input_hash"],
                    mode,
                    output,
                    digest,
                    key=key,
                    transport=transport,
                    profile=StructuredTransportProfile.CANDIDATE_1_11,
                    evidence_strategy=EvidenceStrategy.GC_AWARE_CAUSAL_SCOPE,
                    model_max_calls=plan["model_provider_call_ceiling"],
                )
            existing[key_tuple] = outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(
        args.dataset,
        args.plan,
        args.output,
        key=os.environ.get("DEEPSEEK_API_KEY", ""),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
