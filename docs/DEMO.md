# Deterministic release demo

The Phase 13 demo is one bounded verification command for the release story. It exercises real
repository workflows and persistence tests; it is not a production incident drill, does not grant
model authority, and does not treat test cleanup as recovery.

## Run the demo

Prerequisites are the locked Python 3.12 environment and a reachable Docker Engine. No model
provider account, API key, live service credential, or running Compose stack is required.

```text
python scripts/dev.py demo
```

The command uses only immutable argument lists, invokes no shell, applies a timeout to every step,
and stops on the first failure. Pytest verbose mode prints every scenario and route being verified.
Temporary PostgreSQL Testcontainers and test artifacts are cleaned up by their owning fixtures.

## Demonstrated sequence

1. `mock-model-mode` runs the real deterministic `diagnosis-mock/1.0.0` adapter twice against
   fixed adversarial context. Stable fingerprints, bounded token counters, and zero recorded cost
   prove the demo needs no external model credential; the adapter still has no execution authority.
2. `docker-daemon` fails early if the persistence-backed portions cannot run.
3. `demo-six-fault-matrix` runs each label-free runtime scenario through Alert triage, current
   Evidence, Diagnosis, deterministic Evidence Gate, and its terminal safety route.
4. `demo-approved-recovery-and-verification-routes` runs the PostgreSQL-backed approved
   `rollback_service` chain with exact replay, then proves verifier `PASS` is the only close route
   and verifier `FAIL` can only re-diagnose or require a human. It never redeploys the faulty
   version and never enters generic compensation.
5. `demo-audit-and-crash-resume` checks every one of the 33 closed workflow audit outcomes and
   replaces the Diagnosis worker at every durable boundary, proving checkpoint resume without
   duplicate effects.

## Six-fault route matrix

The scenario runtime completes before evaluator-only Ground Truth is loaded. The verbose test IDs
show all six cases. The asserted outcomes are:

| Fault | MVP route | Write count |
| --- | --- | ---: |
| Release-induced HTTP 500 | Evidence-bound proposal, Policy, human Approval, one rollback, deterministic verification, closure | 1 |
| Database pool exhaustion | Human handoff: `POOL_CAPACITY_ACTION_UNAVAILABLE` | 0 |
| Redis timeout | Human handoff: `DEPENDENCY_RECOVERY_ACTION_UNAVAILABLE` | 0 |
| Downstream latency | Human handoff: `DOWNSTREAM_LATENCY_ACTION_UNAVAILABLE` | 0 |
| Deployment-linked memory leak | Evidence-bound proposal, Policy, human Approval, one rollback, deterministic verification, closure | 1 |
| Configuration drift | Human handoff: `CONFIGURATION_ACTION_UNAVAILABLE` | 0 |

The eligible scenario cases use stable verification observations to demonstrate successful
closure. The separate failure-route cases deliberately supply a typed failed verification and
show both bounded destinations: `INVESTIGATING` while a re-diagnosis attempt remains, and
`NEEDS_HUMAN` when it does not. Execution success by itself never counts as recovery.

## What the output proves

A zero exit code means the selected committed contracts passed on this machine. It proves neither
production availability nor model quality, and the elapsed lines printed by the task runner are
diagnostic timings rather than benchmark results. The canonical measured claims remain in the
[reproducible evaluation report](EVALUATION_REPORT.md).

If Docker Desktop reports an unresponsive WSL backend, follow the bounded recovery steps in the
[operations runbook](OPERATIONS_RUNBOOK.md#docker-desktop-or-wsl-is-unavailable), confirm
`docker info` succeeds, and rerun the same demo command.
