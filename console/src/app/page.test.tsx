import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("renders the accessible console foundation and safety boundary", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "AgentOps Incident Commander",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Console foundation ready",
    );
    expect(
      screen.getByRole("heading", { name: "Authority stays deterministic" }),
    ).toBeVisible();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("/api/v1")).toBeVisible();
  });
});
