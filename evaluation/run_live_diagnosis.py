"""Collect live Compose telemetry during bounded faults; stop before human approval."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from agentops_incident_commander.faults import SCENARIO_TARGETS, clean, inject
from evaluation.deepseek_provider import DeepSeekEvaluationProvider, digest
from evaluation.live_evidence import ExperimentEvidence
from evaluation.run_real_comparison import TAXONOMY

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = {
    "SIMULATOR_DB_ADMIN_PASSWORD_FILE": "./secrets/simulator-db-admin-password.txt",
    "GATEWAY_PORT": "18080",
    "PROMETHEUS_PORT": "19090",
    "LOKI_PORT": "13100",
    "TEMPO_PORT": "13200",
    "GRAFANA_PORT": "13000",
}


def checkout(client: httpx.Client, *, sku: str = "widget") -> dict[str, Any]:
    started = time.monotonic_ns()
    response = client.post(
        "http://127.0.0.1:18080/v1/checkout",
        json={
            "order_id": f"evaluation-{uuid4().hex[:16]}",
            "items": [{"sku": sku, "quantity": 1}],
            "amount_minor": 500,
            "currency": "USD",
        },
    )
    return {
        "status": response.status_code,
        "duration_ms": (time.monotonic_ns() - started) // 1_000_000,
    }


def ready(client: httpx.Client) -> None:
    for _ in range(30):
        try:
            if client.get("http://127.0.0.1:18080/healthz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("gateway did not become live")


def wait_target(target: str, environment: dict[str, str]) -> None:
    if target not in set(SCENARIO_TARGETS.values()):
        raise ValueError("unknown simulator target")
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        target,
        "python",
        "-c",
        "import urllib.request; "
        "urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()",
    ]
    for _ in range(20):
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("target liveness timeout")


def telemetry(client: httpx.Client, start: float, target: str) -> list[dict[str, str]]:
    selector = f'{{service_name="agentops-simulator-{target}"}}'
    sources = [
        (
            "metrics",
            "http://127.0.0.1:19090/api/v1/query",
            {
                "query": "sum by (service_name,service_version,route,status) "
                "(simulator_http_server_requests_total)"
            },
        ),
        (
            "logs",
            "http://127.0.0.1:13100/loki/api/v1/query_range",
            {"query": selector, "start": str(int(start * 1e9)), "limit": "20"},
        ),
        (
            "traces",
            "http://127.0.0.1:13200/api/search",
            {
                "tags": f'service.name="agentops-simulator-{target}"',
                "start": str(int(start)),
                "end": str(int(time.time())),
                "limit": "10",
            },
        ),
    ]
    observations = []
    for index, (source, endpoint, params) in enumerate(sources, 1):
        response = client.get(endpoint, params=params)
        response.raise_for_status()
        body = response.json()
        if source == "metrics":
            payload: Any = [
                {
                    "labels": {
                        k: v
                        for k, v in item["metric"].items()
                        if k in {"service_name", "service_version", "route", "status"}
                    },
                    "value": item["value"][1],
                }
                for item in body["data"]["result"]
            ]
        elif source == "logs":
            payload = [
                {
                    "service": item["stream"].get("service_name"),
                    "events": [value[1][:256] for value in item["values"]],
                }
                for item in body["data"]["result"]
            ]
        else:
            payload = [
                {
                    "rootServiceName": item.get("rootServiceName"),
                    "durationMs": item.get("durationMs"),
                    "rootTraceName": item.get("rootTraceName"),
                }
                for item in body.get("traces", [])
            ]
        # Telemetry producers emit bounded, content-free logs; never export model reasoning.
        observations.append(
            {
                "id": f"live-{index}",
                "source": source,
                "summary": json.dumps(payload, sort_keys=True)[:2048],
            }
        )
    return observations


def run(output: Path) -> None:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required")
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    output.mkdir(parents=True, exist_ok=False)
    environment = {**os.environ, **ENVIRONMENT}

    # The evaluator process uses the explicit environment for fault application/cleanup.
    def journal(event: dict[str, Any]) -> None:
        with (output / "calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), **event}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    provider = DeepSeekEvaluationProvider(key, journal)
    results = []
    with httpx.Client(timeout=15, trust_env=False) as client:
        ready(client)
        for index, (scenario, target) in enumerate(SCENARIO_TARGETS.items(), 1):
            started_at = datetime.now(UTC).isoformat()
            baseline = checkout(client)
            if baseline["status"] != 200:
                raise RuntimeError("baseline checkout failed; no valid fault measurement")
            record: dict[str, Any] = {
                "scenario": scenario,
                "started_at": started_at,
                "baseline": baseline,
                "recovery_credit": False,
            }
            try:
                if inject(scenario, root=ROOT, environment=environment) != 0:
                    raise RuntimeError("fault injection failed")
                wait_target(target, environment)
                ready(client)
                start = time.time()
                probes = [checkout(client) for _ in range(8)]
                time.sleep(12)
                observations = telemetry(client, start, target)
                observations.append(
                    {"id": "live-http", "source": "http-probes", "summary": json.dumps(probes)}
                )
                incident = f"live-incident-{index}"
                evidence = ExperimentEvidence(
                    ROOT / "artifacts" / "live-evidence" / output.name / incident,
                    incident,
                    observations,
                    observed_from=datetime.fromtimestamp(start, UTC),
                )
                reports: list[Any] = []
                # No fault name, target mapping or evaluator result is supplied to the model.
                record.update(
                    probes=probes,
                    evidence_hash=digest(observations),
                    collected_at=datetime.now(UTC).isoformat(),
                    source_nonempty={o["source"]: o["summary"] != "[]" for o in observations},
                    diagnosis=provider.diagnose(
                        incident,
                        evidence.observations,
                        taxonomy=TAXONOMY,
                        report_sink=reports.append,
                    ),
                    terminal="HUMAN_REVIEW_REQUIRED",
                )
                record["evidence_store"] = (
                    evidence.gate(reports[0])
                    if reports
                    else {"stored_evidence_count": len(evidence.records), "gate": "NO_VALID_REPORT"}
                )
            finally:
                record["cleanup_exit"] = clean(root=ROOT, environment=environment)
                wait_target(target, environment)
                ready(client)
                record["after_cleanup"] = checkout(client)
                with (output / "cases.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record) + "\n")
            results.append(record)
            print(f"live case={index} completed; awaiting human review", flush=True)
    policy = json.loads((ROOT / "evaluation/metrics/v1/policy.json").read_text(encoding="utf-8"))
    for record in results:
        candidates = record["diagnosis"].get("candidate_ids", [])
        expected = policy["accepted_root_causes"][record["scenario"]]
        record["top1_correct"] = bool(candidates and candidates[0] in expected)
        record["top3_correct"] = bool(set(candidates[:3]) & set(expected))
    document = {
        "schema_version": "live-compose-diagnosis/1.0.0",
        "code_revision": revision,
        "environment": ENVIRONMENT,
        "results": results,
        "limitations": [
            "Evaluator-controlled HTTP telemetry collection, not autonomous Tool Gateway",
            "No approvals or product recovery executed; cleanup earns no recovery credit",
            "Telemetry summaries truncated at 2048 characters; independent runtime Gate not run",
            "Metrics query is cumulative; not an isolated rate or production P95 measurement",
        ],
    }
    (output / "results.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    run(parser.parse_args().output_dir)


if __name__ == "__main__":  # pragma: no cover
    main()
