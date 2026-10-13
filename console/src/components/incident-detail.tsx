"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { EvidenceView } from "@/components/evidence-view";
import { DiagnosisResults } from "@/components/diagnosis-results";
import { loadDiagnosis, type DiagnosisResult } from "@/lib/diagnosis";
import { loadEvidence, type EvidencePage } from "@/lib/evidence";
import {
  loadIncident,
  type IncidentDetail as IncidentRecord,
} from "@/lib/incidents";
import {
  loadInvestigation,
  type InvestigationProgress,
} from "@/lib/investigation";
import {
  loadTimeline,
  type TimelineEvent,
  type TimelinePage,
} from "@/lib/timeline";

type DetailState =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      incident: IncidentRecord;
      timeline: TimelinePage;
      investigation: InvestigationProgress | null;
      diagnosis: DiagnosisResult | null;
      evidence: EvidencePage;
    };

function displayState(value: string) {
  return value.replaceAll("_", " ");
}

function displayTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not set";
}

function EventTitle({ event }: Readonly<{ event: TimelineEvent }>) {
  return event.kind === "transition" ? (
    <>
      {displayState(event.priorState)} <span aria-hidden="true">→</span>{" "}
      {displayState(event.newState)}
    </>
  ) : (
    <>Cancellation requested while {displayState(event.stateWhenRequested)}</>
  );
}

const budgetLabels = {
  steps: "Steps",
  replans: "Replans",
  toolCalls: "Tool calls",
  modelCalls: "Model calls",
  tokens: "Tokens",
  costNanounits: "Cost (nanounits)",
} as const;

function InvestigationView({
  investigation,
}: Readonly<{ investigation: InvestigationProgress | null }>) {
  if (investigation === null) {
    return (
      <section
        aria-labelledby="investigation-progress"
        className="investigation-section"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">SERVER-PERSISTED PROGRESS</p>
            <h2 id="investigation-progress">Investigation progress</h2>
          </div>
        </div>
        <div className="panel">
          <p>No diagnosis run has been recorded for this incident.</p>
        </div>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="investigation-progress"
      className="investigation-section"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">SERVER-PERSISTED PROGRESS</p>
          <h2 id="investigation-progress">Investigation progress</h2>
        </div>
        <span
          className={`progress-status status-${investigation.status.toLowerCase()}`}
        >
          {displayState(investigation.status)}
        </span>
      </div>

      {investigation.status === "HUMAN_HANDOFF" ? (
        <p className="progress-notice" role="status">
          Human handoff required. Automated investigation has stopped.
        </p>
      ) : null}
      {investigation.budgets.replans.remaining === 0 ? (
        <p className="progress-notice" role="status">
          Replan budget exhausted. No further automatic replan is available.
        </p>
      ) : null}
      {investigation.errorCode ? (
        <p className="progress-notice" role="alert">
          Failure code: {investigation.errorCode}
        </p>
      ) : null}

      <dl className="progress-metadata panel">
        <div>
          <dt>Phase</dt>
          <dd>{displayState(investigation.phase)}</dd>
        </div>
        <div>
          <dt>Workflow run</dt>
          <dd>{investigation.workflowRunId}</dd>
        </div>
        <div>
          <dt>Checkpoint</dt>
          <dd>{investigation.checkpointSequence}</dd>
        </div>
        <div>
          <dt>Graph version</dt>
          <dd>{investigation.graphVersion}</dd>
        </div>
        <div>
          <dt>Projection version</dt>
          <dd>{investigation.schemaVersion}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{displayTime(investigation.updatedAt)}</dd>
        </div>
      </dl>

      <h3>Resource budgets</h3>
      <dl className="budget-grid">
        {Object.entries(investigation.budgets).map(([key, budget]) => (
          <div key={key}>
            <dt>{budgetLabels[key as keyof typeof budgetLabels]}</dt>
            <dd>
              <strong>{budget.used}</strong> used · {budget.remaining} remaining
              · {budget.maximum} maximum
            </dd>
          </div>
        ))}
      </dl>

      <div className="investigation-history">
        {investigation.plans.map((plan) => (
          <article className="plan-card" key={plan.planId}>
            <div className="plan-heading">
              <div>
                <p className="eyebrow">ATTEMPT {plan.attempt}</p>
                <h3>{plan.summary}</h3>
              </div>
              <span>{displayTime(plan.createdAt)}</span>
            </div>
            <p className="technical-id">
              Plan {plan.planId} · model call {plan.modelCallId}
            </p>
            <ol className="tool-progress-list">
              {plan.steps.map((step) => (
                <li key={step.toolCallId}>
                  <div className="tool-progress-heading">
                    <h4>
                      {step.position}. {step.objective}
                    </h4>
                    <span
                      className={`tool-status status-${step.status.toLowerCase()}`}
                    >
                      {displayState(step.status)}
                    </span>
                  </div>
                  <p>
                    {step.toolName} v{step.toolVersion} · {step.expectedSource}{" "}
                    · parallel group {step.parallelGroup}
                  </p>
                  {step.dependsOn.length > 0 ? (
                    <p>Depends on: {step.dependsOn.join(", ")}</p>
                  ) : null}
                  {step.failureCode ? (
                    <p role="alert">Failure: {step.failureCode}</p>
                  ) : null}
                  <dl className="tool-timing">
                    <div>
                      <dt>Started</dt>
                      <dd>{displayTime(step.startedAt)}</dd>
                    </div>
                    <div>
                      <dt>Completed</dt>
                      <dd>{displayTime(step.completedAt)}</dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ol>
          </article>
        ))}
      </div>

      <div className="replan-history">
        <h3>Bounded replan history</h3>
        {investigation.replans.length === 0 ? (
          <p>No replan has been recorded.</p>
        ) : (
          <ol>
            {investigation.replans.map((replan) => (
              <li key={replan.decisionFingerprint}>
                Attempt {replan.completedAttempt} → {replan.nextAttempt}:{" "}
                {displayState(replan.reasonCode)}
                <span>{displayTime(replan.occurredAt)}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

export function IncidentDetail({
  incidentId,
}: Readonly<{ incidentId: string }>) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<DetailState>({ status: "loading" });
  const [timelineBusy, setTimelineBusy] = useState(false);
  const [timelineError, setTimelineError] = useState(false);
  const timelineController = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    timelineController.current?.abort();
    setState({ status: "loading" });
    setTimelineBusy(false);
    setTimelineError(false);
    void Promise.all([
      loadIncident(incidentId, controller.signal),
      loadTimeline(incidentId, undefined, controller.signal),
      loadInvestigation(incidentId, controller.signal),
      loadDiagnosis(incidentId, controller.signal),
      loadEvidence(incidentId, undefined, controller.signal),
    ]).then(
      ([incident, timeline, investigation, diagnosis, evidence]) => {
        if (!controller.signal.aborted) {
          setState({
            status: "ready",
            incident,
            timeline,
            investigation,
            diagnosis,
            evidence,
          });
        }
      },
      (reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setState({ status: "error" });
        }
      },
    );
    return () => {
      controller.abort();
      timelineController.current?.abort();
    };
  }, [attempt, incidentId]);

  async function loadMore(
    current: Extract<DetailState, { status: "ready" }>,
    cursor: string,
  ) {
    const controller = new AbortController();
    timelineController.current?.abort();
    timelineController.current = controller;
    setTimelineBusy(true);
    setTimelineError(false);
    try {
      const next = await loadTimeline(incidentId, cursor, controller.signal);
      if (!controller.signal.aborted) {
        setState({
          ...current,
          timeline: {
            items: [...current.timeline.items, ...next.items],
            nextCursor: next.nextCursor,
          },
        });
      }
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setTimelineError(true);
      }
    } finally {
      if (!controller.signal.aborted) setTimelineBusy(false);
    }
  }

  if (state.status === "loading") {
    return (
      <main aria-busy="true" className="centered-state">
        <p role="status">Loading authorized incident details…</p>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="centered-state">
        <p className="eyebrow">INCIDENT READ</p>
        <h1>Incident details could not be loaded</h1>
        <p>No incident state was changed.</p>
        <button type="button" onClick={() => setAttempt((value) => value + 1)}>
          Retry incident view
        </button>
      </main>
    );
  }

  const { incident, timeline, investigation, diagnosis, evidence } = state;
  return (
    <main>
      <Link className="back-link" href="/incidents">
        ← All incidents
      </Link>
      <header className="page-heading incident-heading">
        <p className="eyebrow">INCIDENT DETAIL</p>
        <h1>{incident.id}</h1>
        <div className="incident-badges">
          <span>{incident.service}</span>
          <span className={`severity ${incident.severity.toLowerCase()}`}>
            {incident.severity}
          </span>
          <span>{displayState(incident.state)}</span>
        </div>
      </header>

      <section aria-labelledby="incident-summary" className="panel">
        <h2 id="incident-summary">Lifecycle summary</h2>
        <dl className="detail-grid">
          <div>
            <dt>Version</dt>
            <dd>{incident.version}</dd>
          </div>
          <div>
            <dt>Opened</dt>
            <dd>{displayTime(incident.openedAt)}</dd>
          </div>
          <div>
            <dt>Updated</dt>
            <dd>{displayTime(incident.updatedAt)}</dd>
          </div>
          <div>
            <dt>Cancellation requested</dt>
            <dd>{displayTime(incident.cancellationRequestedAt)}</dd>
          </div>
          <div>
            <dt>Cancelled</dt>
            <dd>{displayTime(incident.cancelledAt)}</dd>
          </div>
          <div>
            <dt>Closed</dt>
            <dd>{displayTime(incident.closedAt)}</dd>
          </div>
        </dl>
      </section>

      <InvestigationView investigation={investigation} />

      <DiagnosisResults result={diagnosis} />

      <EvidenceView incidentId={incidentId} initialPage={evidence} />

      <section aria-labelledby="workflow-timeline" className="timeline-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">AUTHORITATIVE HISTORY</p>
            <h2 id="workflow-timeline">State and workflow timeline</h2>
          </div>
          <span>{timeline.items.length} events loaded</span>
        </div>
        {timeline.items.length === 0 ? (
          <div className="panel">
            <p>No lifecycle events have been recorded.</p>
          </div>
        ) : (
          <ol className="timeline-list">
            {timeline.items.map((event) => (
              <li
                key={`${event.newVersion}-${event.kind}-${event.causationId}`}
              >
                <div className="timeline-marker" aria-hidden="true" />
                <article>
                  <div className="timeline-title">
                    <h3>
                      <EventTitle event={event} />
                    </h3>
                    <span>
                      v{event.priorVersion} → v{event.newVersion}
                    </span>
                  </div>
                  {event.kind === "cancellation_request" ? (
                    <p>Disposition: {displayState(event.disposition)}</p>
                  ) : null}
                  <p>{event.reason}</p>
                  <dl className="timeline-metadata">
                    <div>
                      <dt>Occurred</dt>
                      <dd>{displayTime(event.occurredAt)}</dd>
                    </div>
                    <div>
                      <dt>Actor</dt>
                      <dd>{event.actorId}</dd>
                    </div>
                    <div>
                      <dt>Correlation</dt>
                      <dd>{event.correlationId}</dd>
                    </div>
                    <div>
                      <dt>Causation</dt>
                      <dd>{event.causationId}</dd>
                    </div>
                  </dl>
                </article>
              </li>
            ))}
          </ol>
        )}
        {timelineError ? (
          <p role="alert">Additional timeline events could not be loaded.</p>
        ) : null}
        {timeline.nextCursor !== null ? (
          <button
            type="button"
            disabled={timelineBusy}
            onClick={() => void loadMore(state, timeline.nextCursor as string)}
          >
            {timelineBusy
              ? "Loading more events…"
              : timelineError
                ? "Retry older events"
                : "Load more events"}
          </button>
        ) : null}
      </section>
    </main>
  );
}
