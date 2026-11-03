"""Predeclared paired real-model replay; orchestration-only graph comparison."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.memory import InMemorySaver

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.domain import EvidenceSourceType
from agentops_incident_commander.workflows import (
    ContextLoadResult,
    DiagnosisGraphState,
    DiagnosisReport,
    DiagnosisRuntimeContext,
    EvidencePersistenceResult,
    GateNodeResult,
    GateRoute,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
    HypothesisNodeResult,
    InvestigationPlan,
    PlanNodeResult,
    PlanToolCallReference,
    build_diagnosis_graph,
)
from evaluation.baselines.controlled_graph import _Clock, _Progress
from evaluation.baselines.controlled_graph_memory import HistoricalMemoryIndex
from evaluation.deepseek_provider import DeepSeekEvaluationProvider, digest

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = (
    "configuration-drift",
    "database-pool-exhaustion",
    "downstream-latency",
    "deployment-regression",
    "redis-timeout",
    "unknown",
)
PLAN = {
    "version": "real-paired-replay/1.0.0",
    "model": "deepseek-flash",
    "repeats": 3,
    "modes": ["single", "graph", "memory"],
    "taxonomy": TAXONOMY,
    "calls_per_case": 1,
    "max_output_tokens": 2048,
    "max_context_characters": 12288,
    "independent_variable": "single-vs-graph: orchestration; graph-vs-memory: historical context",
    "scope": "summary replay; fixed deterministic collection plan; no model planning comparison",
}


class ReplayServices:
    """Graph ports for immutable fixture reads, never real infrastructure tools."""

    def __init__(
        self,
        provider: DeepSeekEvaluationProvider,
        observations: list[dict[str, str]],
        advisory: str,
    ) -> None:
        self.provider = provider
        self.observations = observations
        self.advisory = advisory
        self.result: dict[str, Any] = {}
        self.report: DiagnosisReport | None = None
        self.reads: list[str] = []

    async def load_context(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> ContextLoadResult:
        return ContextLoadResult()

    async def plan(self, state: DiagnosisGraphState, *, operation_id: str) -> PlanNodeResult:
        plan = InvestigationPlan.model_validate_json(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "plan_id": "fixed-replay-plan",
                    "summary": "Read predeclared immutable observations",
                    "steps": [
                        {
                            "step_id": "read",
                            "objective": "Load the same bounded evidence",
                            "expected_source": EvidenceSourceType.LOG.value,
                            "parallel_group": 0,
                        }
                    ],
                }
            )
        )
        calls = (
            PlanToolCallReference(
                call_id="read-fixture", step_id="read", tool_name="query_logs", tool_version="1.0.0"
            ),
        )
        return PlanNodeResult(
            "deterministic-plan", plan, calls, (digest(self.observations),), 1, 0, 0
        )

    async def load_tool_batches(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> tuple[tuple[str, ...], ...]:
        return (("read-fixture",),)

    async def execute_read_tool(
        self, state: DiagnosisGraphState, tool_call_id: str, *, operation_id: str
    ) -> None:
        if tool_call_id != "read-fixture":
            raise ValueError("unknown fixture read")
        self.reads.append(tool_call_id)

    async def persist_evidence(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> EvidencePersistenceResult:
        return EvidencePersistenceResult(tuple(item["id"] for item in self.observations))

    async def hypothesize(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> HypothesisNodeResult:
        self.result = await asyncio.to_thread(
            self.provider.diagnose,
            state.incident_id,
            self.observations,
            advisory=self.advisory,
            taxonomy=TAXONOMY,
            report_sink=self._accept,
        )
        usage = self.result.get("usage") or {}
        return HypothesisNodeResult("real-hypothesis", usage.get("total_tokens", 0), 0)

    def _accept(self, report: DiagnosisReport) -> None:
        self.report = report

    async def evaluate_evidence_gate(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> GateNodeResult:
        # Fixture observations cannot satisfy the runtime immutable Evidence Store contract.
        return GateNodeResult(
            digest(self.result), GateRoute.HUMAN_HANDOFF, "FIXTURE_EVIDENCE_NOT_RUNTIME_VERIFIED"
        )

    async def record_handoff(self, state: DiagnosisGraphState, *, operation_id: str) -> None:
        return None


class ReplayPromptAuthorization:
    async def require_approved(
        self, state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> None:
        if state.prompt.content_fingerprint != digest(PLAN):
            raise ValueError("replay prompt mismatch")


async def graph_call(
    provider: DeepSeekEvaluationProvider,
    observations: list[dict[str, str]],
    advisory: str,
    incident: str,
) -> dict[str, Any]:
    services = ReplayServices(provider, observations, advisory)
    state = DiagnosisGraphState(
        state_schema_version="1.3.0",
        graph_version="1.0.0",
        tenant_id="evaluation",
        incident_id=incident,
        workflow_run_id=f"run-{incident}",
        correlation_id=f"corr-{incident}",
        causation_id=f"cause-{incident}",
        phase=GraphPhase.CONTEXT_LOADING,
        budgets=GraphBudgetState(
            max_steps=4,
            used_steps=0,
            max_replans=0,
            used_replans=0,
            max_tool_calls=4,
            used_tool_calls=0,
            max_model_calls=2,
            used_model_calls=0,
            max_tokens=8192,
            used_tokens=0,
            max_cost_nanounits=0,
            used_cost_nanounits=0,
        ),
        prompt=GraphPromptReference(
            prompt_id="paired-replay", version="1.0.0", content_fingerprint=digest(PLAN)
        ),
        checkpoint_sequence=0,
        updated_at=datetime.now(UTC),
    )
    saver = InMemorySaver()
    graph = build_diagnosis_graph(checkpointer=saver)
    config: Any = {"configurable": {"thread_id": incident}}
    final = DiagnosisGraphState.model_validate(
        await graph.ainvoke(
            state,
            config=config,
            context=DiagnosisRuntimeContext(
                services, ReplayPromptAuthorization(), _Progress(), _Clock()
            ),
        )
    )
    result = dict(services.result)
    result.update(
        graph_phase=final.phase.value,
        fixture_reads=len(services.reads),
        checkpoints=len([item async for item in saver.alist(config)]),
        cost_budget_enforced=False,
    )
    return result


def run(output: Path, repeats: int = 3) -> dict[str, Any]:
    if repeats != PLAN["repeats"]:
        raise ValueError("only predeclared three-repeat plan is allowed")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required")
    output.mkdir(parents=True, exist_ok=False)
    (output / "plan.json").write_text(json.dumps(PLAN, indent=2), encoding="utf-8")
    dataset = json.loads((ROOT / "evaluation/datasets/v1/dataset.json").read_text(encoding="utf-8"))
    memory = HistoricalMemoryIndex()

    def journal(event: dict[str, Any]) -> None:
        with (output / "calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), **event}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    provider = DeepSeekEvaluationProvider(key, journal)
    results = []
    for repeat in range(repeats):
        for index, case in enumerate(dataset["cases"]):
            observations = [
                {"id": f"observation-{n}", **signal}
                for n, signal in enumerate(case["observation"]["signals"], 1)
            ]
            text = " ".join(item["summary"] for item in observations)
            advisory = "\n".join(item.context for item in memory.retrieve(text))
            # Rotate order to avoid always assigning warm-up or drift to the same mode.
            modes = cast(list[str], PLAN["modes"])
            order = modes[repeat:] + modes[:repeat]
            for mode in order:
                incident = f"incident-{index + 1}"
                started = time.monotonic_ns()
                if mode == "single":
                    result = provider.diagnose(incident, observations, taxonomy=TAXONOMY)
                else:
                    result = asyncio.run(
                        graph_call(
                            provider, observations, advisory if mode == "memory" else "", incident
                        )
                    )
                result.update(
                    case_id=case["case_id"],
                    mode=mode,
                    repeat=repeat + 1,
                    observation_hash=digest(observations),
                    wall_duration_ms=(time.monotonic_ns() - started) // 1_000_000,
                )
                results.append(result)
                with (output / "observations.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(result) + "\n")
                print(
                    f"repeat={repeat + 1} case={index + 1} mode={mode} {result['status']}",
                    flush=True,
                )
    policy = json.loads((ROOT / "evaluation/metrics/v1/policy.json").read_text(encoding="utf-8"))
    mapping = {
        c["case_id"]: policy["accepted_root_causes"][c["scenario_id"]] for c in dataset["cases"]
    }
    for result in results:
        candidates = result.get("candidate_ids", [])
        result["top1_correct"] = bool(candidates and candidates[0] in mapping[result["case_id"]])
        result["top3_correct"] = bool(set(candidates[:3]) & set(mapping[result["case_id"]]))
    document = {
        "schema_version": PLAN["version"],
        "plan_hash": digest(PLAN),
        "dataset_hash": digest(dataset),
        "policy_hash": digest(policy),
        "code_revision": subprocess.check_output(
            ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
        ).strip(),
        "results": results,
        "limitations": [
            "Repeated known six-case replay, not held-out or live diagnosis",
            "Graph uses fixed deterministic plan and fixture reads, not real Tool Gateway",
            "Runtime gate always refuses fixture evidence; no recovery authority",
            "Bills unavailable; graph zero cost is a placeholder, not free usage",
            "Only orchestration and advisory-memory effects measured; not agent planning quality",
        ],
    }
    (output / "results.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    run(parser.parse_args().output_dir)


if __name__ == "__main__":  # pragma: no cover
    main()
