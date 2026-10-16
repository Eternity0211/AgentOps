# Observability alert runbooks

These runbooks cover the versioned local Prometheus rules for the diagnosed-system and AgentOps
control-plane layers. An alert is an operational signal, not Evidence Gate proof, policy approval,
execution authority, or recovery verification. Do not mutate infrastructure from Grafana,
Prometheus, Loki, or Tempo. Use the versioned read-only Tool Gateway to collect Incident-owned
Evidence and retain the required deterministic safety chain for any recovery.

The reference stack evaluates alerts locally and shows them in Prometheus and the two provisioned
Grafana dashboards. It deliberately does not configure an external paging receiver or embed a
credential. A deployment that adds notification delivery must manage receiver secrets outside Git
and preserve these rule names, layer/severity labels, and runbook links.

## Diagnosed-system alerts

<a id="diagnosed-system-high-error-rate"></a>
### Diagnosed-system high error rate

1. Confirm the affected `service_name`, the five-minute request volume, and that the 5xx ratio has
   remained above 5% for the alert's five-minute hold.
2. Open **AgentOps / Diagnosed system** and compare request status, P95 latency, dependency
   failures, deployment markers, and trace-linked logs in the same time window.
3. Start or attach to the Incident through the normal alert/triage path. Query metrics, logs,
   traces, deployments, and topology through the read-only Tool Gateway so every cited fact becomes
   resolvable Evidence.
4. Do not infer a version rollback from this alert alone. Only a passing Evidence Gate, Policy
   Engine decision, current human approval, deterministic Executor, and Health Verifier may close
   the recovery chain.

<a id="diagnosed-system-high-p95-latency"></a>
### Diagnosed-system high P95 latency

1. Confirm meaningful traffic is present and P95 exceeds 1,000 ms for the full hold window; exclude
   a single sparse histogram sample.
2. Compare server latency with downstream client and PostgreSQL/Redis dependency timing, then inspect
   Tempo traces for the critical path using the Incident's correlation window.
3. Collect current, direct Evidence. Treat downstream latency, pool saturation, and service CPU or
   memory behavior as separate hypotheses until the evidence distinguishes them.
4. Route non-version-remediable causes to a human; do not force `rollback_service` for dependency or
   external configuration failures.

<a id="diagnosed-system-dependency-failures"></a>
### Diagnosed-system dependency failures

1. Identify the affected service and closed dependency label (`postgres` or `redis`).
2. Check dependency duration, result, relevant service errors, and trace topology over the same
   window; never inspect or export SQL, Redis keys/values, credentials, or exception payloads.
3. Use the read-only collectors to persist owned Evidence and distinguish a dependency outage from
   client timeout, pool exhaustion, or application failure.
4. The MVP recovery matrix requires human handoff for pool exhaustion and Redis timeout; evaluator
   cleanup is not a runtime recovery action.

## Agent-platform alerts

<a id="agent-platform-failure-ratio"></a>
### Agent-platform failure ratio

1. Open **AgentOps / Agent platform** and split the failures by component, operation, and outcome.
2. Use the durable Incident timeline, correlation ledger, checkpoints, Job leases, and append-only
   audit records to determine whether work safely retried, paused, handed off, or stopped.
3. Check dependency availability before changing a timeout or retry budget. Existing budgets are
   safety bounds and must not be raised merely to silence the alert.
4. Never replay a write outside the Action Executor. Exact idempotent replay and authoritative
   failure routing remain mandatory.

<a id="agent-platform-stale-job-recovery"></a>
### Agent-platform stale job recovery

1. Confirm which Job lease operation was reclaimed and whether the bounded attempt budget routed it
   to retry, dead letter, or `NEEDS_HUMAN`.
2. Check worker process availability, lease heartbeat telemetry, PostgreSQL health, and checkpoint
   continuity. Correlate with the durable audit trail rather than relying on telemetry alone.
3. Do not manually acknowledge or delete the Job. PostgreSQL claim/lease ownership and replay-safe
   handlers determine the next legal action.

<a id="recovery-execution-failure"></a>
### Recovery execution failure

1. Treat this as urgent because an approved recovery did not produce a confirmed successful
   execution. Inspect the immutable ActionExecution record, before/after snapshot bindings, and
   deterministic failure classification.
2. For timeout or uncertain outcomes, preserve the target lock/idempotency record and route to a
   human. Never issue a second untracked mutation.
3. If verification later fails, use bounded re-diagnosis or human handoff. Never redeploy the known
   faulty version and never invent compensation for `rollback_service`.

<a id="tool-gateway-retry-ratio"></a>
### Tool Gateway retry ratio

1. Split attempts and retries by registered tool and version, then verify the dependency's health
   and the fixed timeout/retry classifications.
2. Confirm the Tool Gateway still rejects unsafe arguments, writes from Diagnosis, unknown versions,
   and oversized results. Do not bypass it with raw URLs, paths, or shell commands.
3. If retry exhaustion creates missing Evidence, report the missing evidence and uncertainty rather
   than producing a confidence-only diagnosis.

<a id="model-call-errors"></a>
### Model call errors

1. Identify the registered provider/model and typed outcome. Consult content-free traces and
   persisted ModelCall metadata; do not copy prompt or response content into telemetry.
2. Confirm the exact active Prompt Registry version, timeout, token budget, and model availability.
3. Preserve deterministic malformed/refusal/timeout routing. A model failure must not skip schema
   validation, Evidence Gate, Policy, approval, execution, or verification.

## Shared observability alert

<a id="telemetry-collector-down"></a>
### Telemetry collector down

1. Check the `otel-collector` container health and validate the checked-in Collector configuration.
   Then verify Prometheus target health and Loki/Tempo readiness from loopback-bound endpoints.
2. Treat telemetry produced during the outage as incomplete. Do not use absence of errors or spans
   as counter-evidence, and never declare recovery from missing observations.
3. Business requests and deterministic recovery controls intentionally fail open with respect to
   exporter failure. Restore the telemetry path without changing Incident state or reissuing a
   mutation.
