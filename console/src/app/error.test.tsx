import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import GlobalError from "./error";

describe("GlobalError", () => {
  it("explains the fail-closed state and offers an explicit retry", () => {
    const reset = vi.fn();
    render(<GlobalError error={new Error("unavailable")} reset={reset} />);

    expect(
      screen.getByRole("heading", { name: "The console could not load" }),
    ).toBeVisible();
    expect(screen.getByText(/No backend action was attempted/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(reset).toHaveBeenCalledOnce();
  });
});
