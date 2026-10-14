import type { PlatformObservability } from "@/lib/platform-observability";

function display(value: string) {
  return value.replaceAll("_", " ");
}

function displayTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Pending";
}

function displayCost(amountNanounits: number, currency: string) {
  return `${(amountNanounits / 1_000_000_000).toFixed(9)} ${currency}`;
}

export function PlatformObservabilityView({
  platform,
}: Readonly<{ platform: PlatformObservability }>) {
  return (
    <section
      aria-labelledby="platform-observability"
      className="platform-section"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">CONTENT-FREE CONTROL-PLANE METADATA</p>
          <h2 id="platform-observability">Agent platform observability</h2>
        </div>
        <span
          className={`audit-completeness audit-${platform.audit.status.toLowerCase()}`}
        >
          Audit {display(platform.audit.status)}
        </span>
      </div>

      <dl className="platform-usage panel" aria-label="Model usage totals">
        <div>
          <dt>Model calls</dt>
          <dd>{platform.usage.callCount}</dd>
        </div>
        <div>
          <dt>Total tokens</dt>
          <dd>{platform.usage.tokens.totalTokens.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Input / output</dt>
          <dd>
            {platform.usage.tokens.inputTokens.toLocaleString()} /{" "}
            {platform.usage.tokens.outputTokens.toLocaleString()}
          </dd>
        </div>
        <div>
          <dt>Cached / reasoning</dt>
          <dd>
            {platform.usage.tokens.cachedInputTokens.toLocaleString()} /{" "}
            {platform.usage.tokens.reasoningTokens.toLocaleString()}
          </dd>
        </div>
        <div>
          <dt>Metered / unavailable</dt>
          <dd>
            {platform.usage.meteredCallCount} /{" "}
            {platform.usage.unavailableCallCount}
          </dd>
        </div>
        <div>
          <dt>Cost</dt>
          <dd>
            {platform.usage.costs.length === 0
              ? "Not available"
              : platform.usage.costs
                  .map((item) =>
                    displayCost(item.amountNanounits, item.currency),
                  )
                  .join(" · ")}
          </dd>
        </div>
      </dl>

      {platform.modelCallsTruncated ? (
        <p className="progress-notice" role="status">
          Older model calls are omitted by the bounded API view; audit status is
          partial.
        </p>
      ) : null}

      <div className="platform-grid">
        <article className="panel platform-traces">
          <div className="platform-card-heading">
            <div>
              <p className="eyebrow">MODEL CALL TRACES</p>
              <h3>Prompt, latency, tokens, and cost</h3>
            </div>
            <span>{platform.modelCalls.length} displayed</span>
          </div>
          {platform.modelCalls.length === 0 ? (
            <p>No model-call trace has been recorded for this incident.</p>
          ) : (
            <ol className="model-trace-list">
              {platform.modelCalls.map((trace) => (
                <li key={trace.id}>
                  <div className="model-trace-heading">
                    <div>
                      <strong>{trace.node}</strong>
                      <span>
                        {trace.provider} / {trace.model} · attempt{" "}
                        {trace.attempt}
                      </span>
                    </div>
                    <span
                      className={`trace-status status-${trace.status.toLowerCase()}`}
                    >
                      {display(trace.status)}
                    </span>
                  </div>
                  <dl>
                    <div>
                      <dt>Started</dt>
                      <dd>{displayTime(trace.startedAt)}</dd>
                    </div>
                    <div>
                      <dt>Completed / latency</dt>
                      <dd>
                        {displayTime(trace.completedAt)} ·{" "}
                        {trace.durationMs === null
                          ? "pending"
                          : `${trace.durationMs} ms`}
                      </dd>
                    </div>
                    <div>
                      <dt>Tokens</dt>
                      <dd>
                        {trace.tokenUsage
                          ? `${trace.tokenUsage.totalTokens.toLocaleString()} total`
                          : display(
                              trace.meteringUnavailableReason ?? "pending",
                            )}
                      </dd>
                    </div>
                    <div>
                      <dt>Cost</dt>
                      <dd>
                        {trace.cost
                          ? displayCost(
                              trace.cost.amountNanounits,
                              trace.cost.currency,
                            )
                          : "Not available"}
                      </dd>
                    </div>
                    <div>
                      <dt>Prompt</dt>
                      <dd>
                        {trace.promptId} v{trace.promptVersion}
                      </dd>
                    </div>
                    <div>
                      <dt>Workflow run</dt>
                      <dd>{trace.workflowRunId}</dd>
                    </div>
                  </dl>
                  {trace.failureCode ? (
                    <p role="alert">Failure: {trace.failureCode}</p>
                  ) : null}
                  <details className="fingerprint-details">
                    <summary>Trace and integrity bindings</summary>
                    <dl>
                      <div>
                        <dt>Call</dt>
                        <dd>{trace.id}</dd>
                      </div>
                      <div>
                        <dt>Correlation / causation</dt>
                        <dd>
                          {trace.correlationId} / {trace.causationId}
                        </dd>
                      </div>
                      <div>
                        <dt>Prompt SHA-256</dt>
                        <dd>{trace.promptFingerprint}</dd>
                      </div>
                      <div>
                        <dt>Request SHA-256</dt>
                        <dd>{trace.requestHash}</dd>
                      </div>
                      <div>
                        <dt>Response SHA-256</dt>
                        <dd>{trace.responseHash ?? "Not recorded"}</dd>
                      </div>
                      <div>
                        <dt>Schema</dt>
                        <dd>
                          {trace.inputSchemaVersion} →{" "}
                          {trace.outputSchemaVersion}
                        </dd>
                      </div>
                    </dl>
                  </details>
                </li>
              ))}
            </ol>
          )}
        </article>

        <article className="panel platform-checkpoints">
          <div className="platform-card-heading">
            <div>
              <p className="eyebrow">DURABLE CHECKPOINT PROJECTIONS</p>
              <h3>Latest observed state per run</h3>
            </div>
            <span>{platform.checkpoints.length} runs</span>
          </div>
          {platform.checkpointsTruncated ? (
            <p className="progress-notice" role="status">
              Older run projections are omitted by the bounded API view.
            </p>
          ) : null}
          {platform.checkpoints.length === 0 ? (
            <p>No durable Diagnosis checkpoint projection has been recorded.</p>
          ) : (
            <ol className="checkpoint-list">
              {platform.checkpoints.map((checkpoint) => (
                <li key={checkpoint.workflowRunId}>
                  <strong>{checkpoint.workflowRunId}</strong>
                  <span>
                    Checkpoint {checkpoint.checkpointSequence} ·{" "}
                    {display(checkpoint.phase)} · {display(checkpoint.status)}
                  </span>
                  <small>
                    Graph {checkpoint.graphVersion} ·{" "}
                    {displayTime(checkpoint.observedAt)}
                  </small>
                  <code>{checkpoint.projectionFingerprint}</code>
                </li>
              ))}
            </ol>
          )}
        </article>
      </div>

      <article className="panel platform-audit" aria-label="Audit completeness">
        <div className="platform-card-heading">
          <div>
            <p className="eyebrow">DETERMINISTIC COMPLETENESS RULE 1.0.0</p>
            <h3>{display(platform.audit.status)}</h3>
          </div>
          <span>
            {platform.audit.observedEventCount} observed /{" "}
            {platform.audit.expectedEventCount} expected
          </span>
        </div>
        <p>
          Scope: displayed model calls. Missing{" "}
          {platform.audit.missingEventCount}; duplicate{" "}
          {platform.audit.duplicateEventCount}. The browser displays the backend
          decision and does not infer completeness.
        </p>
        {platform.audit.requirements.length === 0 ? (
          <p>
            No model-call audit event is expected because no call is displayed.
          </p>
        ) : (
          <ul className="audit-requirement-list">
            {platform.audit.requirements.map((item) => (
              <li key={`${item.modelCallId}-${item.eventType}`}>
                <span>
                  {item.modelCallId} · {item.eventType}
                </span>
                <strong className={`audit-${item.status.toLowerCase()}`}>
                  {display(item.status)}
                </strong>
                <small>
                  {item.observedSequences.length === 0
                    ? "No sequence"
                    : `Sequence ${item.observedSequences.join(", ")}`}
                </small>
              </li>
            ))}
          </ul>
        )}
      </article>
    </section>
  );
}
