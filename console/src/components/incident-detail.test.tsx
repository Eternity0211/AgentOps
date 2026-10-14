import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IncidentDetail } from "./incident-detail";

const mocks = vi.hoisted(() => ({
  loadEvidence: vi.fn(),
  loadDiagnosis: vi.fn(),
  loadIncident: vi.fn(),
  loadInvestigation: vi.fn(),
  loadRecovery: vi.fn(),
  loadTimeline: vi.fn(),
}));

vi.mock("@/lib/diagnosis", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/diagnosis")>()),
  loadDiagnosis: mocks.loadDiagnosis,
}));

vi.mock("@/lib/evidence", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/evidence")>()),
  loadEvidence: mocks.loadEvidence,
}));

vi.mock("@/lib/incidents", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/incidents")>()),
  loadIncident: mocks.loadIncident,
}));

vi.mock("@/lib/timeline", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/timeline")>()),
  loadTimeline: mocks.loadTimeline,
}));

vi.mock("@/lib/investigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/investigation")>()),
  loadInvestigation: mocks.loadInvestigation,
}));

vi.mock("@/lib/recovery", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/recovery")>()),
  loadRecovery: mocks.loadRecovery,
}));

const incident = {
  id: "incident-1",
  service: "orders",
  severity: "SEV2" as const,
  state: "EVIDENCE_REVIEW" as const,
  version: 3,
  openedAt: "2026-10-11T10:00:00Z",
  updatedAt: "2026-10-11T10:05:00Z",
  closedAt: "2026-10-11T10:30:00Z",
  cancelledAt: null,
  cancellationRequestedAt: null,
};

const transition = {
  kind: "transition" as const,
  priorVersion: 1,
  newVersion: 2,
  actorId: "operator-1",
  reason: "Begin investigation",
  correlationId: "correlation-1",
  causationId: "command-1",
  occurredAt: "2026-10-11T10:05:00Z",
  priorState: "TRIAGED",
  newState: "INVESTIGATING",
};

const cancellation = {
  kind: "cancellation_request" as const,
  priorVersion: 2,
  newVersion: 3,
  actorId: "operator-2",
  reason: "Stop safely",
  correlationId: "correlation-1",
  causationId: "command-2",
  occurredAt: "2026-10-11T10:10:00Z",
  stateWhenRequested: "READY_TO_EXECUTE",
  disposition: "DEFERRED_TO_SAFE_BOUNDARY",
};

const investigation = {
  schemaVersion: "1.0.0",
  workflowRunId: "run-1",
  graphVersion: "1.0.0",
  phase: "EVIDENCE_REVIEW" as const,
  status: "FAILED" as const,
  budgets: {
    steps: { used: 2, maximum: 4, remaining: 2 },
    replans: { used: 1, maximum: 1, remaining: 0 },
    toolCalls: { used: 2, maximum: 4, remaining: 2 },
    modelCalls: { used: 3, maximum: 6, remaining: 3 },
    tokens: { used: 300, maximum: 1000, remaining: 700 },
    costNanounits: { used: 30, maximum: 100, remaining: 70 },
  },
  plans: [
    {
      attempt: 1,
      planId: "plan-1",
      summary: "Collect independent evidence",
      modelCallId: "model-1",
      createdAt: "2026-10-11T10:01:00Z",
      steps: [
        {
          position: 1,
          stepId: "metrics",
          objective: "Inspect error rate",
          expectedSource: "METRIC",
          dependsOn: ["context"],
          parallelGroup: 0,
          toolCallId: "tool-1",
          toolName: "query_metrics",
          toolVersion: "1.0.0",
          status: "FAILED" as const,
          failureCode: "TOOL_TIMEOUT",
          startedAt: "2026-10-11T10:02:00Z",
          completedAt: "2026-10-11T10:03:00Z",
        },
      ],
    },
  ],
  replans: [
    {
      completedAttempt: 1,
      nextAttempt: 2,
      decisionFingerprint: "a".repeat(64),
      reasonCode: "MORE_EVIDENCE_REQUIRED",
      occurredAt: "2026-10-11T10:04:00Z",
    },
  ],
  checkpointSequence: 7,
  errorCode: "TOOL_TIMEOUT",
  updatedAt: "2026-10-11T10:05:00Z",
};

beforeEach(() => {
  mocks.loadDiagnosis.mockReset().mockResolvedValue(null);
  mocks.loadEvidence.mockReset().mockResolvedValue({
    items: [],
    nextCursor: null,
  });
  mocks.loadIncident.mockReset();
  mocks.loadInvestigation.mockReset().mockResolvedValue(null);
  mocks.loadRecovery.mockReset().mockResolvedValue({
    execution: null,
    verification: null,
    route: null,
    compensation: {
      eligible: false,
      separatelyAuthorized: false,
      status: "FORBIDDEN_FOR_ROLLBACK_SERVICE",
      detail: "rollback_service is non-compensable.",
    },
  });
  mocks.loadTimeline.mockReset();
});

describe("IncidentDetail", () => {
  it("renders authoritative lifecycle data and appends cursor pages", async () => {
    let resolveMore!: (value: {
      items: (typeof transition)[];
      nextCursor: null;
    }) => void;
    mocks.loadIncident.mockResolvedValue(incident);
    mocks.loadTimeline
      .mockResolvedValueOnce({
        items: [transition, cancellation],
        nextCursor: "opaque-next",
      })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveMore = resolve;
          }),
      );

    render(<IncidentDetail incidentId="incident-1" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading authorized");
    expect(
      await screen.findByRole("heading", { name: "incident-1" }),
    ).toBeVisible();
    expect(screen.getByText("EVIDENCE REVIEW")).toBeVisible();
    expect(
      screen.getByRole("heading", { name: /TRIAGED.*INVESTIGATING/ }),
    ).toBeVisible();
    expect(
      screen.getByText("Cancellation requested while READY TO EXECUTE"),
    ).toBeVisible();
    expect(
      screen.getByText("Disposition: DEFERRED TO SAFE BOUNDARY"),
    ).toBeVisible();
    expect(screen.getAllByText("Not set")).toHaveLength(2);
    expect(
      screen.getByRole("link", { name: "← All incidents" }),
    ).toHaveAttribute("href", "/incidents");

    fireEvent.click(screen.getByRole("button", { name: "Load more events" }));
    expect(
      screen.getByRole("button", { name: "Loading more events…" }),
    ).toBeDisabled();
    expect(mocks.loadTimeline).toHaveBeenLastCalledWith(
      "incident-1",
      "opaque-next",
      expect.any(AbortSignal),
    );
    await act(async () =>
      resolveMore({
        items: [
          {
            ...transition,
            priorVersion: 3,
            newVersion: 4,
            causationId: "command-3",
            priorState: "INVESTIGATING",
            newState: "EVIDENCE_REVIEW",
          },
        ],
        nextCursor: null,
      }),
    );
    expect(
      await screen.findByRole("heading", {
        name: /INVESTIGATING.*EVIDENCE REVIEW/,
      }),
    ).toBeVisible();
    expect(screen.getByText("3 events loaded")).toBeVisible();
    expect(screen.queryByRole("button", { name: /events/ })).toBeNull();
  });

  it("renders an empty authoritative timeline", async () => {
    mocks.loadIncident.mockResolvedValue({
      ...incident,
      closedAt: null,
      cancelledAt: "2026-10-11T10:20:00Z",
      cancellationRequestedAt: "2026-10-11T10:15:00Z",
    });
    mocks.loadTimeline.mockResolvedValue({ items: [], nextCursor: null });
    render(<IncidentDetail incidentId="incident-empty" />);
    expect(
      await screen.findByText("No lifecycle events have been recorded."),
    ).toBeVisible();
    expect(screen.getByText("0 events loaded")).toBeVisible();
    expect(
      screen.getByText("No diagnosis run has been recorded for this incident."),
    ).toBeVisible();
  });

  it("renders plans, tool progress, budgets, failures, and bounded replans", async () => {
    mocks.loadIncident.mockResolvedValue(incident);
    mocks.loadTimeline.mockResolvedValue({ items: [], nextCursor: null });
    mocks.loadInvestigation.mockResolvedValue(investigation);
    render(<IncidentDetail incidentId="incident-1" />);

    expect(
      await screen.findByRole("heading", { name: "Investigation progress" }),
    ).toBeVisible();
    expect(screen.getAllByText("EVIDENCE REVIEW")).toHaveLength(2);
    expect(
      screen.getByText("Replan budget exhausted.", { exact: false }),
    ).toBeVisible();
    expect(screen.getByText("Failure code: TOOL_TIMEOUT")).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Collect independent evidence" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "1. Inspect error rate" }),
    ).toBeVisible();
    expect(screen.getByText("Depends on: context")).toBeVisible();
    expect(screen.getByText("Failure: TOOL_TIMEOUT")).toBeVisible();
    expect(
      screen.getByText(/Attempt 1.*2: MORE EVIDENCE REQUIRED/),
    ).toBeVisible();
    expect(screen.getByText("Replans").parentElement).toHaveTextContent(
      "1 used · 0 remaining · 1 maximum",
    );
  });

  it("renders handoff and empty replan states", async () => {
    mocks.loadIncident.mockResolvedValue(incident);
    mocks.loadTimeline.mockResolvedValue({ items: [], nextCursor: null });
    mocks.loadInvestigation.mockResolvedValue({
      ...investigation,
      status: "HUMAN_HANDOFF",
      phase: "HUMAN_HANDOFF",
      budgets: {
        ...investigation.budgets,
        replans: { used: 0, maximum: 1, remaining: 1 },
      },
      replans: [],
      errorCode: null,
      plans: [
        {
          ...investigation.plans[0]!,
          steps: [
            {
              ...investigation.plans[0]!.steps[0]!,
              dependsOn: [],
              failureCode: null,
            },
          ],
        },
      ],
    });
    render(<IncidentDetail incidentId="incident-1" />);

    expect(
      await screen.findByText("Human handoff required.", { exact: false }),
    ).toBeVisible();
    expect(screen.getByText("No replan has been recorded.")).toBeVisible();
    expect(screen.queryByText("Depends on: context")).toBeNull();
  });

  it("fails closed and retries the complete incident view", async () => {
    mocks.loadIncident
      .mockRejectedValueOnce(new DOMException("offline", "NetworkError"))
      .mockResolvedValueOnce(incident);
    mocks.loadTimeline.mockResolvedValue({ items: [], nextCursor: null });
    render(<IncidentDetail incidentId="incident-1" />);

    expect(
      await screen.findByRole("heading", {
        name: "Incident details could not be loaded",
      }),
    ).toBeVisible();
    expect(screen.getByText("No incident state was changed.")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry incident view" }),
    );
    expect(
      await screen.findByRole("heading", { name: "incident-1" }),
    ).toBeVisible();
    expect(mocks.loadIncident).toHaveBeenCalledTimes(2);
  });

  it("fails the complete read-only view when investigation loading fails", async () => {
    mocks.loadIncident.mockResolvedValue(incident);
    mocks.loadTimeline.mockResolvedValue({ items: [], nextCursor: null });
    mocks.loadInvestigation.mockRejectedValue(new Error("invalid projection"));
    render(<IncidentDetail incidentId="incident-1" />);
    expect(
      await screen.findByRole("heading", {
        name: "Incident details could not be loaded",
      }),
    ).toBeVisible();
  });

  it("fails the complete read-only view when evidence loading fails", async () => {
    mocks.loadIncident.mockResolvedValue(incident);
    mocks.loadTimeline.mockResolvedValue({ items: [], nextCursor: null });
    mocks.loadEvidence.mockRejectedValue(new Error("invalid evidence"));
    render(<IncidentDetail incidentId="incident-1" />);
    expect(
      await screen.findByRole("heading", {
        name: "Incident details could not be loaded",
      }),
    ).toBeVisible();
  });

  it("fails the complete read-only view when recovery integrity loading fails", async () => {
    mocks.loadIncident.mockResolvedValue(incident);
    mocks.loadTimeline.mockResolvedValue({ items: [], nextCursor: null });
    mocks.loadRecovery.mockRejectedValue(
      new Error("invalid recovery response"),
    );
    render(<IncidentDetail incidentId="incident-1" />);
    expect(
      await screen.findByRole("heading", {
        name: "Incident details could not be loaded",
      }),
    ).toBeVisible();
  });

  it("retries additional timeline failures without discarding loaded events", async () => {
    mocks.loadIncident.mockResolvedValue(incident);
    mocks.loadTimeline
      .mockResolvedValueOnce({ items: [transition], nextCursor: "next" })
      .mockRejectedValueOnce(new Error("offline"))
      .mockRejectedValueOnce(new DOMException("offline", "NetworkError"))
      .mockResolvedValueOnce({ items: [cancellation], nextCursor: null });
    render(<IncidentDetail incidentId="incident-1" />);
    await screen.findByRole("heading", { name: /TRIAGED.*INVESTIGATING/ });

    fireEvent.click(screen.getByRole("button", { name: "Load more events" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not be loaded",
    );
    expect(
      screen.getByRole("heading", { name: /TRIAGED.*INVESTIGATING/ }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Retry older events" }));
    await waitFor(() => expect(mocks.loadTimeline).toHaveBeenCalledTimes(3));
    expect(await screen.findByRole("alert")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry older events" }));
    expect(
      await screen.findByText("Cancellation requested while READY TO EXECUTE"),
    ).toBeVisible();
  });

  it("aborts initial requests and ignores late success on unmount", async () => {
    let resolveIncident!: (value: typeof incident) => void;
    let resolveTimeline!: (value: { items: never[]; nextCursor: null }) => void;
    mocks.loadIncident.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveIncident = resolve;
        }),
    );
    mocks.loadTimeline.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveTimeline = resolve;
        }),
    );
    const view = render(<IncidentDetail incidentId="incident-1" />);
    view.unmount();
    await act(async () => {
      resolveIncident(incident);
      resolveTimeline({ items: [], nextCursor: null });
    });
    expect(mocks.loadIncident).toHaveBeenCalledOnce();
  });

  it("ignores the expected initial abort rejection", async () => {
    const pending = (_id: string, signal: AbortSignal) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () =>
          reject(new DOMException("cancelled", "AbortError")),
        );
      });
    mocks.loadIncident.mockImplementation(pending);
    mocks.loadTimeline.mockImplementation((_id, _cursor, signal: AbortSignal) =>
      pending("incident-1", signal),
    );
    const view = render(<IncidentDetail incidentId="incident-1" />);
    view.unmount();
    await waitFor(() => expect(mocks.loadIncident).toHaveBeenCalledOnce());
  });

  it("ignores expected aborts while loading more timeline events", async () => {
    mocks.loadIncident.mockResolvedValue(incident);
    mocks.loadTimeline
      .mockResolvedValueOnce({ items: [transition], nextCursor: "next" })
      .mockImplementationOnce(
        (_id, _cursor, signal: AbortSignal) =>
          new Promise((_resolve, reject) => {
            signal.addEventListener("abort", () =>
              reject(new DOMException("cancelled", "AbortError")),
            );
          }),
      );
    const view = render(<IncidentDetail incidentId="incident-1" />);
    await screen.findByRole("heading", { name: /TRIAGED.*INVESTIGATING/ });
    fireEvent.click(screen.getByRole("button", { name: "Load more events" }));
    view.unmount();
    await waitFor(() => expect(mocks.loadTimeline).toHaveBeenCalledTimes(2));
  });

  it("ignores a late timeline success after unmount", async () => {
    let resolveMore!: (value: { items: never[]; nextCursor: null }) => void;
    mocks.loadIncident.mockResolvedValue(incident);
    mocks.loadTimeline
      .mockResolvedValueOnce({ items: [transition], nextCursor: "next" })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveMore = resolve;
          }),
      );
    const view = render(<IncidentDetail incidentId="incident-1" />);
    await screen.findByRole("heading", { name: /TRIAGED.*INVESTIGATING/ });
    fireEvent.click(screen.getByRole("button", { name: "Load more events" }));
    view.unmount();
    await act(async () => resolveMore({ items: [], nextCursor: null }));
    expect(mocks.loadTimeline).toHaveBeenCalledTimes(2);
  });
});
