import type { RecoveryResult, VerificationSample } from "@/lib/recovery";

function displayState(value: string) {
  return value.replaceAll("_", " ");
}

function displayTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not recorded";
}

function SignalSnapshot({
  label,
  sample,
}: Readonly<{ label: string; sample: VerificationSample }>) {
  return (
    <article className="signal-snapshot">
      <p className="eyebrow">{label}</p>
      <h4>{displayTime(sample.observedAt)}</h4>
      <dl>
        <div>
          <dt>Error rate</dt>
          <dd>{(sample.errorRateBasisPoints / 100).toFixed(2)}%</dd>
        </div>
        <div>
          <dt>P95 latency</dt>
          <dd>{sample.p95LatencyMs.toLocaleString()} ms</dd>
        </div>
        <div>
          <dt>Health endpoint</dt>
          <dd>{sample.healthEndpointHealthy ? "Healthy" : "Unhealthy"}</dd>
        </div>
        <div>
          <dt>Deployed version</dt>
          <dd>{sample.deployedVersion}</dd>
        </div>
        <div>
          <dt>New alerts</dt>
          <dd>{sample.newAlertCount}</dd>
        </div>
      </dl>
    </article>
  );
}

export function RecoveryView({
  recovery,
}: Readonly<{ incidentId: string; recovery: RecoveryResult }>) {
  const { execution, verification, route, compensation } = recovery;
  if (execution === null) {
    return (
      <section aria-labelledby="recovery-result" className="recovery-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">CONTROLLED RECOVERY</p>
            <h2 id="recovery-result">Execution and verification</h2>
          </div>
        </div>
        <div className="panel">
          <p>No recovery execution has been recorded for this incident.</p>
        </div>
      </section>
    );
  }

  const evidenceLinks: ReadonlyArray<readonly [string, string]> = verification
    ? [
        ["Error rate", verification.evidence.errorRate],
        ["P95 latency", verification.evidence.p95Latency],
        ["Health endpoint", verification.evidence.healthEndpoint],
        ["Deployed version", verification.evidence.deployedVersion],
        ["New alerts", verification.evidence.newAlerts],
      ]
    : [];

  return (
    <section aria-labelledby="recovery-result" className="recovery-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">CONTROLLED RECOVERY</p>
          <h2 id="recovery-result">Execution and verification</h2>
        </div>
        <span
          className={`recovery-status status-${execution.status.toLowerCase()}`}
        >
          {displayState(execution.status)}
        </span>
      </div>

      <article className="panel recovery-execution">
        <div className="recovery-card-heading">
          <div>
            <p className="eyebrow">DETERMINISTIC EXECUTOR</p>
            <h3>rollback_service</h3>
          </div>
          <span>Execution v{execution.version}</span>
        </div>
        <dl className="recovery-metadata">
          <div>
            <dt>Service</dt>
            <dd>{execution.service}</dd>
          </div>
          <div>
            <dt>Environment</dt>
            <dd>{execution.environment}</dd>
          </div>
          <div>
            <dt>Target</dt>
            <dd>{execution.targetReference}</dd>
          </div>
          <div>
            <dt>Approval</dt>
            <dd>{execution.approvalId}</dd>
          </div>
          <div>
            <dt>Executor actor</dt>
            <dd>{execution.actorId}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{displayTime(execution.startedAt)}</dd>
          </div>
          <div>
            <dt>Completed</dt>
            <dd>{displayTime(execution.completedAt)}</dd>
          </div>
          <div>
            <dt>Failure code</dt>
            <dd>{execution.failureCode ?? "None"}</dd>
          </div>
        </dl>
        <div
          className="version-comparison"
          aria-label="Deployment version comparison"
        >
          <article>
            <p className="eyebrow">BEFORE</p>
            <h4>{execution.before.deployedVersion}</h4>
            <p>{displayTime(execution.before.observedAt)}</p>
            <p className="technical-id">
              Artifact {execution.before.artifactId}
            </p>
          </article>
          <span aria-hidden="true">→</span>
          <article>
            <p className="eyebrow">AFTER</p>
            <h4>{execution.after?.deployedVersion ?? "No after snapshot"}</h4>
            <p>{displayTime(execution.after?.observedAt ?? null)}</p>
            <p className="technical-id">
              {execution.after
                ? `Artifact ${execution.after.artifactId}`
                : "Execution did not produce a completed deployment snapshot."}
            </p>
          </article>
        </div>
        <details className="fingerprint-details">
          <summary>Integrity bindings</summary>
          <dl>
            <div>
              <dt>Execution</dt>
              <dd>{execution.executionFingerprint}</dd>
            </div>
            <div>
              <dt>Proposal</dt>
              <dd>{execution.proposalFingerprint}</dd>
            </div>
            <div>
              <dt>Policy decision</dt>
              <dd>{execution.policyDecisionFingerprint}</dd>
            </div>
            <div>
              <dt>Before SHA-256</dt>
              <dd>{execution.before.contentHash}</dd>
            </div>
            {execution.after ? (
              <div>
                <dt>After SHA-256</dt>
                <dd>{execution.after.contentHash}</dd>
              </div>
            ) : null}
          </dl>
        </details>
      </article>

      {verification === null ? (
        <div className="panel" role="status">
          <h3>Verification not recorded</h3>
          <p>
            The console will not declare recovery until the deterministic
            verifier records a result.
          </p>
        </div>
      ) : (
        <article className="panel recovery-verification">
          <div className="recovery-card-heading">
            <div>
              <p className="eyebrow">DETERMINISTIC HEALTH VERIFIER</p>
              <h3>Stability window</h3>
            </div>
            <span
              className={`verification-outcome outcome-${verification.outcome.toLowerCase()}`}
            >
              {verification.outcome}
            </span>
          </div>
          <p>
            {displayTime(verification.windowStartedAt)} –{" "}
            {displayTime(verification.windowEndedAt)} ·{" "}
            {verification.windowDurationSeconds}s · {verification.sampleCount}{" "}
            samples
          </p>
          <div className="signal-comparison">
            <SignalSnapshot
              label="FIRST SAMPLE"
              sample={verification.firstSample}
            />
            <SignalSnapshot
              label="LAST SAMPLE"
              sample={verification.lastSample}
            />
          </div>
          <div className="verification-reasons">
            <h4>
              {verification.outcome === "PASS"
                ? "All configured checks passed"
                : "Failed checks"}
            </h4>
            {verification.reasons.length === 0 ? (
              <p>No failure reason was recorded.</p>
            ) : (
              <ul>
                {verification.reasons.map((reason) => (
                  <li key={reason}>{displayState(reason)}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="verification-evidence">
            <h4>Signal evidence</h4>
            <ul>
              {evidenceLinks.map(([label, evidenceId]) => (
                <li key={evidenceId}>
                  <a href={`#evidence-${encodeURIComponent(evidenceId)}`}>
                    {label}: {evidenceId}
                  </a>
                </li>
              ))}
            </ul>
          </div>
          <details className="fingerprint-details">
            <summary>Verifier trace bindings</summary>
            <dl>
              <div>
                <dt>Decision</dt>
                <dd>{verification.decisionFingerprint}</dd>
              </div>
              <div>
                <dt>Observation</dt>
                <dd>{verification.observationFingerprint}</dd>
              </div>
              <div>
                <dt>Criteria</dt>
                <dd>{verification.criteriaFingerprint}</dd>
              </div>
              <div>
                <dt>Input</dt>
                <dd>{verification.inputFingerprint}</dd>
              </div>
              <div>
                <dt>Rules</dt>
                <dd>{verification.rulesVersion}</dd>
              </div>
              <div>
                <dt>Expires</dt>
                <dd>{displayTime(verification.expiresAt)}</dd>
              </div>
            </dl>
          </details>
        </article>
      )}

      {route ? (
        <article className="panel recovery-route">
          <p className="eyebrow">FAILURE / CLOSURE ROUTE</p>
          <h3>{displayState(route.status)}</h3>
          {route.transitions.length === 0 ? (
            <p>
              No post-verification lifecycle transition has been recorded yet.
            </p>
          ) : (
            <ol>
              {route.transitions.map((transition) => (
                <li key={transition.newVersion}>
                  <strong>
                    {displayState(transition.priorState)} →{" "}
                    {displayState(transition.newState)}
                  </strong>
                  <span>{transition.reason}</span>
                  <small>
                    {displayTime(transition.occurredAt)} · correlation{" "}
                    {transition.correlationId}
                  </small>
                </li>
              ))}
            </ol>
          )}
        </article>
      ) : null}

      <aside
        className="compensation-boundary"
        aria-label="Compensation authorization"
      >
        <strong>Compensation: {displayState(compensation.status)}</strong>
        <p>{compensation.detail}</p>
        <p>No separate compensation authorization exists for this execution.</p>
      </aside>
    </section>
  );
}
