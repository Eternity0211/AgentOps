# Deterministic Fault Control

The repository-owned fault controller provides the state, locking, Compose overlay, run correlation, and cleanup contract used by all six Phase 1C scenarios. It is a deterministic developer tool, not an agent and not a production infrastructure controller.

## Commands

```text
python scripts/dev.py fault inject --scenario http-500
python scripts/dev.py fault inject --scenario http-500 --run-id run-demo001
python scripts/dev.py fault clean
python scripts/dev.py fault clean --run-id run-demo001
```

Scenario names are a fixed allowlist: `http-500`, `db-pool-exhaustion`, `redis-timeout`, `downstream-latency`, `memory-leak`, and `bad-configuration`. A known name is not sufficient for activation: the controller rejects it until that scenario's symptom, cleanup, and tests are implemented and registered. This prevents a container restart from being falsely reported as an active fault. Currently `http-500` is enabled; the other five fail closed.

Run IDs are generated as `run-` plus 12 hexadecimal characters, or supplied using the conservative `[a-z0-9][a-z0-9-]{5,63}` contract. They are correlation labels, not authorization tokens.

## State and transition contract

The controller holds a cross-platform non-blocking advisory lock for every transition. One active fault is allowed. Runtime files live under ignored `data/runtime/`:

- `fault-state.json` is a schema-versioned record containing run ID, scenario, derived target service, `applying`/`active` status, and UTC start time.
- `fault.override.yaml` contains only validated, generated environment values for the derived service target.
- `fault.lock` coordinates Windows and POSIX processes and is not a stale ownership marker.

Injection writes the generated overlay and recoverable `applying` state before invoking fixed-argument Compose. A failed Compose mutation removes both. A successful mutation atomically advances the state to `active`. Repeating the same run/scenario is idempotent; another run is refused until cleanup.

Cleanup derives the target again from the allowlisted scenario rather than trusting an arbitrary path or service from disk. It force-recreates that target from base `compose.yaml` without the fault overlay. State is removed only after Compose succeeds, so failed cleanup is retryable. Cleanup with no state is a successful no-op and removes an unused orphan overlay. It never deletes named volumes.

Both apply and reset subprocesses have a three-minute upper bound and use argument arrays without a shell. Missing Docker returns 127 and timeout returns 124. State parsing fails closed on unknown schemas, scenarios, targets, statuses, timestamps, or injected identifiers.

## Scenario boundary

The common overlay sets `SIMULATOR_FAULT_SCENARIO`, `SIMULATOR_FAULT_RUN_ID`, opaque service version `2.0.0`, baseline previous version `1.0.0`, and the run ID as deployment ID. The observable version deliberately does not contain the scenario name. Each scenario batch must separately implement the symptom, deterministic observation, reset behavior, bounds, and tests before adding its name to `IMPLEMENTED_SCENARIOS`.

### `http-500`

The controller recreates only Order with the generated overlay. Its `/healthz`, dependency-aware `/readyz`, and `/versionz` remain healthy so this represents a bad deployment rather than a dead process. Every `POST /v1/orders` deterministically returns HTTP 500 with the generic body `internal server error` before Inventory, Payment, or PostgreSQL is called. Gateway consequently observes a downstream failure. Request metrics and server spans record the 500, while responses, span attributes, access logs, and deployment-version fields do not expose the scenario name or run ID as a cause label.

Cleanup force-recreates Order from base Compose, removing both fault environment variables and restoring the baseline version fields. The run-scoped deployment ID makes the change correlatable without revealing evaluation Ground Truth.

Operational fault state contains no Ground Truth cause or evaluation label. Evaluation-only Ground Truth remains a later isolated artifact and must not be mounted or retrievable by simulator/control-plane runtime paths.

## Verification boundary

Unit tests cover state corruption, command construction, subprocess refusal/timeout, injection replay, conflicting runs, failed apply, repeatable cleanup, failed cleanup retry, run matching, Windows/POSIX lock acquisition and contention, and CLI validation. Docker Engine was unavailable on the implementation host, so no real scenario activation is claimed by this framework batch.
