# Operations runbook

This runbook covers the repository's local reference environment and the deterministic Incident
control boundaries. It does not grant production infrastructure access. An alert, model output,
dashboard, or shell session is never recovery authority.

## Start and stop the local reference stack

1. Confirm Python 3.12, Docker Engine, the ignored `.env`, and five distinct runtime secret files.
2. Run `python scripts/dev.py doctor`. Fix the named prerequisite; do not bypass the check.
3. Run `python scripts/dev.py up`. It validates Compose, starts the simulator and observability
   profiles with a bounded wait, then checks all repository-owned health endpoints.
4. Run `python scripts/dev.py status` before a demo or fault exercise.
5. Run `python scripts/dev.py down` when finished. This removes containers and networks but
   preserves named volumes.

If startup fails, `up` automatically stops partial containers. Inspect the bounded diagnostic,
correct the prerequisite, and rerun. Do not delete a named volume merely to hide an unexplained
database failure.

## Docker Desktop or WSL is unavailable

Symptoms include a missing `dockerDesktopLinuxEngine` pipe, `WSL is unresponsive`, or every
Testcontainers case failing before collection setup.

1. Confirm `docker version` shows a client but cannot reach the server.
2. Restart Docker Desktop. If its WSL backend is unresponsive, close Docker Desktop, run
   `wsl --shutdown`, and reopen Docker Desktop. This stops all WSL distributions, so first ensure
   no unrelated work is running there.
3. Wait until `docker info` returns a server version.
4. Rerun `python scripts/dev.py doctor`, then the failed command. Do not reinterpret a missing
   daemon as a product test failure.

## Triage an alert or unhealthy service

1. Preserve the Alert, affected service, observation window, and correlation identifiers.
2. Open the diagnosed-system dashboard and compare error rate, P95 latency, dependency behavior,
   deployment markers, logs, and traces for the same window.
3. Start or attach to an Incident through the typed API/control path. Do not invoke a service
   mutation from Grafana, Prometheus, Loki, Tempo, or a model response.
4. Collect current observations through the read-only Tool Gateway. Every factual diagnosis
   reference must resolve to Incident-owned Evidence and immutable Artifact provenance.
5. Treat missing telemetry as missing evidence, not proof of health. Follow the alert-specific
   procedures in [Observability alert runbooks](OBSERVABILITY_RUNBOOKS.md).

## Approval and recovery

1. Confirm the Evidence Gate passed for the exact root-cause candidate and the Remediation Agent
   produced a schema-valid, allowlisted proposal.
2. Review the deterministic Policy result, proposal fingerprint, target, stable version, risk,
   expiry, validation criteria, and failure route.
3. Enforce separation of duties. The proposer cannot approve when the Policy requires separation.
4. Approve or reject only through the versioned API/console. Never edit a database row to simulate
   approval.
5. The deterministic Executor must revalidate Policy, approval, expiry, proposal fingerprint,
   target lock, Incident ID, Approval ID, and Idempotency Key immediately before dispatch.
6. Treat execution success as provisional. Only the deterministic verifier may close recovery
   after the configured stability window across error rate, P95 latency, health, deployed version,
   and new alerts.

`rollback_service` is the recovery action. If verification fails, route to bounded re-diagnosis or
human handoff. Never automatically redeploy the known faulty version and never invent a generic
compensation step.

## Worker crash, replay, or stalled work

1. Check the durable Job lease, heartbeat, attempt budget, workflow checkpoint, and correlation
   ledger. Telemetry alone is insufficient.
2. Allow the PostgreSQL lease timeout and claim logic to select one new owner. Do not manually
   clear the lease while the former worker may still be alive.
3. A replacement worker resumes the saved LangGraph thread and reuses stable operation identities.
   It must replay committed results rather than repeat external effects.
4. If the attempt budget is exhausted or ownership is uncertain, preserve records and route to
   `NEEDS_HUMAN`/dead-letter handling according to the stored route.

## Audit integrity failure

For `AUDIT_INTEGRITY_FAILED`, a sequence gap, fingerprint mismatch, duplicate identity, or private
head mismatch:

1. Stop relying on the affected export or timeline; no partial result is trustworthy.
2. Preserve database snapshots and relevant logs without changing audit rows or sequence heads.
3. Verify the runtime connection is the restricted role, not the database owner.
4. Escalate to the database owner/security operator for forensic review. Corrections are new audit
   events; historical rows are never updated or deleted.

The current design does not claim external anchoring against a compromised database owner.

## Database migration and credential rotation

1. Back up according to the deployment's database procedure; this repository does not claim a
   production backup implementation.
2. Run reviewed Alembic migrations with the deployment migrator/object owner, never an API or
   worker credential.
3. Reapply `config/postgres/control-plane-runtime-grants.sql` as documented in
   [Database and service least privilege](DATABASE_SECURITY.md).
4. Validate the real-login refusal matrix with the integration suite before rollout.
5. Rotate runtime secrets through the deployment secret manager and restart only the affected
   process. Simulator PostgreSQL role initialization runs only on a new local volume; rotate its
   password explicitly as owner or recreate only a confirmed disposable local volume.

## Fault exercise and cleanup

Use only the six fixed scenarios:

```text
python scripts/dev.py fault inject --scenario http-500
python scripts/dev.py fault inject --scenario db-pool-exhaustion
python scripts/dev.py fault inject --scenario redis-timeout
python scripts/dev.py fault inject --scenario downstream-latency
python scripts/dev.py fault inject --scenario memory-leak
python scripts/dev.py fault inject --scenario bad-configuration
python scripts/dev.py fault clean
```

Always run `fault clean`, then `status`, after an exercise. Evaluator cleanup is test control, not
a runtime remediation action. Ground Truth remains evaluation-only and must never be copied into an
Incident, Evidence record, prompt, or runtime mount.

## Escalation record

When handing off, record the Incident and correlation IDs, current state, confirmed Evidence IDs,
counter/missing evidence, attempted bounded operations, last durable checkpoint, lease/execution
status, approval status/expiry, exact blocker, and the safe next input required. Exclude secret
values, raw model content, unredacted telemetry, and Ground Truth labels.
