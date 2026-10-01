# AgentOps Incident Commander

AgentOps Incident Commander is an evidence-driven platform for diagnosing microservice incidents and performing controlled recovery. It combines metrics, logs, traces, topology, and deployment history; a constrained Diagnosis Agent builds verifiable root-cause hypotheses; a constrained Remediation Agent proposes recovery only after a deterministic evidence gate passes. Deterministic policy, approval, execution, health verification, and failure routing retain authority over every state change.

> Status: Phase 1A complete. The Python workspace, cross-platform task runner, and enforced domain import boundaries exist; simulator and incident-domain business implementation begin in subsequent batches.

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

The commands below describe the remaining developer contract and will be enabled incrementally. They currently fail closed instead of pretending that an unavailable capability ran.

```text
python scripts/dev.py up
python scripts/dev.py fault inject --scenario http-500
python scripts/dev.py fault clean
python scripts/dev.py test
python scripts/dev.py test --suite e2e
python scripts/dev.py eval --model mock
```

The repository-owned Python task runner below is the single cross-platform entry point for Windows, POSIX shells, and CI; `make` may be offered later only as an optional convenience wrapper.

## Python quality commands

The Python workspace uses the committed `uv.lock`. After bootstrapping Python 3.12.14:

```text
uv sync --frozen --all-groups
uv lock --check
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen python scripts/check_architecture.py
uv run --frozen mypy src scripts tests
uv run --frozen pytest
uv run --frozen pre-commit run --all-files
uv build --offline --no-sources
```

The same commands run in the `Python Quality / quality` GitHub Actions job. The current package is intentionally minimal; simulator and application code arrive in later atomic batches.

If the host restricts the normal user cache directory, set `PRE_COMMIT_HOME` to the ignored repository-local `.pre-commit-cache` directory before running pre-commit. The project task runner normalizes this automatically.

## Cross-platform task runner

The repository now provides one fixed-command development entry point used by Windows and CI:

```text
python scripts/dev.py sync
python scripts/dev.py quality
python scripts/dev.py format
python scripts/dev.py format --write
python scripts/dev.py lint
python scripts/dev.py architecture
python scripts/dev.py typecheck
python scripts/dev.py test --suite unit
python scripts/dev.py docs
python scripts/dev.py build
python scripts/dev.py pre-commit
```

The runner never forwards arbitrary shell text: every task maps to an immutable argument list, runs without a shell, has a timeout, stops on first failure, and emits start/pass/fail timing lines. The `architecture` task rejects domain imports of FastAPI, SQLAlchemy, LangGraph/LangChain, model-provider SDKs, or higher internal layers. Future `up`, fault, E2E, and evaluation tasks remain unavailable until their implementation phases.

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
