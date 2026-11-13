"""Strict create-only scorer for the frozen eight-pair durability experiment."""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.contracts import EvaluationContractError, canonical_json, load_json_object

PLAN_SCHEMA = "final-durability-plan/1.0.0"
OBSERVATION_SCHEMA = "final-durability-observations/1.0.0"
RESULT_SCHEMA = "final-durability-result/1.0.0"
ARMS = ("control", "treatment")


@dataclass(frozen=True, slots=True)
class DurabilityPlan:
    fingerprint: str
    cases: tuple[tuple[str, str], ...]
    acceptance: Mapping[str, int | float]


@dataclass(frozen=True, slots=True)
class ArmObservation:
    case_id: str
    arm: str
    completed: int
    duplicate_external_effects: int
    ambiguous_result_redispatches: int
    evidence_expected: int
    evidence_persisted: int
    takeover_or_resume_latency_ms: int
    total_latency_ms: int
    model_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    rate_card_upper_bound_nusd: int
    terminal_route: str

    @property
    def lost_evidence_records(self) -> int:
        return self.evidence_expected - self.evidence_persisted


def load_plan(path: Path) -> DurabilityPlan:
    value = load_json_object(path)
    if value.get("schema_version") != PLAN_SCHEMA or value.get("status") != (
        "FROZEN_BEFORE_MEASUREMENT"
    ):
        raise EvaluationContractError("durability plan is not frozen under the supported schema")
    treatments = value.get("treatments")
    if not isinstance(treatments, list) or len(treatments) != 8:
        raise EvaluationContractError("durability plan requires exactly eight treatments")
    cases: list[tuple[str, str]] = []
    for item in treatments:
        if not isinstance(item, dict):
            raise EvaluationContractError("durability treatment is malformed")
        case_id, route = item.get("case_id"), item.get("expected_route")
        if not isinstance(case_id, str) or not isinstance(route, str):
            raise EvaluationContractError("durability treatment identity is invalid")
        cases.append((case_id, route))
    if len({case_id for case_id, _ in cases}) != 8 or value.get("pair_count") != 8:
        raise EvaluationContractError("durability case identities are not a fixed census")
    acceptance = value.get("acceptance")
    if not isinstance(acceptance, dict):
        raise EvaluationContractError("durability acceptance contract is missing")
    return DurabilityPlan(
        hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest(),
        tuple(cases),
        acceptance,
    )


def _integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise EvaluationContractError(f"durability observation {name} is invalid")
    return value


def _parse_observation(value: object) -> ArmObservation:
    fields = {item.name for item in ArmObservation.__dataclass_fields__.values()}
    if not isinstance(value, dict) or set(value) != fields:
        raise EvaluationContractError("durability observation fields do not match the contract")
    case_id, arm, route = value["case_id"], value["arm"], value["terminal_route"]
    if not all(isinstance(item, str) and item for item in (case_id, arm, route)):
        raise EvaluationContractError("durability observation identity is invalid")
    numeric = {
        name: _integer(value[name], name)
        for name in fields - {"case_id", "arm", "terminal_route"}
    }
    if numeric["completed"] not in (0, 1):
        raise EvaluationContractError("durability completed value must be binary")
    if numeric["evidence_persisted"] > numeric["evidence_expected"]:
        raise EvaluationContractError("durability persisted Evidence exceeds the expected set")
    return ArmObservation(case_id, arm, terminal_route=route, **numeric)


def load_observations(path: Path, plan: DurabilityPlan) -> tuple[ArmObservation, ...]:
    value = load_json_object(path)
    if set(value) != {"observations", "plan_sha256", "schema_version"}:
        raise EvaluationContractError("durability observation document fields changed")
    if value["schema_version"] != OBSERVATION_SCHEMA or value["plan_sha256"] != plan.fingerprint:
        raise EvaluationContractError("durability observations do not bind the frozen plan")
    rows = value["observations"]
    if not isinstance(rows, list) or len(rows) != 16:
        raise EvaluationContractError("durability observations require sixteen fixed arms")
    observations = tuple(_parse_observation(row) for row in rows)
    expected = {(case_id, arm) for case_id, _ in plan.cases for arm in ARMS}
    actual = {(row.case_id, row.arm) for row in observations}
    if actual != expected or len(actual) != len(observations):
        raise EvaluationContractError(
            "durability observations are missing, duplicated or reordered"
        )
    return observations


def _relative_delta(control: int, treatment: int) -> float | None:
    return None if control == 0 else (treatment - control) / control


def _bootstrap_median_interval(values: Sequence[int], seed: int) -> list[float]:
    if not values:
        raise EvaluationContractError("durability interval requires paired values")
    generator = random.Random(seed)
    samples = sorted(
        statistics.median(generator.choices(values, k=len(values))) for _ in range(10_000)
    )
    return [samples[249], samples[9749]]


def score(plan: DurabilityPlan, observations: Sequence[ArmObservation]) -> dict[str, Any]:
    indexed = {(row.case_id, row.arm): row for row in observations}
    pairs: list[dict[str, Any]] = []
    latency_deltas: list[int] = []
    resume_deltas: list[int] = []
    for case_id, expected_route in plan.cases:
        control, treatment = indexed[(case_id, "control")], indexed[(case_id, "treatment")]
        metrics = (
            "completed",
            "duplicate_external_effects",
            "ambiguous_result_redispatches",
            "lost_evidence_records",
            "takeover_or_resume_latency_ms",
            "total_latency_ms",
            "model_calls",
            "tool_calls",
            "input_tokens",
            "output_tokens",
            "rate_card_upper_bound_nusd",
        )
        deltas: dict[str, dict[str, int | float | None]] = {}
        for name in metrics:
            before, after = getattr(control, name), getattr(treatment, name)
            deltas[name] = {
                "control": before,
                "treatment": after,
                "absolute_delta": after - before,
                "relative_delta": _relative_delta(before, after),
            }
        latency_deltas.append(treatment.total_latency_ms - control.total_latency_ms)
        resume_deltas.append(
            treatment.takeover_or_resume_latency_ms - control.takeover_or_resume_latency_ms
        )
        pairs.append(
            {
                "case_id": case_id,
                "expected_treatment_route": expected_route,
                "control_route": control.terminal_route,
                "treatment_route": treatment.terminal_route,
                "route_matches": treatment.terminal_route == expected_route,
                "metrics": deltas,
            }
        )
    duplicate_effects = sum(
        indexed[(case_id, "treatment")].duplicate_external_effects
        for case_id, _ in plan.cases
    )
    ambiguous_redispatches = sum(
        indexed[(case_id, "treatment")].ambiguous_result_redispatches
        for case_id, _ in plan.cases
    )
    lost_evidence = sum(
        indexed[(case_id, "treatment")].lost_evidence_records
        for case_id, route in plan.cases
        if route == "RESUMED_COMPLETION"
    )
    route_matches = sum(item["route_matches"] for item in pairs)
    accepted = (
        len(pairs) == plan.acceptance["completed_pairs"]
        and duplicate_effects <= plan.acceptance["maximum_duplicate_external_effects"]
        and ambiguous_redispatches
        <= plan.acceptance["maximum_ambiguous_result_redispatches"]
        and lost_evidence <= plan.acceptance["maximum_lost_evidence_records_on_resumable_routes"]
        and route_matches / len(pairs) >= plan.acceptance["required_terminal_route_match_rate"]
    )
    seed = int(plan.fingerprint[:16], 16)
    return {
        "schema_version": RESULT_SCHEMA,
        "plan_sha256": plan.fingerprint,
        "pairs": pairs,
        "summary": {
            "accepted": accepted,
            "completed_pairs": len(pairs),
            "duplicate_external_effects": duplicate_effects,
            "ambiguous_result_redispatches": ambiguous_redispatches,
            "lost_evidence_records_on_resumable_routes": lost_evidence,
            "terminal_route_matches": route_matches,
            "total_latency_delta_median_ms": statistics.median(latency_deltas),
            "total_latency_delta_median_95pct_bootstrap_ms": _bootstrap_median_interval(
                latency_deltas, seed
            ),
            "resume_latency_delta_median_ms": statistics.median(resume_deltas),
            "resume_latency_delta_median_95pct_bootstrap_ms": _bootstrap_median_interval(
                resume_deltas, seed ^ 0xA5A5A5A5
            ),
        },
    }


def render_markdown(result: Mapping[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Final durability paired comparison",
        "",
        "| Case | Control route | Treatment route | Total latency control→treatment "
        "(delta ms) | Duplicate effects | Ambiguous redispatches | Lost Evidence |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for pair in result["pairs"]:
        metrics = pair["metrics"]
        latency = metrics["total_latency_ms"]
        lines.append(
            f"| `{pair['case_id']}` | `{pair['control_route']}` | `{pair['treatment_route']}` | "
            f"{latency['control']}→{latency['treatment']} ({latency['absolute_delta']:+}) | "
            f"{metrics['duplicate_external_effects']['treatment']} | "
            f"{metrics['ambiguous_result_redispatches']['treatment']} | "
            f"{metrics['lost_evidence_records']['treatment']} |"
        )
    lines.extend(
        (
            "",
            f"Acceptance: `{'PASS' if summary['accepted'] else 'FAIL'}`; "
            f"route matches {summary['terminal_route_matches']}/{summary['completed_pairs']}, "
            f"duplicate effects {summary['duplicate_external_effects']}, ambiguous redispatches "
            f"{summary['ambiguous_result_redispatches']}.",
            "",
            "Latency is local monotonic elapsed time. Token and rate-card fields are descriptive; "
            "the latter is not actual provider billing. Controlled substitutes do not establish "
            "real-provider quality, human labor savings, MTTR, or production reliability.",
            "",
        )
    )
    return "\n".join(lines)


def create_result(*, plan_path: Path, observations_path: Path, output_dir: Path) -> None:
    if output_dir.exists():
        raise EvaluationContractError("durability output directory already exists")
    plan = load_plan(plan_path)
    result = score(plan, load_observations(observations_path, plan))
    if not math.isfinite(float(result["summary"]["total_latency_delta_median_ms"])):
        raise EvaluationContractError("durability latency summary is not finite")
    output_dir.mkdir(parents=True)
    raw = f"{canonical_json(result)}\n"
    (output_dir / "result.json").write_text(raw, encoding="utf-8", newline="\n")
    (output_dir / "README.md").write_text(
        render_markdown(result), encoding="utf-8", newline="\n"
    )
    manifest = {
        "README.md": hashlib.sha256((output_dir / "README.md").read_bytes()).hexdigest(),
        "result.json": hashlib.sha256((output_dir / "result.json").read_bytes()).hexdigest(),
    }
    (output_dir / "manifest.json").write_text(
        f"{canonical_json(manifest)}\n", encoding="utf-8", newline="\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        create_result(
            plan_path=arguments.plan,
            observations_path=arguments.observations,
            output_dir=arguments.output_dir,
        )
    except EvaluationContractError as error:
        print(f"[evaluation] durability scoring failed reason={error}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
