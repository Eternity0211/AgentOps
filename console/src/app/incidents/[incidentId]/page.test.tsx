import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import IncidentDetailPage from "./page";

vi.mock("@/components/incident-detail", () => ({
  IncidentDetail: ({ incidentId }: { incidentId: string }) => (
    <p>incident-detail:{incidentId}</p>
  ),
}));

describe("IncidentDetailPage", () => {
  it("passes the resolved dynamic route identity to the detail view", async () => {
    const page = await IncidentDetailPage({
      params: Promise.resolve({ incidentId: "incident-1" }),
      searchParams: Promise.resolve({}),
    });
    render(page);
    expect(screen.getByText("incident-detail:incident-1")).toBeVisible();
  });
});
