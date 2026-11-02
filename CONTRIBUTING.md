# Contributing to AgentOps Incident Commander

Contributions must preserve the product invariant: models may diagnose and propose, but only
deterministic, typed, policy- and approval-controlled components may execute or verify recovery.
Read `AGENTS.md`, `docs/PROJECT_SPEC.md`, `docs/ARCHITECTURE.md`, relevant ADRs, and `TODO.md` before
changing code.

## Development setup

1. Install Git, Docker Engine/Desktop, and `uv`.
2. Install the pinned Python and dependencies:

   ```text
   uv python install 3.12.14
   uv sync --frozen --all-groups
   ```

3. Copy `.env.example` to the ignored `.env` only when running the local stack. Create five
   distinct local-only secret files described in [Configuration reference](docs/CONFIGURATION.md).
4. Run `python scripts/dev.py doctor` before container-backed work.

Do not commit `.env`, credentials, generated runtime data, large logs, raw model content, personal
data, or evaluation outputs that were not produced by the versioned create-only runner.

## Change workflow

Choose one logically complete TODO batch with explicit acceptance criteria and a test plan. Keep
domain rules independent of FastAPI, LangGraph, SQLAlchemy, and provider adapters. Prefer explicit
types and state transitions over booleans or free-form dictionaries. Every external call needs a
timeout; retries are bounded and classified.

A complete batch updates implementation, tests, documentation, and `TODO.md` together. Never mark
a TODO complete while a required check is failing. Preserve unrelated working-tree changes and do
not rewrite pushed history or force-push.

Use Conventional Commits, for example:

```text
feat: enforce least-privilege runtime boundaries
fix: reject stale approval replay
docs: complete operator runbooks
```

The repository currently permits the documented atomic direct-push workflow. A collaborator may
use a feature branch and pull request, but documentation must not claim remote branch protection or
required reviews until those settings are independently verified.

## Required verification

Run the checks appropriate to the change, then the complete gate before committing:

```text
python scripts/dev.py quality
python scripts/dev.py pre-commit
```

Container-backed changes also require the relevant fixed suite, commonly:

```text
python scripts/dev.py test --suite integration
python scripts/dev.py test --suite e2e
python scripts/dev.py test --suite security
```

Frontend changes run `npm ci`, `npm run verify`, and `npm run test:browser` from `console/`.
Evaluation changes run `python scripts/dev.py eval --model mock` and must retain raw, versioned
inputs/results that reproduce every quantitative statement.

Before committing, review staged files for credentials, tokens, passwords, personal data, large
logs, and unredacted model/telemetry content. The final commit must be atomic, pushed immediately,
and reported with checks, results, SHA, and push status.

## Architecture and safety review

Reject a change that:

- lets an LLM call a write adapter, arbitrary shell, URL, path, or infrastructure client;
- bypasses schema validation, Evidence Gate, Policy, human approval, locks, idempotency, or the
  deterministic verifier;
- relabels collectors, validators, Policy, Executor, Verifier, or compensation control as agents;
- adds Kafka, NATS, control-plane Redis, A2A, MCP write paths, or Kubernetes authority without a
  measured need and superseding ADR;
- exposes Ground Truth, credentials, raw telemetry, prompts, or model responses to an unauthorized
  runtime path;
- treats confidence, execution success, or missing telemetry as recovery proof;
- automatically redeploys the known faulty version after failed `rollback_service` verification.

New write tools require a new ADR, typed schema, RBAC, threat review, Policy rules, human approval,
idempotent executor, before/after snapshots, deterministic verification, explicit failure routing,
and adversarial tests. Generic compensation remains future-only and requires an independently
authorized safe inverse.

## Documentation and claims

Update the canonical document rather than duplicating a second source of truth. New architectural
decisions use the template described in `docs/ADR/README.md`; accepted ADRs are not rewritten and
are superseded by a new record. Keep local Markdown links valid and run `python scripts/dev.py docs`.

Do not invent latency, scale, reliability, cost, quality, or resume metrics. Use “production-
oriented” only with the implemented controls and limitations. Portfolio and résumé statements must
link to committed, reproducible evaluation results.
