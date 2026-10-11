import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NotFound from "./not-found";

describe("NotFound", () => {
  it("provides a clear route back to the console", () => {
    render(<NotFound />);

    expect(
      screen.getByRole("heading", { name: "This console view does not exist" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Return to the console" }),
    ).toHaveAttribute("href", "/");
  });
});
