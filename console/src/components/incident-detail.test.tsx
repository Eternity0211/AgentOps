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
  loadIncident: vi.fn(),
  loadTimeline: vi.fn(),
}));

vi.mock("@/lib/incidents", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/incidents")>()),
  loadIncident: mocks.loadIncident,
}));

vi.mock("@/lib/timeline", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/timeline")>()),
  loadTimeline: mocks.loadTimeline,
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

beforeEach(() => {
  mocks.loadIncident.mockReset();
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
