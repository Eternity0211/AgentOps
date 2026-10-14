import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalList } from "./approval-list";

const mocks = vi.hoisted(() => ({
  loadApprovals: vi.fn(),
  push: vi.fn(),
  query: "",
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/approvals",
  useRouter: () => ({ push: mocks.push }),
  useSearchParams: () => new URLSearchParams(mocks.query),
}));

vi.mock("@/lib/approvals", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/approvals")>()),
  loadApprovals: mocks.loadApprovals,
}));

const approval = {
  id: "approval-1",
  incidentId: "incident-1",
  proposalId: "proposal-1",
  proposalVersion: 1,
  proposalFingerprint: "a".repeat(64),
  policyDecisionFingerprint: "b".repeat(64),
  proposerActorId: "operator-1",
  riskLevel: "HIGH" as const,
  status: "PENDING" as const,
  version: 1,
  requestedAt: "2026-10-13T01:00:00Z",
  expiresAt: "2026-10-13T01:30:00Z",
  decidedAt: null,
  decidedBy: null,
  decisionReason: null,
  expired: false,
  invalidated: false,
  separationOfDuties: {
    required: true,
    satisfied: true,
    code: "INDEPENDENT_APPROVER_PRESENT",
    detail: "Independent approver present.",
  },
  schemaVersion: "1.0.0",
};

beforeEach(() => {
  mocks.query = "";
  mocks.loadApprovals.mockReset();
  mocks.push.mockReset();
  mocks.push.mockImplementation((href: string) => {
    mocks.query = href.split("?", 2)[1] ?? "";
  });
});

describe("ApprovalList", () => {
  it("filters and traverses opaque pages while showing control feedback", async () => {
    mocks.query = "status=PENDING&cursor=current";
    mocks.loadApprovals
      .mockResolvedValueOnce({ items: [approval], nextCursor: "next" })
      .mockResolvedValueOnce({
        items: [{ ...approval, id: "approval-2", invalidated: true }],
        nextCursor: null,
      })
      .mockResolvedValueOnce({
        items: [{ ...approval, expired: true }],
        nextCursor: null,
      });
    const view = render(<ApprovalList />);
    expect(
      await screen.findByRole("link", { name: "approval-1" }),
    ).toBeVisible();
    expect(screen.getByText("Independent approver present.")).toBeVisible();
    expect(mocks.loadApprovals).toHaveBeenCalledWith(
      "PENDING",
      "current",
      expect.any(AbortSignal),
    );

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    view.rerender(<ApprovalList />);
    expect(await screen.findByText("Reapproval required")).toBeVisible();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    view.rerender(<ApprovalList />);
    expect(await screen.findByText("Expired")).toBeVisible();
  });

  it("applies and clears the status filter", async () => {
    mocks.loadApprovals.mockResolvedValue({ items: [], nextCursor: null });
    const view = render(<ApprovalList />);
    await screen.findByRole("heading", {
      name: "No approvals match this filter",
    });
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "APPROVED" },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Apply filter" }).closest("form")!,
    );
    await waitFor(() =>
      expect(mocks.push).toHaveBeenLastCalledWith(
        "/approvals?status=APPROVED",
        {
          scroll: false,
        },
      ),
    );
    view.rerender(<ApprovalList />);
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "" },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Apply filter" }).closest("form")!,
    );
    await waitFor(() =>
      expect(mocks.push).toHaveBeenLastCalledWith("/approvals", {
        scroll: false,
      }),
    );
  });

  it("fails closed, retries, and ignores expected aborts", async () => {
    mocks.loadApprovals
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ items: [], nextCursor: null });
    const view = render(<ApprovalList />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No Approval state was changed",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("heading", {
      name: "No approvals match this filter",
    });
    view.unmount();

    mocks.loadApprovals.mockImplementation(
      (_status, _cursor, signal: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("cancelled", "AbortError")),
          );
        }),
    );
    const pending = render(<ApprovalList />);
    pending.unmount();
    await waitFor(() => expect(mocks.loadApprovals).toHaveBeenCalled());
  });
});
