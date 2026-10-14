import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ApprovalPage from "./page";

vi.mock("@/components/approval-detail", () => ({
  ApprovalDetail: ({ approvalId }: { approvalId: string }) => (
    <p>{approvalId}</p>
  ),
}));

describe("ApprovalPage", () => {
  it("passes the awaited route parameter", async () => {
    render(
      await ApprovalPage({
        params: Promise.resolve({ approvalId: "approval-route" }),
      }),
    );
    expect(screen.getByText("approval-route")).toBeVisible();
  });
});
