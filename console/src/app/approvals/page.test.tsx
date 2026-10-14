import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ApprovalsPage from "./page";

vi.mock("@/components/approval-list", () => ({
  ApprovalList: () => <p>approval list</p>,
}));

describe("ApprovalsPage", () => {
  it("renders the Approval center", () => {
    render(<ApprovalsPage />);
    expect(screen.getByText("approval list")).toBeVisible();
  });
});
