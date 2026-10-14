import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalRequestError } from "@/lib/approvals";

import { ApprovalDetail } from "./approval-detail";

const mocks = vi.hoisted(() => ({
  loadApproval: vi.fn(),
  decideApproval: vi.fn(),
}));

vi.mock("@/lib/approvals", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/approvals")>()),
  loadApproval: mocks.loadApproval,
  decideApproval: mocks.decideApproval,
}));

function detail(overrides: Record<string, unknown> = {}) {
  return {
    approval: {
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
        detail: "The reviewer is independent.",
      },
      schemaVersion: "1.0.0",
    },
    proposal: {
      action: "rollback_service",
      parameters: {
        service: "orders",
        introducing_deployment_evidence_id: "evidence-deploy",
      },
      prerequisites: { current_version_evidence_id: "evidence-current" },
      verification_conditions: {
        max_error_rate_basis_points: 100,
        max_p95_latency_ms: 500,
      },
      failure_handling: { route: "HUMAN_HANDOFF", max_rediagnosis_attempts: 0 },
      risk_assumptions: ["The current deployment is faulty."],
    },
    policy: {
      outcome: "APPROVAL_REQUIRED",
      environment: "PRODUCTION",
      blastRadius: "SINGLE_SERVICE",
      maintenanceWindow: "ACTIVE",
      policyVersion: "1.0.0",
      reasons: [
        { code: "APPROVAL_REQUIRED", detail: "Human approval is required." },
      ],
    },
    reviewFingerprint: "c".repeat(64),
    replacementProposal: null,
    proposalDiff: [],
    invalidation: null,
    ...overrides,
  };
}

beforeEach(() => {
  mocks.loadApproval.mockReset();
  mocks.decideApproval.mockReset();
});

describe("ApprovalDetail", () => {
  it("renders the immutable review and records approval without optimistic state", async () => {
    mocks.loadApproval.mockResolvedValue(detail());
    mocks.decideApproval.mockResolvedValue({ status: "APPROVED" });
    render(<ApprovalDetail approvalId="approval-1" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(
      await screen.findByRole("heading", { name: "Rollback orders" }),
    ).toBeVisible();
    expect(screen.getByText("Human approval is required.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Decision reason"), {
      target: { value: "Reviewed evidence and scope." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve proposal" }));
    await waitFor(() =>
      expect(mocks.decideApproval).toHaveBeenCalledWith(
        "approval-1",
        "approve",
        1,
        "Reviewed evidence and scope.",
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("now approved");
  });

  it("records rejection and reports expiry returned by the server", async () => {
    mocks.loadApproval.mockResolvedValue(detail());
    mocks.decideApproval
      .mockResolvedValueOnce({ status: "REJECTED" })
      .mockResolvedValueOnce({ status: "EXPIRED" });
    const view = render(<ApprovalDetail approvalId="approval-1" />);
    await screen.findByLabelText("Decision reason");
    fireEvent.change(screen.getByLabelText("Decision reason"), {
      target: { value: "Needs revision." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reject proposal" }));
    expect(await screen.findByRole("status")).toHaveTextContent("now rejected");
    view.rerender(<ApprovalDetail approvalId="approval-1" />);
    await screen.findByLabelText("Decision reason");
    fireEvent.change(screen.getByLabelText("Decision reason"), {
      target: { value: "Late decision." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve proposal" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "expired before",
    );
  });

  it("shows server errors with request correlation", async () => {
    mocks.loadApproval.mockResolvedValue(detail());
    mocks.decideApproval.mockRejectedValueOnce(
      new ApprovalRequestError(409, "State changed.", "request-1"),
    );
    render(<ApprovalDetail approvalId="approval-1" />);
    await screen.findByLabelText("Decision reason");
    fireEvent.change(screen.getByLabelText("Decision reason"), {
      target: { value: "Reviewed." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve proposal" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Request ID: request-1",
    );
  });

  it("shows ordinary decision errors without correlation", async () => {
    mocks.loadApproval.mockResolvedValue(detail());
    mocks.decideApproval.mockRejectedValueOnce(new Error("Offline."));
    render(<ApprovalDetail approvalId="approval-1" />);
    await screen.findByLabelText("Decision reason");
    fireEvent.change(screen.getByLabelText("Decision reason"), {
      target: { value: "Reviewed." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve proposal" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Offline.");
  });

  it("fails closed for malformed failures and missing reasons", async () => {
    mocks.loadApproval.mockResolvedValue(detail());
    mocks.decideApproval.mockRejectedValueOnce("unexpected rejection");
    render(<ApprovalDetail approvalId="approval-1" />);
    await screen.findByLabelText("Decision reason");
    fireEvent.change(screen.getByLabelText("Decision reason"), {
      target: { value: "Reviewed." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve proposal" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Decision failed.",
    );

    fireEvent.change(screen.getByLabelText("Decision reason"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve proposal" }));
    expect(mocks.decideApproval).toHaveBeenCalledTimes(1);

    const reason = screen.getByLabelText("Decision reason");
    reason.removeAttribute("name");
    fireEvent.submit(reason.closest("form")!);
    expect(mocks.decideApproval).toHaveBeenCalledTimes(1);
  });

  it("renders invalidated, expired, and separation-restricted terminal states", async () => {
    mocks.loadApproval.mockResolvedValueOnce(
      detail({
        approval: {
          ...detail().approval,
          invalidated: true,
          expired: true,
          separationOfDuties: {
            required: true,
            satisfied: false,
            code: "SELF_APPROVAL_FORBIDDEN",
            detail: "A different approver is required.",
          },
        },
        invalidation: {
          invalidatedBy: "operator-1",
          invalidatedAt: "2026-10-13T01:10:00Z",
        },
        proposalDiff: [{ path: "$.proposal_version", before: 1, after: 2 }],
      }),
    );
    render(<ApprovalDetail approvalId="approval-1" />);
    expect(await screen.findByText(/material proposal revision/)).toBeVisible();
    expect(screen.getByText(/has expired/)).toBeVisible();
    expect(
      screen.getAllByText("A different approver is required."),
    ).toHaveLength(2);
    expect(
      screen.getByRole("heading", { name: "Immutable proposal diff" }),
    ).toBeVisible();
    expect(
      screen.getByText("No decision is available for this record."),
    ).toBeVisible();
  });

  it("fails closed on load errors, retries, and ignores abort on unmount", async () => {
    mocks.loadApproval
      .mockRejectedValueOnce(new Error("corrupt"))
      .mockResolvedValueOnce(detail());
    const view = render(<ApprovalDetail approvalId="approval-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "verified review snapshot",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("heading", { name: "Rollback orders" });
    view.unmount();

    mocks.loadApproval.mockImplementation(
      (_id, signal: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("cancelled", "AbortError")),
          );
        }),
    );
    const pending = render(<ApprovalDetail approvalId="approval-2" />);
    pending.unmount();
    await waitFor(() => expect(mocks.loadApproval).toHaveBeenCalled());
  });
});
