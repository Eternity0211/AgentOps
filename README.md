# AgentOps Incident Commander

AgentOps Incident Commander is an evidence-driven platform for diagnosing microservice incidents and performing controlled recovery. It combines metrics, logs, traces, topology, and deployment history; a constrained Diagnosis Agent builds verifiable root-cause hypotheses; a constrained Remediation Agent proposes recovery only after a deterministic evidence gate passes. Deterministic policy, approval, execution, health verification, and failure routing retain authority over every state change.

> Status: planning baseline. No business implementation exists yet. The first implementation milestone will build the reproducible microservice simulator, observability signals, and evaluation-only Ground Truth.

## Why this project exists

- Shorten time to diagnose microservice failures.
- Improve the completeness and traceability of root-cause evidence.
- Reduce recovery risk with typed plans, policy enforcement, human approval, idempotency, health verification, and explicit safe failure routing.
- Make the agent system itself observable and auditable.

## Safety boundary

```text
Alert -> deterministic triage -> Diagnosis Agent -> read-only tools -> Evidence Store
      -> deterministic Evidence Gate -> Remediation Agent -> schema validation
      -> Policy Engine -> human approval -> deterministic Executor
      -> deterministic Health Verifier -> close, re-diagnose, or human handoff
```

An LLM can propose; it cannot execute arbitrary commands, mutate infrastructure directly, approve its own proposal, declare success, or invent evidence. Ground Truth is available only to the evaluation harness.

## Planned stack

Python 3.12, FastAPI, LangGraph, Pydantic, SQLAlchemy, Alembic, PostgreSQL/pgvector, OpenTelemetry, Prometheus, Loki, Tempo, Docker Compose, Pytest, Testcontainers, and a small Next.js/React console.

## Python 3.12 bootstrap

The project is pinned to Python 3.12.14 in `.python-version`; Python 3.14 is not an accepted substitute. `uv` is the bootstrap tool. A normal developer/CI setup is:

```text
uv python install 3.12.14
uv venv --python 3.12.14 .venv
```

Activate `.venv` using the shell's normal command, then verify the invariant with:

```text
python -c "import sys; assert sys.version_info[:2] == (3, 12), sys.version; print(sys.version)"
```

On this Windows host, the registered Store Python 3.12 launcher was broken. The verified fallback installs the runtime inside the ignored `.python/` directory and creates `.venv` from its explicit interpreter path; the resulting interpreter is Python 3.12.14. The future bootstrap command will automate that fallback without relying on the Store launcher.

```text
uv python install 3.12.14 --install-dir .python --no-bin --no-registry
uv venv --python .python/cpython-3.12.14-windows-x86_64-none/python.exe .venv
.\.venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12); print(sys.version)"
```

## Planned local experience

The commands below describe the target developer contract and will be enabled incrementally; they are not claimed to work in this planning-only commit.

```text
python scripts/dev.py up
python scripts/dev.py fault inject --scenario http-500
python scripts/dev.py fault clean
python scripts/dev.py test
python scripts/dev.py test --suite e2e
python scripts/dev.py eval --model mock
```

These are the target commands and are not claimed to work in the planning-only baseline. The repository-owned Python task runner will be the single cross-platform entry point for Windows, POSIX shells, and CI; `make` may be offered later only as an optional convenience wrapper.

The simulator will include API Gateway, Order, Inventory, and Payment services, PostgreSQL, Redis, Prometheus, Loki, Tempo, and OpenTelemetry Collector. Six deterministic scenarios will cover deployment-induced HTTP 500s, database pool exhaustion, Redis timeout, downstream latency, memory leak, and bad configuration.

## Documentation

- [Project specification](docs/PROJECT_SPEC.md)
- [Architecture and workflows](docs/ARCHITECTURE.md)
- [Decision history and rationale](docs/DECISION_HISTORY.md)
- [Comparison with Programming Tutor](docs/COMPARISON_WITH_PROGRAMMING_TUTOR.md)
- [Data model](docs/DATA_MODEL.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Repository CI and branch governance](docs/REPOSITORY_GOVERNANCE.md)
- [Architecture decisions](docs/ADR/README.md)
- [Delivery plan](TODO.md)

## Repository discipline

Work is delivered in small, verifiable Conventional Commits. A TODO is checked only after its acceptance checks pass. Every completed batch must record its checks, commit SHA, and push status. Secrets, personal data, unredacted model data, and generated runtime artifacts are excluded from Git.

## Name note

The repository remains named `AgentOps`, while the documentation and portfolio display name is **AgentOps Incident Commander**. This standalone project is not affiliated with other products or repositories named AgentOps.
