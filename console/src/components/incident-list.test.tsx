import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IncidentList } from "./incident-list";

const mocks = vi.hoisted(() => ({
  loadIncidents: vi.fn(),
  push: vi.fn(),
  query: "",
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/incidents",
  useRouter: () => ({ push: mocks.push }),
  useSearchParams: () => new URLSearchParams(mocks.query),
}));

vi.mock("@/lib/incidents", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/incidents")>()),
  loadIncidents: mocks.loadIncidents,
}));

const firstIncident = {
  id: "incident-1",
  service: "orders",
  severity: "SEV2" as const,
  state: "EVIDENCE_REVIEW" as const,
  version: 3,
  openedAt: "2026-10-11T10:00:00Z",
  updatedAt: "2026-10-11T10:05:00Z",
};

beforeEach(() => {
  mocks.query = "";
  mocks.loadIncidents.mockReset();
  mocks.push.mockReset();
  mocks.push.mockImplementation((href: string) => {
    mocks.query = href.split("?", 2)[1] ?? "";
  });
});

describe("IncidentList", () => {
  it("loads URL filters and traverses opaque cursor pages", async () => {
    mocks.query =
      "severity=SEV2&state=EVIDENCE_REVIEW&service=orders&cursor=current";
    mocks.loadIncidents
      .mockResolvedValueOnce({
        items: [firstIncident],
        nextCursor: "opaque-next",
      })
      .mockResolvedValueOnce({
        items: [{ ...firstIncident, id: "incident-2", severity: "SEV1" }],
        nextCursor: null,
      })
      .mockResolvedValueOnce({ items: [firstIncident], nextCursor: null });

    const view = render(<IncidentList />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(
      await screen.findByRole("link", { name: "incident-1" }),
    ).toHaveAttribute("href", "/incidents/incident-1");
    expect(screen.getByText("EVIDENCE REVIEW")).toBeVisible();
    expect(screen.getByText("SEV2", { selector: "span" })).toHaveClass("sev2");
    expect(mocks.loadIncidents).toHaveBeenLastCalledWith(
      {
        severity: "SEV2",
        state: "EVIDENCE_REVIEW",
        service: "orders",
        cursor: "current",
      },
      expect.any(AbortSignal),
    );
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(mocks.push).toHaveBeenLastCalledWith(
      "/incidents?severity=SEV2&state=EVIDENCE_REVIEW&service=orders&cursor=opaque-next",
      { scroll: false },
    );
    view.rerender(<IncidentList />);
    expect(
      await screen.findByRole("link", { name: "incident-2" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(mocks.push).toHaveBeenLastCalledWith(
      "/incidents?severity=SEV2&state=EVIDENCE_REVIEW&service=orders&cursor=current",
      { scroll: false },
    );
    view.rerender(<IncidentList />);
    expect(
      await screen.findByRole("link", { name: "incident-1" }),
    ).toBeVisible();
  });

  it("writes trimmed filters to the URL and clears pagination", async () => {
    mocks.loadIncidents.mockResolvedValue({ items: [], nextCursor: null });
    const view = render(<IncidentList />);
    await screen.findByRole("heading", {
      name: "No incidents match these filters",
    });

    fireEvent.change(screen.getByLabelText("Severity"), {
      target: { value: "SEV3" },
    });
    fireEvent.change(screen.getByLabelText("State"), {
      target: { value: "NEEDS_HUMAN" },
    });
    fireEvent.change(screen.getByLabelText("Service"), {
      target: { value: " payments " },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Apply filters" }).closest("form")!,
    );
    await waitFor(() =>
      expect(mocks.push).toHaveBeenLastCalledWith(
        "/incidents?severity=SEV3&state=NEEDS_HUMAN&service=payments",
        { scroll: false },
      ),
    );

    view.rerender(<IncidentList />);
    fireEvent.change(screen.getByLabelText("Severity"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Service"), {
      target: { value: "" },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Apply filters" }).closest("form")!,
    );
    await waitFor(() =>
      expect(mocks.push).toHaveBeenLastCalledWith("/incidents", {
        scroll: false,
      }),
    );
  });

  it("shows a fail-closed error and retries the same view", async () => {
    mocks.loadIncidents
      .mockRejectedValueOnce(new DOMException("offline", "NetworkError"))
      .mockResolvedValueOnce({ items: [], nextCursor: null });
    render(<IncidentList />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No incident state was changed",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("heading", {
        name: "No incidents match these filters",
      }),
    ).toBeVisible();
    expect(mocks.loadIncidents).toHaveBeenCalledTimes(2);
  });

  it("handles ordinary request errors", async () => {
    mocks.loadIncidents.mockRejectedValue(new Error("offline"));
    render(<IncidentList />);
    expect(await screen.findByRole("alert")).toBeVisible();
  });

  it("ignores the expected abort when unmounted", async () => {
    mocks.loadIncidents.mockImplementation(
      (_filters, signal: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("cancelled", "AbortError")),
          );
        }),
    );
    const view = render(<IncidentList />);
    view.unmount();
    await waitFor(() => expect(mocks.loadIncidents).toHaveBeenCalledOnce());
  });
});
