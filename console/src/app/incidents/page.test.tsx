import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import IncidentsPage from "./page";

vi.mock("@/components/incident-list", () => ({
  IncidentList: () => <p>incident-list</p>,
}));

describe("IncidentsPage", () => {
  it("hosts the incident list", () => {
    render(<IncidentsPage />);
    expect(screen.getByText("incident-list")).toBeVisible();
  });
});
