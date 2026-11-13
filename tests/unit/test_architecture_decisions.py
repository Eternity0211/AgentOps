from __future__ import annotations

import math
from pathlib import Path

from evaluation.contracts import load_json_object

DECISIONS = Path("evaluation/results/architecture-decisions/v1/decisions.json")
LOAD = Path("evaluation/results/final-load/v1/confirmatory-001/confirmatory.json")


def test_architecture_decisions_cover_every_optional_item_without_speculative_adoption() -> None:
    value = load_json_object(DECISIONS)
    decisions = {item["option"]: item for item in value["decisions"]}

    assert set(decisions) == {
        "read-only-mcp",
        "additional-write-and-compensation",
        "external-audit-anchoring",
        "artifact-store-and-enterprise-identity",
        "a2a",
        "control-plane-broker",
    }
    assert all(item["disposition"].startswith("NOT_REQUIRED") for item in decisions.values())
    assert decisions["control-plane-broker"]["operational_complexity"].startswith(
        "Kafka/NATS deferred"
    )


def test_broker_decision_uses_exact_confirmatory_baseline_candidate_and_deltas() -> None:
    value = load_json_object(DECISIONS)
    load = load_json_object(LOAD)
    broker = next(item for item in value["decisions"] if item["option"] == "control-plane-broker")
    groups = {item["workers"]: item for item in load["groups"]}
    throughput = broker["measurements"]["throughput_jobs_per_second"]
    queue = broker["measurements"]["queue_wait_p95_ms"]

    assert throughput["baseline"] == groups[4]["throughput_jobs_per_second_median"]
    assert throughput["candidate"] == groups[8]["throughput_jobs_per_second_median"]
    assert math.isclose(
        throughput["absolute_delta"], throughput["candidate"] - throughput["baseline"]
    )
    assert math.isclose(
        throughput["relative_delta"], throughput["candidate"] / throughput["baseline"] - 1
    )
    assert queue["baseline"] == groups[4]["queue_wait_p95_ms_median"]
    assert queue["candidate"] == groups[8]["queue_wait_p95_ms_median"]
    assert queue["absolute_delta"] == queue["candidate"] - queue["baseline"]
    assert math.isclose(queue["relative_delta"], queue["candidate"] / queue["baseline"] - 1)
    assert load["broker_decision"] == "BROKER_EVALUATION_REQUIRED"
