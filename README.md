# AgentOps Incident Commander

AgentOps Incident Commander is an evidence-driven platform for diagnosing microservice incidents and performing controlled recovery. It combines metrics, logs, traces, topology, and deployment history; a constrained Diagnosis Agent builds verifiable root-cause hypotheses; a constrained Remediation Agent proposes recovery only after a deterministic evidence gate passes. Deterministic policy, approval, execution, health verification, and failure routing retain authority over every state change.

> Status: Phase 1 through Phase 7 are complete. The reproducible simulator and live local Compose verification remain documented in the versioned [Phase 1 verification record](docs/PHASE_1_VERIFICATION.md). The control plane includes the framework-free [typed domain model](docs/DOMAIN_MODEL.md), complete Incident lifecycle, deterministic Alert triage, a [PostgreSQL/pgvector persistence foundation](docs/PERSISTENCE.md) with append-only audit, transactional outbox, durable JobLease queue, tenant ownership, command idempotency, and immutable Evidence Gate decisions, separate [API/worker process composition](docs/CONTROL_PLANE_PROCESSES.md) with bounded runtime controls, tenant-scoped [authentication/RBAC contracts](docs/AUTHORIZATION.md), and a fail-closed [versioned business API](docs/API_V1.md) with a committed OpenAPI snapshot and stable problem-detail conventions. Phase 3 includes [immutable Artifact storage](docs/ARTIFACT_STORAGE.md), a tenant-scoped [Evidence model, normalization, quality, verification, redaction, untrusted-telemetry quarantine, and budgeted Context Builder pipeline](docs/EVIDENCE_MODEL.md), five bounded [deterministic collectors](docs/COLLECTORS.md), log error clustering, metric trend summaries, trace critical-path/error summaries, Incident-window deployment correlation with raw Artifact provenance, and tenant-scoped Evidence/Artifact read APIs with verified content bindings. Phase 4 includes the immutable, fail-closed [versioned ToolDefinition registry and deterministic Tool Gateway](docs/TOOL_GATEWAY.md) with conservative schema compatibility, validation, RBAC, exact dispatch, bounded timeout/retry/result controls, hash-only audit events, five bounded live read-tool v1 adapters, the disabled historical-reference-only `search_similar_incidents` v1 contract, and a diagnosis-only read catalog with recursive URL/path/command rejection. Phase 5 includes the versioned [deterministic Evidence Gate](docs/EVIDENCE_GATE.md), resolvable/owned/fresh/independent evidence checks, explicit counter/missing-evidence handling, confidence non-authority, reproducible persistence, audit binding, and adversarial fail-closed coverage. A production authentication adapter and production Artifact backend remain open; no production-scale or reliability claim is implied.

Phase 6 now includes the versioned [Prompt Registry](docs/PROMPT_REGISTRY.md),
[content-free model-call tracing](docs/MODEL_CALL_TRACING.md), strict
[Diagnosis Agent schemas](docs/DIAGNOSIS_SCHEMAS.md), the
[versioned graph-state contract](docs/GRAPH_STATE.md), and all-or-nothing
[diagnosis-plan compilation](docs/DIAGNOSIS_PLANNING.md) against the server tool catalog and hard
resource budgets. The executable [bounded Diagnosis LangGraph](docs/DIAGNOSIS_GRAPH.md) now routes
context loading, planning, parallel read tools, evidence persistence, hypotheses, deterministic
gating, bounded replanning, repeated-equivalent-query refusal, and human handoff. Production
provider invocation remains disabled. The official PostgreSQL LangGraph checkpointer now provides
strictly serialized, thread/run-correlated history and restore. Every Diagnosis node now supports
durable pre-effect pause/resume, safe-boundary cancellation, and stable operation identities for
exact effect replay. A checkpoint-aware runner now distinguishes new work from continuation,
survives worker replacement at every durable Diagnosis boundary, and exposes bounded content-free
checkpoint observations. The credential-free [deterministic mock model](docs/MOCK_MODEL.md) now
supplies versioned valid, malformed, timeout, refusal, fabricated-reference, and
injection-resistant fixtures; production service composition and provider invocation remain
disabled. Every Diagnosis node now resolves the exact tenant-scoped Prompt version and confirms
that it is the single active `DIAGNOSIS` registration before control handling or any node effect;
unregistered, stale, non-active, wrong-purpose, or fingerprint-mismatched references fail closed.

Phase 7 now includes the immutable confirmed Incident-memory projection and its transactionally
bound, versioned [pgvector index](docs/INCIDENT_MEMORY.md), plus authorized same-tenant similarity
retrieval with explicit freshness and leakage controls and an enabled Tool Gateway v2 adapter.
Only authoritative closed Incidents can enter it; source Evidence, Diagnosis Report, Evidence Gate,
confirmation, outcome, trust, and content fingerprint metadata remain bound. Its trust is always
`HISTORICAL_REFERENCE`, so old incidents remain advisory. The enabled Tool Gateway v2 adapter
accepts only a bounded result count; its query vector, tenant, current Incident, clock, and
freshness window are server owned. The immutable disabled v1 contract remains available for exact
replay. Evidence Gate ruleset `1.1.0` explicitly fails any candidate that cites historical memory
as current supporting or counter Evidence.
Memory-aware Prompt versions declare the exact memory-context schema they consume and cannot leave
`DRAFT` until every regression fixture has safe, complete no-memory/with-memory results. The paired
gate rejects missing modes, failed fixtures, unsupported conclusions, fabricated references,
authorization violations, and any Ground Truth exposure; accepted snapshots are hash-bound and
persisted with the lifecycle audit before promotion is possible.

Phase 8 begins with the strict [Remediation Agent proposal contract](docs/REMEDIATION_PROPOSAL.md).
It permits only a bounded `rollback_service` proposal, keeps deployment versions and execution
credentials outside model authority, requires non-bypassable policy/approval/lock prerequisites,
defines deterministic-verifier inputs and safe failure routing, and makes compensation eligibility
structurally false for this recovery action. A deterministic admission gate now re-resolves the
exact tenant/Incident/candidate Evidence Gate record and accepts only a fingerprint-matching
immutable `PASS`; absent, failed, stale, changed, or cross-tenant decisions cannot reach policy.
The versioned [deterministic Policy Engine contracts](docs/POLICY_ENGINE.md) now bind proposal,
Evidence Gate, actor/role, environment, target, blast-radius, maintenance, and separation inputs to
stable fingerprints, with closed risk/outcome enums, structured reasons, and bounded approval
lifetimes. Its server-owned rules evaluate those controls in fixed order, retain every denial
reason, derive risk deterministically, and can only advance a valid rollback to
`APPROVAL_REQUIRED`; it never authorizes or executes a mutation.
The [proposal-bound Approval lifecycle](docs/APPROVALS.md) now enforces expiring hash bindings,
Approver RBAC, medium/high/critical-risk separation of duties, finite terminal transitions,
optimistic persistence, and transactionally matched lifecycle/audit records. Approval remains a
human control record only and cannot invoke recovery.
Any accepted material proposal revision now creates an immutable approval-invalidation marker,
rejects version-only or identity-changing edits, and reruns strict schema validation, exact
Evidence Gate admission, and complete Policy evaluation. Gate/Policy failure cannot revive the old
approval, while a successful re-evaluation still requires a newly issued human Approval.
The versioned [Approval interrupt graph](docs/APPROVAL_GRAPH.md) now persists a content-free human
wait in PostgreSQL and accepts only a `RECHECK` resume directive. Every resume reloads the
tenant-scoped Approval and invalidation marker; only an unexpired, non-invalidated, exact
fingerprint match can become execution-ready, while all refusal routes remain non-executable.
The strict [`rollback_service` v1 contract](docs/ROLLBACK_SERVICE.md) now requires Incident,
Approval, and idempotency identities while excluding commands and caller-selected targets. Its
tenant/service/environment target and stable version resolve only from a server-owned allowlist;
the mutation adapter remains deliberately unregistered until the Executor and verifier safety
gates are complete.
The immutable [ActionExecution lifecycle](docs/ACTION_EXECUTION.md) now binds authority,
server-resolved target, before/after Artifact snapshots, outcome, timing, and canonical fingerprint;
success requires snapshot proof of the configured stable version. PostgreSQL now persists execution
and lifecycle records, serializes concurrent idempotency/target claims, replays stored terminal
results, records each explicitly observed replay as a separate hash-bound audit event, and
atomically releases target locks on completion. The framework-independent execution preflight
reloads Incident/Approval/invalidation authority, replays Evidence Gate and Policy, enforces
execution RBAC and approval expiry/hash bindings, and resolves observed current and stable versions
only through server-owned ports. The crash-safe Executor application path now composes that
preflight with an idempotent before snapshot, a transaction-owning PostgreSQL claim, atomic replay
audit, one bounded typed dispatch, and terminal persistence. A durable claim always commits before
the adapter call; every concurrent or retried duplicate returns the stored execution without a
second mutation. The server kill switch remains disabled by default, and only the deterministic
verifier may declare recovery. The Phase 8 safety matrix
now includes a PostgreSQL concurrent-approval race plus rejection/expiry, mutation
classification, replay, duplicate delivery, timeout, authorization, and bypass coverage; its
server-side mutation flag remains off unless trusted worker configuration explicitly enables it.

Phase 9 now has the first versioned [deterministic health-verification contract](docs/HEALTH_VERIFICATION.md).
It binds a successful ActionExecution to one of the two rollback-eligible scenarios, exact
server-owned target scope, five distinct Evidence references, bounded per-sample observations, and
a continuous stability window. Every sample must satisfy error-rate, P95 latency, health endpoint,
stable-version, and zero-new-alert rules; stale, incomplete, gapped, flapping, or substituted input
fails closed with stable reason codes. The application path now resolves all five series through
owned, fresh, direct Evidence and hash-verified immutable Artifacts, checks controlled source/query
purpose, and compares every timestamp and value before it permits deterministic evaluation. A
bounded all-or-nothing collector now obtains aligned error-rate, P95, health-probe, active-version,
and new-alert samples through fixed read-only ports and emits the five canonical Evidence/Artifact
series. PostgreSQL now persists each accepted observation and decision with same-scope foreign
keys to the successful ActionExecution and all five Evidence records, exact replay semantics,
ordered reasons, hash-bound audit, and corruption detection. An authorized deterministic success
router now locks the persisted PASS and Incident, then atomically records the legal
`VERIFYING -> RESOLVED -> CLOSED` transitions and a hash-bound audit; duplicate and concurrent
delivery replay the same closure without extra transitions. Persisted FAIL decisions now follow a
separate non-compensable route: one proposal-bound budgeted attempt returns to `INVESTIGATING`,
while exhaustion or an explicit zero budget enters `NEEDS_HUMAN`; neither route can redeploy the
faulty version or enter compensation. The architecture gate also rejects executable compensation
modules, controllers, functions, or tool identifiers from the MVP application, workflow, and
infrastructure layers while retaining the explicitly future-only domain states. A single deterministic
recovery coordinator now composes the authorized executor, persisted verifier, and exclusive
success/failure routers: unsuccessful execution never reaches
verification, every authority and decision fingerprint remains exact, `PASS` alone may close,
and `FAIL` alone may re-diagnose or hand off. PostgreSQL integration now proves both composed
routes and exact replay without duplicate route audit. The live persisted verifier now composes
five-signal collection, immutable Artifact/Evidence persistence, full re-resolution,
deterministic evaluation, hash-bound audit, and exact decision replay. A narrow server-bound
rollback adapter now admits only the preflight-resolved typed target and Idempotency Key and reads
back the deployed semantic version; it exposes no command, URL, manifest, namespace, credential,
or caller-selected target. Before and
after deployment observations now persist as deterministic-identity, immutable, hash-bound Artifact
snapshots; exact retries reuse validated content while version, scope, and operation substitutions
fail closed. A deterministic local-simulator-only deployment backend now provides exact-target,
concurrent-idempotent state transition and live `/versionz` observation for the recovery E2E
suite; it is not a production provider and does not enable the default-off mutation switch.
The lifecycle-aware PostgreSQL execution store now commits a new action claim with the Incident's
entry into `EXECUTING`, then commits the terminal execution with its deterministic next state:
success enters `VERIFYING`, confirmed pre-effect failure re-diagnoses, and timeout or uncertainty
requires a human. Exact replays cannot duplicate or rewind those audited transitions.
The final authorized local E2E now explicitly enables the test-only capability and composes the
server-bound adapter, simulator deployment state, immutable before/after snapshots, lifecycle-aware
execution, live five-signal persistence, deterministic `PASS`, and success routing. It proves one
deployment mutation, one ActionExecution, five Evidence records, one verification decision, and the
four legal Incident transitions through `CLOSED`; exact replay reuses those results without a
second mutation, collection, verification, or closure. After that gate, the worker-owned recovery
composition now wires an injected typed deployment backend through the same Executor, verifier,
and transaction-owning PASS/FAIL routers. `AGENTOPS_RECOVERY_MUTATION_ENABLED` remains false by
default and a disabled attempt stops before preflight or any effect; the repository intentionally
ships no production Kubernetes controller or API write endpoint.
Phase 9 also includes [constrained postmortem drafting](docs/POSTMORTEM.md) for closed Incidents.
It accepts only bounded, pre-confirmed facts backed by resolvable current-Incident Evidence and
hash-verified Artifacts. The registered postmortem model may arrange fact IDs into typed sections
but cannot author factual prose; the server rejects fabricated, omitted, duplicated, cross-scoped,
historical, stale, injected, or tampered references and renders the exact confirmed statements and
Evidence IDs deterministically. Prompt identity, request/response hashes, status, token/cost
metadata, actor, and workflow correlation are traced. Versioned human revisions and their
authorship/audit are persisted as immutable consecutive history with server-derived Operator
authorship, inherited source Fact/Evidence references, optimistic concurrency, append-only database
protection, and atomic hash-only audit. Anonymous, read-only, cross-tenant, stale, forged-parent,
substituted-reference, and corrupt-history paths fail closed.

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

## Local runtime commands

After creating the local secret files described below and starting Docker Engine, the fixed task runner controls the simulator and observability profiles:

```text
python scripts/dev.py up
python scripts/dev.py status
python scripts/dev.py down
```

`up` validates the static Compose contract and Docker daemon, builds/starts with Compose `--wait`, then checks Gateway readiness/version, Prometheus/Loki/Tempo readiness, and the Collector's Prometheus target. A post-start failure automatically stops partial containers without deleting named volumes. `status` repeats the observable health contract. `down` removes containers and orphans but deliberately does not remove persistent volumes.

The fault controller syntax and safe state/cleanup framework are available for all six scenarios. The focused in-process smoke suite verifies the four-service baseline, each fault symptom, and restoration to a fresh baseline without requiring Docker. Container E2E and evaluation commands remain reserved:

```text
python scripts/dev.py fault inject --scenario http-500
python scripts/dev.py fault inject --scenario db-pool-exhaustion
python scripts/dev.py fault inject --scenario redis-timeout
python scripts/dev.py fault inject --scenario downstream-latency
python scripts/dev.py fault inject --scenario memory-leak
python scripts/dev.py fault inject --scenario bad-configuration
python scripts/dev.py fault clean
python scripts/dev.py test --suite smoke
python scripts/dev.py test --suite e2e
python scripts/dev.py eval --model mock
```

See [Deterministic fault control](docs/FAULT_INJECTION.md) for run IDs, concurrency, recovery state, cleanup, and the scenario enablement boundary.

The repository-owned Python task runner below is the single cross-platform entry point for Windows, POSIX shells, and CI; `make` may be offered later only as an optional convenience wrapper.

## Python quality commands

The Python workspace uses the committed `uv.lock`. After bootstrapping Python 3.12.14:

```text
uv sync --frozen --all-groups
uv lock --check
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen python scripts/check_architecture.py
uv run --frozen python scripts/check_compose.py
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
python scripts/dev.py compose
python scripts/dev.py typecheck
python scripts/dev.py test --suite unit
python scripts/dev.py test --suite smoke
python scripts/dev.py docs
python scripts/dev.py build
python scripts/dev.py pre-commit
python scripts/dev.py up
python scripts/dev.py status
python scripts/dev.py down
```

The runner never forwards arbitrary shell text: every task maps to an immutable argument list, runs without a shell, has a timeout, stops on first failure, and emits start/pass/fail timing lines. The `architecture` task rejects domain imports of FastAPI, SQLAlchemy, LangGraph/LangChain, model-provider SDKs, or higher internal layers. The smoke suite is deliberately in-process; E2E and evaluation tasks remain unavailable until their implementation phases.

## Compose foundation

Copy `.env.example` to the ignored `.env` file, then create the three ignored runtime secret files referenced by `CONTROL_DB_PASSWORD_FILE`, `SIMULATOR_DB_PASSWORD_FILE`, and `SIMULATOR_REDIS_PASSWORD_FILE`. Each file must contain a distinct, non-empty local-only credential. The isolated evaluator additionally uses `GROUND_TRUTH_ACCESS_FILE` only with `compose.evaluation.yaml`. The repository does not commit working credentials or unsafe fallback passwords; absent secret files prevent profile startup.

The current topology is intentionally profile-scoped: `control-plane` provides its isolated PostgreSQL store, `simulator` provides the diagnosed PostgreSQL and Redis dependencies, and `observability` provides Prometheus, Loki, Tempo, and the OpenTelemetry Collector. Persistent stores use named volumes; runtime root filesystems are read-only; CPU, memory, and process counts are bounded; and published observability ports bind to `127.0.0.1` by default. `python scripts/dev.py compose` renders every profile with synthetic secret sentinels and verifies those invariants without starting containers or exposing the sentinels.

The image tags are explicit release versions selected from the upstream PostgreSQL, Redis, Prometheus, Grafana Loki/Tempo, and OpenTelemetry Collector release streams on 2026-10-01. Digest locking and the update/SBOM policy remain a later hardening item and are not claimed here.

The simulator includes API Gateway, Order, Inventory, and Payment services plus isolated PostgreSQL and Redis dependencies. Order writes are idempotent, Inventory reservations are atomic and idempotent, and dependency-aware readiness fails closed. Services emit bounded traces, HTTP metrics, and trace-linked logs through the OpenTelemetry Collector toward Prometheus, Loki, and Tempo. Six deterministic scenarios cover deployment-induced HTTP 500s, database pool exhaustion, Redis timeout, downstream latency, memory leak, and bad configuration. Their labels live behind a separate evaluator image, Compose file/profile, internal network, read-only path, and credential; runtime/model-capable paths are protected by leakage-canary tests.

## Documentation

- [Project specification](docs/PROJECT_SPEC.md)
- [Architecture and workflows](docs/ARCHITECTURE.md)
- [Decision history and rationale](docs/DECISION_HISTORY.md)
- [Comparison with Programming Tutor](docs/COMPARISON_WITH_PROGRAMMING_TUTOR.md)
- [Data model](docs/DATA_MODEL.md)
- [Operational persistence foundation](docs/PERSISTENCE.md)
- [Control-plane API and worker processes](docs/CONTROL_PLANE_PROCESSES.md)
- [Authentication principal and RBAC](docs/AUTHORIZATION.md)
- [Versioned control-plane API](docs/API_V1.md)
- [Immutable Artifact storage](docs/ARTIFACT_STORAGE.md)
- [Immutable Evidence model](docs/EVIDENCE_MODEL.md)
- [Deterministic Evidence collectors](docs/COLLECTORS.md)
- [Versioned Tool Gateway contracts](docs/TOOL_GATEWAY.md)
- [Deterministic Evidence Gate](docs/EVIDENCE_GATE.md)
- [Versioned Prompt Registry](docs/PROMPT_REGISTRY.md)
- [Content-free model-call tracing](docs/MODEL_CALL_TRACING.md)
- [Deterministic Diagnosis mock model](docs/MOCK_MODEL.md)
- [Versioned Diagnosis graph state](docs/GRAPH_STATE.md)
- [Diagnosis Agent structured schemas](docs/DIAGNOSIS_SCHEMAS.md)
- [Deterministic diagnosis-plan compilation](docs/DIAGNOSIS_PLANNING.md)
- [Bounded Diagnosis LangGraph](docs/DIAGNOSIS_GRAPH.md)
- [Confirmed historical Incident memory](docs/INCIDENT_MEMORY.md)
- [Remediation Agent proposal contract](docs/REMEDIATION_PROPOSAL.md)
- [Deterministic Policy Engine contracts](docs/POLICY_ENGINE.md)
- [Proposal-bound Approval lifecycle](docs/APPROVALS.md)
- [Typed rollback_service contract](docs/ROLLBACK_SERVICE.md)
- [Recovery ActionExecution lifecycle](docs/ACTION_EXECUTION.md)
- [Deterministic health verification](docs/HEALTH_VERIFICATION.md)
- [Constrained postmortem drafting and versioned human revisions](docs/POSTMORTEM.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Repository CI and branch governance](docs/REPOSITORY_GOVERNANCE.md)
- [Local Compose foundation](docs/COMPOSE.md)
- [Simulator service contracts](docs/SIMULATOR_SERVICES.md)
- [Simulator observability baseline](docs/OBSERVABILITY.md)
- [Deterministic fault control](docs/FAULT_INJECTION.md)
- [Evaluation-only Ground Truth](docs/GROUND_TRUTH.md)
- [Phase 1 live verification](docs/PHASE_1_VERIFICATION.md)
- [Architecture decisions](docs/ADR/README.md)
- [Delivery plan](TODO.md)

## Repository discipline

Work is delivered in small, verifiable Conventional Commits. A TODO is checked only after its acceptance checks pass. Every completed batch must record its checks, commit SHA, and push status. Secrets, personal data, unredacted model data, and generated runtime artifacts are excluded from Git.

## Name note

The repository remains named `AgentOps`, while the documentation and portfolio display name is **AgentOps Incident Commander**. This standalone project is not affiliated with other products or repositories named AgentOps.
